"""证据模型（WP8）——报告三种格式的**唯一数据源**.

设计要点：报告格式可以换（HTML / xlsx / PDF），但**证据内容必须一致**。
所以先把要归档的内容收敛成 :class:`Evidence`，再由各导出器渲染；
``tests/test_export_report.py`` 直接断言三种格式的逐点条数一致。

与 ``webui/report.py`` 的关系：那个模块生成的是**自包含 HTML**（含样式、可打印），
本包不替代它，而是把同一份数据喂给 xlsx / PDF 导出器；HTML 导出器复用它的渲染，
避免两套 HTML 漂移。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

_MAX_TEXT = 500


@dataclass
class EvidencePoint:
    """一条逐点证据（来自 WP2 验收会话的 CommissionItem）."""

    ioa: int
    name: str = ""
    kind: str = ""
    group: int = 0
    expected: str = ""
    actual: str = ""
    quality: str = ""
    verdict: str = ""
    reason: str = ""
    note: str = ""
    operator: str = ""
    tx_frame: str = ""
    rx_frame: str = ""
    checked_at: float = 0.0

    def to_row(self) -> list[str]:
        return [
            str(self.ioa), self.name, self.kind, str(self.group),
            self.expected, self.actual, self.quality, self.verdict,
            self.reason, self.note, self.operator, self.tx_frame, self.rx_frame,
            _fmt_ts(self.checked_at),
        ]


@dataclass
class Evidence:
    """一份可归档的测试证据包（会话 + 统计 + 逐点 + 审计 + 曲线）."""

    role: str = ""
    title: str = ""
    generated_at: float = field(default_factory=time.time)
    session: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    points: list[EvidencePoint] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    alarms: list[dict[str, Any]] = field(default_factory=list)
    conclusion: str = ""
    conclusion_kind: str = ""
    notes: str = ""
    chart_images: list[str] = field(default_factory=list)

    @property
    def point_count(self) -> int:
        return len(self.points)

    def summary_rows(self) -> list[tuple[str, str]]:
        """会话摘要键值对（三种格式共用，保证归档内容一致）."""
        rows = [
            ("角色 / Role", self.role or "—"),
            ("生成时间 / Generated", _fmt_ts(self.generated_at)),
            ("标题 / Title", self.title or "—"),
            ("结论 / Conclusion", self.conclusion or "—"),
            ("逐点证据条数 / Evidence rows", str(self.point_count)),
            ("帧条数 / Frames", str(len(self.frames))),
            ("事件条数 / Events", str(len(self.events))),
            ("审计记录条数 / Audit rows", str(len(self.audit))),
            ("告警条数 / Alarms", str(len(self.alarms))),
        ]
        for key, value in self.stats.items():
            if value is None:
                continue
            rows.append((str(key), str(value)[:_MAX_TEXT]))
        return rows


POINT_HEADERS = [
    "IOA", "名称", "类型", "组", "期望值", "实测值", "品质", "结论",
    "失败原因", "备注", "检查人", "下发帧", "回读帧", "检查时间",
]

AUDIT_HEADERS = [
    "时间", "操作人", "角色", "来源", "动作", "目标", "结果", "原因",
]


def _fmt_ts(ts: float) -> str:
    if not ts:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return "—"


def audit_row(rec: dict[str, Any]) -> list[str]:
    return [
        _fmt_ts(float(rec.get("ts") or 0)),
        str(rec.get("operator", "")),
        str(rec.get("role", "")),
        str(rec.get("source_ip", "")),
        str(rec.get("action", "")),
        str(rec.get("target", "")),
        str(rec.get("result", "")),
        str(rec.get("reason", ""))[:_MAX_TEXT],
    ]


def points_from_session(session: dict[str, Any]) -> list[EvidencePoint]:
    """把 ``CommissionSession`` dict 转成证据点列表（保留全部逐点字段）."""
    out: list[EvidencePoint] = []
    for item in session.get("items") or []:
        if not isinstance(item, dict):
            continue
        out.append(EvidencePoint(
            ioa=int(item.get("ioa") or 0),
            name=str(item.get("name", "")),
            kind=str(item.get("kind", "")),
            group=int(item.get("group") or 0),
            expected=_scalar(item.get("expected")),
            actual=_scalar(item.get("actual")),
            quality=str(item.get("quality", "")),
            verdict=str(item.get("verdict", "")),
            reason=str(item.get("reason", "")),
            note=str(item.get("note", "")),
            operator=str(item.get("operator", "")),
            tx_frame=str(item.get("tx_frame", "")),
            rx_frame=str(item.get("rx_frame", "")),
            checked_at=float(item.get("checked_at") or 0.0),
        ))
    return out


def _scalar(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    return str(value)
