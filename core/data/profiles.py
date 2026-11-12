"""工程配置方案存储（WP5）——``configs/profiles/<名称>.yaml``.

一个「方案」= 一次工程调试所需的完整参数集：连接（host/port/公共地址）、
链路参数（t0~t3 / k / w）、ASDU 地址长度（WP1）、点表文件引用、告警阈值、
报告默认标题。现场按间隔/装置保存多套方案，换现场时一键切换，不必手抄参数。

存储沿用 ``core/config.py`` 的 YAML 形态（``AppConfig.save`` 的子集 + 额外节），
因此方案文件本身也能直接当 ``--config`` 使用（反之亦然，见 ``load_config``
的未知键忽略策略）——**旧版 ``--config`` 单文件启动方式不受影响**。

与历史库/审计库不同：方案是**人工维护的文本配置**，用户会用编辑器直接改，
所以这里不做哈希链、不做版本号，保持"可以直接用 git 管"的朴素形态。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# 方案名：允许中英文/数字/下划线/短横/点/空格，禁止路径分隔符与首字符点/下划线
_NAME_RE = re.compile(r"^[^/\\:*?\"<>|\x00-\x1f]{1,64}$")

# 活动方案文件名（列表时按 ``_`` 前缀排除）
_STATE_FILE = "_active.yaml"


class ProfileNameError(ValueError):
    """方案名非法（含路径分隔符/过长/空白等）."""


def validate_name(name: str) -> str:
    """校验并规范化方案名；非法即抛 ``ProfileNameError``（不静默改写）."""
    raw = (name or "").strip()
    if not raw:
        raise ProfileNameError("方案名不能为空")
    if raw.startswith((".", "_")):
        raise ProfileNameError("方案名不能以 . 或 _ 开头")
    if raw in (".", "..") or ".." in raw:
        raise ProfileNameError("方案名不能包含 ..")
    if not _NAME_RE.match(raw):
        raise ProfileNameError(f"方案名含非法字符：{name!r}")
    return raw


@dataclass
class ProfileInfo:
    """方案概要（列表用，不返回完整配置）."""

    name: str
    updated_at: float = 0.0
    size: int = 0
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "updated_at": self.updated_at,
            "size": self.size,
            "summary": self.summary,
        }


def summarize(data: dict) -> dict:
    """从方案 YAML 提取列表展示需要的摘要字段（全部缺省即空）."""
    conn = data.get("connection") or {}
    addr = data.get("asdu_address") or {}
    pts = data.get("point_table") or {}
    timers = data.get("timers") or {}
    flow = data.get("flow_control") or {}
    return {
        "mode": str(data.get("mode", "")),
        "host": str(conn.get("host", "")),
        "port": conn.get("port"),
        "common_addr": conn.get("common_addr"),
        "ca_length": addr.get("ca_length"),
        "ioa_length": addr.get("ioa_length"),
        "cot_length": addr.get("cot_length"),
        "point_table": str(pts.get("file", "")),
        "note": str(data.get("note", "")),
        "timers": {k: timers.get(k) for k in ("t0", "t1", "t2", "t3") if k in timers},
        "flow_control": {k: flow.get(k) for k in ("k", "w") if k in flow},
    }


class ProfileStore:
    """方案目录的读写门面（返回/接收纯 dict，便于与 ``AppConfig`` 互转）."""

    def __init__(self, root: str | Path = "configs/profiles"):
        self.root = Path(root)

    # ── 路径 ──────────────────────────────────────────────────────

    def path_of(self, name: str) -> Path:
        return self.root / f"{validate_name(name)}.yaml"

    def exists(self, name: str) -> bool:
        try:
            return self.path_of(name).is_file()
        except ProfileNameError:
            return False

    # ── 列表 / 读写 ───────────────────────────────────────────────

    def list_profiles(self) -> list[ProfileInfo]:
        if not self.root.is_dir():
            return []
        out: list[ProfileInfo] = []
        for p in sorted(self.root.glob("*.yaml")):
            if p.name.startswith("_"):
                continue
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                # 单个坏文件不应让整个列表失败：仍然列出（summary 空），
                # 用户可在界面上看到它并删除/修复。
                data = {}
            st = p.stat()
            out.append(ProfileInfo(
                name=p.stem, updated_at=st.st_mtime, size=st.st_size,
                summary=summarize(data) if isinstance(data, dict) else {},
            ))
        out.sort(key=lambda i: i.name)
        return out

    def load(self, name: str) -> dict | None:
        path = self.path_of(name)
        if not path.is_file():
            return None
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"方案 {name} 内容不是 YAML 映射")
        return data

    def save(self, name: str, data: dict) -> Path:
        path = self.path_of(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload["name"] = validate_name(name)
        payload["updated_at"] = time.time()
        path.write_text(
            yaml.dump(payload, default_flow_style=False, allow_unicode=True,
                      sort_keys=False),
            encoding="utf-8", newline="\n",
        )
        return path

    def delete(self, name: str) -> bool:
        path = self.path_of(name)
        if not path.is_file():
            return False
        path.unlink()
        if self.active() == validate_name(name):
            self.set_active("")
        return True

    # ── 活动方案（浏览器刷新后自动恢复的对象）─────────────────────

    def active(self) -> str:
        path = self.root / _STATE_FILE
        if not path.is_file():
            return ""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return ""
        name = str((data or {}).get("active", "") or "")
        return name if name and self.exists(name) else ""

    def set_active(self, name: str) -> None:
        path = self.root / _STATE_FILE
        if not name:
            if path.is_file():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump({"active": validate_name(name)}, allow_unicode=True),
            encoding="utf-8", newline="\n",
        )

    # ── YAML 文本导入导出 ─────────────────────────────────────────

    def to_yaml(self, name: str) -> str:
        data = self.load(name)
        if data is None:
            raise FileNotFoundError(name)
        return yaml.dump(data, default_flow_style=False, allow_unicode=True,
                         sort_keys=False)

    def from_yaml(self, text: str) -> dict:
        """解析导入文本；非映射/空文本/语法错误一律 ``ValueError``.

        ``yaml.YAMLError`` 不继承 ``ValueError``，必须显式转换——否则
        HTTP 层会把它当成未预期异常返回 500，而不是可读的 400。
        """
        try:
            data = yaml.safe_load(text) if text and text.strip() else None
        except yaml.YAMLError as e:
            raise ValueError(f"YAML 解析失败：{e}") from e
        if not isinstance(data, dict) or not data:
            raise ValueError("导入内容不是有效的方案 YAML 映射")
        return data
