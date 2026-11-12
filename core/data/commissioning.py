"""对点 / 传动验收会话的数据模型与纯判定逻辑（WP2）.

现场对点验收的产出是「逐点记录」：每个点下发什么、期望什么、实际回读到什么、
何时发生、结论如何、证据帧在哪。本模块只负责**数据结构 + 判定规则**，不含
任何 IO（不碰引擎、不碰数据库、不碰事件循环），便于表驱动单测。

设计约束：
* 会话创建时对点表做**快照**，运行中改点表不会让已有记录错乱；
* 每条记录强制留存下发帧 / 回读帧与时间戳，这是「可举证」的核心；
* SBO 被拒 / 超时一律判 fail，绝不计入通过；
* 自动判定规则可判定、不靠人眼；人工复核只能改 ``verdict`` 并留备注。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class SessionStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    STOPPED = "stopped"


class Verdict(StrEnum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    MANUAL = "manual"        # 人工判定（不自动判定时的兜底）


class ItemKind(StrEnum):
    YX = "YX"       # 遥信：置数/变位核对
    YC = "YC"       # 遥测：读命令回读值核对
    YK = "YK"       # 遥控：命令 + 变位确认
    STEP = "STEP"   # 步位置


@dataclass
class CommissionItem:
    """一个点的验收记录."""

    ioa: int
    name: str = ""
    kind: ItemKind = ItemKind.YX
    group: int = 1
    # 下发命令用的 IOA（现场遥控与其回读遥信常不同地址）；None/0 = 与 ioa 相同。
    # 本仓演示点表采用 YK/YX 同 IOA 配对，但真实装置必须允许显式指定。
    command_ioa: int | None = None
    expected: Any = None            # 期望值（YX bool / YC float / YK bool|int / STEP int）
    tolerance: float = 0.0         # YC 容差（绝对值；0 表示取量程比例，在编排层换算）
    actual: Any = None             # 实测回读值
    quality: str = ""              # 实测品质字符串（GOOD / IV|NT / ...）
    verdict: Verdict = Verdict.PENDING
    note: str = ""
    operator: str = ""
    checked_at: float = 0.0
    # 证据链
    tx_frame: str = ""             # 下发帧 hex
    rx_frame: str = ""             # 回读/变位帧 hex
    tx_time: float = 0.0
    rx_time: float = 0.0
    reason: str = ""               # 失败原因（超时 / 值不符 / 品质异常 / SBO 拒绝 ...）

    @property
    def target_ioa(self) -> int:
        """实际下发命令的 IOA（未显式指定时与回读 IOA 相同）。"""
        return self.command_ioa or self.ioa

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["verdict"] = self.verdict.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> CommissionItem:
        d = dict(d)
        d["kind"] = ItemKind(d.get("kind", "YX"))
        d["verdict"] = Verdict(d.get("verdict", "pending"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CommissionSession:
    """一次对点 / 传动验收会话."""

    id: str
    name: str = ""
    created_at: float = field(default_factory=time.time)
    operator: str = ""
    status: SessionStatus = SessionStatus.IDLE
    items: list[CommissionItem] = field(default_factory=list)
    # 点表快照（仅存精简信息，避免会话随时间膨胀）
    point_table_snapshot: list[dict] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    cursor: int = 0                # 当前执行到第几个点
    note: str = ""

    def to_dict(self, *, with_items: bool = True) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "operator": self.operator,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cursor": self.cursor,
            "note": self.note,
            "summary": self.summary(),
            "point_count": len(self.point_table_snapshot),
        }
        if with_items:
            d["items"] = [i.to_dict() for i in self.items]
        return d

    def summary(self) -> dict:
        counts = {v.value: 0 for v in Verdict}
        for it in self.items:
            counts[it.verdict.value] += 1
        return {
            "total": len(self.items),
            **counts,
            "done": counts[Verdict.PASS.value] + counts[Verdict.FAIL.value]
                    + counts[Verdict.MANUAL.value],
        }


# ── 纯判定规则 ────────────────────────────────────────────────────

def quality_bad(quality: str) -> bool:
    """品质异常判定：IV / NT / BL / SB / OV 任一置位即视为无效数据.

    空串视为 GOOD（历史数据/不携带品质的点）。按 IEC 60870-5-101 的
    五位置品质位字符串约定（``GOOD`` / ``IV|NT`` 等）。
    """
    if not quality:
        return False
    q = quality.upper()
    if q == "GOOD":
        return False
    return any(flag in q for flag in ("IV", "NT", "BL", "SB", "OV"))


def judge(item: CommissionItem, *, observed: Any, quality: str = "",
          rx_time: float | None = None, reason: str = "") -> CommissionItem:
    """把「观测到的值 + 品质」判定进 Item，返回同一对象（便于链式）.

    规则：
    * ``reason`` 非空（超时 / SBO 拒绝 / 命令失败）→ 直接 FAIL；
    * 品质异常 → FAIL，原因写明；
    * YC（float）→ 落在 ``expected ± tolerance`` 内为 PASS；
    * 其余类型 → 值相等（bool/int 做宽松归一化）为 PASS；
    * ``expected is None`` → 不做值比较，交人工判定（MANUAL 由调用方决定）。
    """
    item.actual = observed
    item.quality = quality or ""
    item.rx_time = rx_time or time.time()

    if reason:
        item.verdict = Verdict.FAIL
        item.reason = reason
        return item
    if quality_bad(item.quality):
        item.verdict = Verdict.FAIL
        item.reason = f"品质异常: {item.quality}"
        return item
    if item.expected is None:
        # 无期望值：保留 PENDING，供人工复核；调用方也可显式改 MANUAL
        item.reason = "未设期望值，待人工复核"
        return item

    ok = _values_match(item.kind, item.expected, observed, item.tolerance)
    item.verdict = Verdict.PASS if ok else Verdict.FAIL
    if not ok:
        item.reason = f"值不符: 期望 {item.expected!r}, 实测 {observed!r}"
    else:
        item.reason = ""
    return item


def _values_match(kind: ItemKind, expected: Any, observed: Any,
                  tolerance: float) -> bool:
    if observed is None:
        return False
    if kind == ItemKind.YC:
        try:
            return abs(float(observed) - float(expected)) <= float(tolerance)
        except (TypeError, ValueError):
            return False
    # bool / int 宽松归一化：True == 1、False == 0
    if isinstance(expected, bool):
        return bool(observed) is expected
    if isinstance(expected, (int, float)) and isinstance(observed, (int, float, bool)):
        return float(observed) == float(expected)
    return observed == expected


def build_items_from_points(points: list[dict],
                            command_ioas: dict[int, int] | None = None) -> list[CommissionItem]:
    """从点表快照生成待验收条目（只取可自动核对的类型）.

    ``points`` 为 ``/api/points`` 风格的行（``ioa/type/name/group/...``）。
    ``command_ioas`` 为 ``{回读 IOA: 下发命令 IOA}``：现场遥控与其回读遥信
    常不同地址，显式指定可避免把命令打到无关对象。未指定时默认同 IOA
    （本仓演示点表即 YK/YX 同 IOA 配对）。
    YK 点默认期望值留空由用户填写；YC 点按量程比例给默认容差。
    """
    items: list[CommissionItem] = []
    cmd_map = command_ioas or {}
    for p in points:
        kind_raw = str(p.get("type", "")).upper()
        try:
            kind = ItemKind(kind_raw)
        except ValueError:
            continue  # YM 等不参与逐点传动（保留在设计比对里）
        tol = 0.0
        if kind == ItemKind.YC:
            lo, hi = p.get("min_value"), p.get("max_value")
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and hi > lo:
                tol = float(hi - lo) * 0.005  # 量程 0.5%
        ioa = int(p["ioa"])
        items.append(CommissionItem(
            ioa=ioa,
            name=str(p.get("name", "")),
            kind=kind,
            group=int(p.get("group", 1) or 1),
            command_ioa=int(cmd_map[ioa]) if ioa in cmd_map else None,
            tolerance=tol,
        ))
    return items
