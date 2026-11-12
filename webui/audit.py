"""操作审计服务 + 多用户身份（WP4a）.

审计：``core/data/audit.py`` 的哈希链存储之上的记录门面——
REST middleware 用 :data:`operator_context`（ContextVar）把
「谁、什么角色、从哪来」流到请求处理链路；``EngineBridge._cmd``
在命令汇聚点读取该上下文并附帧证据落链，被权限拒绝（401/403）
的请求在 middleware 就返回、**不入链**（验收判据：越权动作链上无痕）。

身份：``--auth-config users.yaml`` 提供多用户三角色
（viewer 只读 / operator 可操作 / admin 全权）；未配置时保留
单 token 兼容模式，行为与 v1.10.0 完全一致。
"""

from __future__ import annotations

import contextvars
import csv
import hashlib
import hmac
import io
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from core.data.audit import AuditRecord, AuditStore

logger = logging.getLogger(__name__)

ROLES = ("viewer", "operator", "admin")


@dataclass(frozen=True)
class Identity:
    """已认证操作者身份（兼容单 token 模式下 name 为空、role 为 admin）."""

    name: str = ""
    role: str = "admin"
    source_ip: str = ""


# 请求级身份上下文：token_auth middleware 写入，审计钩子/编排读取。
# 与 WP1 的 asdu address ContextVar 同模式——aiohttp 每请求一个 task，
# ContextVar 即请求隔离；非 HTTP 调用（--demo、内部任务）保持 None。
operator_context: contextvars.ContextVar[Identity | None] = contextvars.ContextVar(
    "operator_context", default=None
)


def current_identity() -> Identity | None:
    return operator_context.get()


def set_operator_context(identity: Identity | None) -> None:
    operator_context.set(identity)


@dataclass(frozen=True)
class AuditIntent:
    """本次请求要记的动作名与目标（middleware 从 path/body 解析一次）.

    action 用去掉 ``/api/`` 前缀的路径（如 ``master.yk``、
    ``commission.sessions/<id>/run``）；target 取 body 的 ``ioa``/
    ``name``/``id`` 等可归因字段，取不到留空。
    """

    action: str = ""
    target: str = ""


# 请求级动作意图：与 operator_context 同生命周期；命令汇聚点读取。
audit_intent: contextvars.ContextVar[AuditIntent | None] = contextvars.ContextVar(
    "audit_intent", default=None
)


def current_intent() -> AuditIntent | None:
    return audit_intent.get()


def set_audit_intent(intent: AuditIntent | None) -> None:
    audit_intent.set(intent)


class OperatorRegistry:
    """``--auth-config`` YAML 的内存态：token 哈希 → (name, role).

    YAML 明文保存 token（现场离线环境由用户自行管理文件权限），
    内存只保留 SHA-256，比较用 ``hmac.compare_digest``（常数时间）。
    """

    def __init__(self, entries: dict[str, tuple[str, str]] | None = None):
        # {sha256(token): (name, role)}
        self._entries: dict[str, tuple[str, str]] = dict(entries or {})

    @classmethod
    def from_yaml(cls, path: str | Path) -> OperatorRegistry:
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8")) if p.suffix == ".json" else None
        if data is None:
            import yaml

            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        users = (data or {}).get("users") or []
        entries: dict[str, tuple[str, str]] = {}
        for u in users:
            name = str(u.get("name", "")).strip()
            token = str(u.get("token", ""))
            role = str(u.get("role", "viewer")).strip()
            if not name or not token:
                raise ValueError(f"auth-config 用户缺少 name/token: {u!r}")
            if role not in ROLES:
                raise ValueError(f"auth-config 用户 {name} 角色非法: {role}（须为 {ROLES}）")
            entries[hashlib.sha256(token.encode("utf-8")).hexdigest()] = (name, role)
        if not entries:
            raise ValueError("auth-config 未定义任何用户（users 列表为空）")
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def authenticate(self, token: str) -> Identity | None:
        if not token:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        for known, entry in self._entries.items():
            # 少量用户线性比较即可保持常数时间语义（用户数 ≤ 现场班组规模）
            if hmac.compare_digest(known, digest):
                return Identity(name=entry[0], role=entry[1])
        return None

    def roles(self) -> list[dict]:
        """列出用户名与角色（不含任何 token 材料，供 /api/auth/users）。"""
        return [
            {"name": name, "role": role}
            for name, role in sorted(self._entries.values(), key=lambda e: e[0])
        ]


def role_allowed(role: str, method: str, path: str) -> bool:
    """三角色权限矩阵（可判定规则，与 api_contract.md §2.4d 一致）.

    - viewer：GET 全部 + /api/auth；写一律拒绝；
    - operator：GET + 命令/模拟/测试/桥启停等操作类 POST；点表写入、
      审计导出之外的管理动作与一切 DELETE 拒绝；
    - admin：全部放行。
    被拒请求返回 403 且不入审计链。
    """
    if role == "admin":
        return True
    if method == "GET":
        # 用户名单 admin 专属（含 GET）；其余 GET 三角色可读
        return not path.startswith("/api/auth/users")
    if role == "viewer":
        return False
    if method == "DELETE":
        # operator 不可删除任何资源（会话删除等管理动作 admin 专属）
        return False
    # operator：POST 只放行操作类（命令/模拟/传动/桥启停/测试），
    # 点表写入族与管理/用户类端点一律拒绝；GET 已在上面处理（users 除外）
    return not path.startswith(
        ("/api/points/", "/api/auth/users", "/api/profiles", "/api/users")
    )


class AuditService:
    """审计记录门面：落链 + 查询 + 校验 + 导出；写失败不外抛不打断主路径."""

    def __init__(self, store: AuditStore):
        self.store = store

    def record(
        self,
        action: str,
        result: str,
        *,
        operator: str = "",
        role: str = "",
        source_ip: str = "",
        target: str = "",
        reason: str = "",
        tx_frame: str = "",
        rx_frame: str = "",
        ts: float | None = None,
    ) -> bool:
        """追加一条记录；任何存储异常只记日志（审计缺条可被 verify 发现）."""
        try:
            self.store.append(
                AuditRecord(
                    ts=ts if ts is not None else time.time(),
                    operator=operator, role=role, source_ip=source_ip,
                    action=action, target=target, result=result,
                    reason=reason[:500], tx_frame=tx_frame, rx_frame=rx_frame,
                )
            )
            return True
        except Exception as e:  # noqa: BLE001 — 审计不得打断命令主路径
            logger.error(f"audit record failed: {e}")
            return False

    def list_records(self, **kw) -> list[dict]:
        return [r.to_dict() for r in self.store.list_records(**kw)]

    def verify(self) -> dict:
        return self.store.verify()

    def stats(self) -> dict:
        return self.store.stats()

    def export(self, fmt: str) -> tuple[str, str, str]:
        """导出全部记录：json / csv。返回 (body, content_type, suffix)."""
        records = [r.to_dict() for r in self.store.list_records(limit=5000)]
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "id", "ts", "operator", "role", "source_ip", "action",
                "target", "result", "reason", "tx_frame", "rx_frame", "hash",
            ])
            for r in records:
                writer.writerow([
                    r.get("id", ""), r.get("ts", ""), r.get("operator", ""),
                    r.get("role", ""), r.get("source_ip", ""), r.get("action", ""),
                    r.get("target", ""), r.get("result", ""), r.get("reason", ""),
                    r.get("tx_frame", ""), r.get("rx_frame", ""), r.get("hash", ""),
                ])
            return buf.getvalue(), "text/csv", "csv"
        if fmt == "json":
            body = json.dumps(
                {"ok": True, "records": records}, ensure_ascii=False, indent=2
            )
            return body, "application/json", "json"
        raise ValueError(f"unsupported audit export format: {fmt}")

    def shutdown(self) -> None:
        self.store.close()
