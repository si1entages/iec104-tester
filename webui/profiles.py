"""工程配置方案服务（WP5）.

把 :class:`core.data.profiles.ProfileStore` 的纯文本存取接到运行中的应用上：

- ``capture()``  —— 快照当前生效参数（连接 / 链路参数 / ASDU 地址长度 / 点表引用 /
  告警阈值 / 报告默认标题）；
- ``apply()``    —— 把方案写回运行中的应用与引擎（含 WP1 的 ``set_default``，
  保证非标地址长度也一并还原）；
- ``restore_active()`` —— 供前端 onMount / ``--profile`` 使用。

**启动时刻意不自动应用方案**：服务端启动保持确定性（端口/角色只由 CLI 与
``--config`` 决定），方案恢复由前端在挂载时显式调用 ``apply``，或由用户显式
``--profile <名称>``。这样 CI/e2e 与「旧版 --config 单文件启动」都不会被
磁盘上的历史状态悄悄改变行为。

写动作（保存/应用/删除/导入）经 WP4a 的审计链留痕；无认证（兼容模式）下与
``EngineBridge._cmd`` 同策略：无身份上下文则不记。
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from core.data.profiles import ProfileStore, validate_name

from .audit import current_identity

logger = logging.getLogger(__name__)


class ProfileService:
    """方案列表 / 捕获 / 应用 / 导入导出；所有方法返回纯 dict（可 JSON 化）."""

    def __init__(self, bridge, store: ProfileStore | None = None):
        self._bridge = bridge
        self.store = store or ProfileStore()

    # ── 读 ────────────────────────────────────────────────────────

    def list(self) -> dict:
        return {
            "ok": True,
            "profiles": [p.to_dict() for p in self.store.list_profiles()],
            "active": self.store.active(),
        }

    def get(self, name: str) -> dict | None:
        data = self.store.load(name)
        if data is None:
            return None
        from core.data.profiles import summarize

        return {"name": validate_name(name), "config": data,
                "summary": summarize(data)}

    def capture(self) -> dict:
        """当前运行态 → 方案 dict（可直接 save）."""
        cfg = self._bridge.config
        alarms = getattr(self._bridge, "alarms", None)
        alarm_cfg = getattr(alarms, "config", None)
        out: dict = {
            "mode": self._bridge.role,
            "connection": {
                "host": cfg.connection.host,
                "port": cfg.connection.port,
                "common_addr": cfg.connection.common_addr,
                "reconnect": cfg.connection.reconnect,
                "reconnect_interval": cfg.connection.reconnect_interval,
                "max_connections": cfg.connection.max_connections,
            },
            "timers": asdict(cfg.timers),
            "flow_control": asdict(cfg.flow_control),
            "asdu_address": asdict(cfg.asdu_address),
            "point_table": {"file": cfg.point_table.file},
            "note": "",
        }
        if alarm_cfg is not None:
            out["alarms"] = {
                "stale_seconds": alarm_cfg.stale_seconds,
                "comm_seconds": alarm_cfg.comm_seconds,
                "jump_delta": alarm_cfg.jump_delta,
                "debounce": alarm_cfg.debounce,
                "sound": alarm_cfg.sound,
            }
        st = getattr(self._bridge, "_status", None)
        if isinstance(st, dict):
            # 运行中（或浏览器里手改过）的连接参数以 status 为准，避免捕获到启动默认值
            out["connection"]["host"] = st.get("host", out["connection"]["host"])
            out["connection"]["port"] = st.get("port", out["connection"]["port"])
            out["connection"]["common_addr"] = st.get("addr", out["connection"]["common_addr"])
        return out

    # ── 写 ────────────────────────────────────────────────────────

    def save(self, name: str, config: dict | None = None) -> dict:
        payload = dict(config) if config else self.capture()
        path = self.store.save(name, payload)
        self._audit("profiles/save", validate_name(name), True)
        return {"ok": True, "name": validate_name(name), "path": str(path)}

    def delete(self, name: str) -> bool:
        ok = self.store.delete(name)
        if ok:
            self._audit("profiles/delete", name, True)
        return ok

    def apply(self, name: str) -> dict:
        """把方案写回运行态；返回逐项应用结果（供界面显示"还原了什么"）."""
        data = self.store.load(name)
        if data is None:
            raise FileNotFoundError(name)
        applied: list[str] = []

        cfg = self._bridge.config
        conn = data.get("connection") or {}
        if conn:
            for key in ("host", "port", "common_addr", "reconnect",
                        "reconnect_interval", "max_connections"):
                if key in conn:
                    setattr(cfg.connection, key, conn[key])
            st = getattr(self._bridge, "_status", None)
            if isinstance(st, dict):
                st["host"] = cfg.connection.host
                st["port"] = cfg.connection.port
                st["addr"] = cfg.connection.common_addr
            applied.append("connection")

        timers = data.get("timers") or {}
        for key in ("t0", "t1", "t2", "t3"):
            if key in timers:
                setattr(cfg.timers, key, float(timers[key]))
                applied.append(f"timers.{key}")

        flow = data.get("flow_control") or {}
        for key in ("k", "w"):
            if key in flow:
                setattr(cfg.flow_control, key, int(flow[key]))
                applied.append(f"flow_control.{key}")

        addr = data.get("asdu_address") or {}
        if addr:
            from core.protocol.address import AsduAddressConfig, set_default

            new_addr = AsduAddressConfig(
                ca_length=int(addr.get("ca_length", cfg.asdu_address.ca_length)),
                ioa_length=int(addr.get("ioa_length", cfg.asdu_address.ioa_length)),
                cot_length=int(addr.get("cot_length", cfg.asdu_address.cot_length)),
            )
            cfg.asdu_address = new_addr
            # WP1：进程级默认同步更新，编解码/离线解析立刻按新长度工作
            set_default(new_addr)
            applied.append("asdu_address")

        alarms = data.get("alarms") or {}
        alarm_svc = getattr(self._bridge, "alarms", None)
        if alarms and alarm_svc is not None:
            try:
                alarm_svc.configure(**alarms)
                applied.append("alarms")
            except (TypeError, ValueError) as e:  # 阈值非法不应让整个方案应用失败
                logger.warning("profile.alarms 应用失败：%s", e)

        pt = (data.get("point_table") or {}).get("file")
        if pt:
            r = self._apply_point_table(str(pt))
            if r is not None:
                applied.append("point_table")

        self.store.set_active(validate_name(name))
        self._audit("profiles/apply", validate_name(name), True,
                    detail=",".join(applied))
        return {"ok": True, "name": validate_name(name), "applied": applied}

    def _apply_point_table(self, file_ref: str) -> dict | None:
        """按方案引用导入点表；文件不存在时记日志并跳过（不中断方案应用）."""
        from pathlib import Path

        path = Path(file_ref)
        if not path.is_file():
            logger.warning("方案引用的点表文件不存在，已跳过：%s", file_ref)
            return None
        try:
            text = path.read_text(encoding="utf-8")
            engine = getattr(self._bridge.session, "engine", None)
            r = self._bridge.points.import_yaml(text, engine)
        except (OSError, ValueError) as e:
            logger.warning("方案点表导入失败：%s", e)
            return None
        self._bridge.config.point_table.file = file_ref
        return r

    def restore_active(self) -> dict | None:
        """应用记录中的活动方案（无则返回 None；供前端 onMount / --profile 用）."""
        name = self.store.active()
        if not name:
            return None
        try:
            return self.apply(name)
        except (FileNotFoundError, ValueError) as e:
            logger.warning("活动方案 %s 恢复失败：%s", name, e)
            return None

    # ── 导入导出 ──────────────────────────────────────────────────

    def export(self, name: str) -> tuple[str, str, str]:
        """返回 (yaml 文本, content_type, 文件名后缀)。"""
        return self.store.to_yaml(name), "application/x-yaml", "yaml"

    def import_yaml(self, name: str, text: str) -> dict:
        data = self.store.from_yaml(text)
        return self.save(name, data)

    # ── 内部 ──────────────────────────────────────────────────────

    def _audit(self, action: str, target: str, ok: bool, detail: str = "") -> None:
        ident = current_identity()
        if ident is None:
            return  # 兼容模式：无身份上下文不记（与 EngineBridge._cmd 同策略）
        try:
            self._bridge.audit.record(
                action, "ok" if ok else "fail",
                operator=ident.name, role=ident.role, source_ip=ident.source_ip,
                target=target, reason=detail,
            )
        except Exception as e:  # noqa: BLE001 — 审计不得打断配置主路径
            logger.error("profile audit failed: %s", e)
