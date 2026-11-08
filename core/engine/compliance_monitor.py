"""104 传输合规监视器（T79）——桥旁路的自动违规指认.

定位：透明桥（TcpBridge）已看到全量双向帧序列，本模块在其上叠加**判断层**，
把现场排障最费时的「哪条帧违反了规约」变成自动告警。观察-only：
监视器异常绝不影响透传（与桥同一原则）。

检测项（按 IEC 60870-5-104 传输规约）：

- **序号连续性**：I 帧发送序号必须逐帧 +1（mod 32768）——跳变/重复即违规；
- **确认合法性**：收帧携带的接收序号不得超前对端实际发送（确认未发出的帧）；
- **k/w 与 t1**：已发未确认 I 帧数超 k、或 t1 内未获确认 → 违规（每滞留期报一次）；
- **t2**：收到 I 帧后 t2 内对端未确认 → 违规（每滞留期报一次）；
- **t3**：链路启动后静默超 t3 → 违规（每滞留期报一次）；
- **U 帧时序**：未 STARTDT 即传数据、STARTDT 重复（中间无 STOPDT）、
  TESTFR ACT 未获 CON 重复发送。

时间基准：observe() 用传入 ts（真实流量）或调用方时钟；poll(now) 做
超时类检查（由桥的状态轮询驱动，无帧时 t3 也能被发现）。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU
from core.protocol.constants import (
    U_STARTDT_ACT,
    U_STARTDT_CON,
    U_STOPDT_ACT,
    U_TESTFR_ACT,
    U_TESTFR_CON,
)
from core.protocol.types import COT, TypeID

_SEQ_MOD = 32768
_MAX_VIOLATIONS = 200

# 应用层语义规则（T81）的参与类型集合——从 TypeID 单源派生
_CMD_TYPES = {t.value for t in TypeID if t.name.startswith("C_") and 45 <= t.value <= 64}
_MON_TYPES = {t.value for t in TypeID if t.name.startswith("M_")}
_ACT_EXPIRE_S = 60.0
_SPONT_WINDOW_S = 10.0    # T86：同值自发帧重复窗口
_MAX_TIME_SKEW_S = 300.0  # T86：CP56 时标与观察时刻最大允许偏差（秒）


@dataclass
class _SideState:
    """单侧（主站/子站）的发送/接收账目."""
    started: bool = False
    send_seq: int | None = None       # 本端最近发送 I 帧序号（None=STARTDT 后未发）
    unacked: int = 0                  # 已发未确认 I 帧数
    last_send_time: float = 0.0       # 最近 I 帧发送时刻（t1）
    last_recv_i_time: float = 0.0     # 最近接收 I 帧时刻（t2）
    last_ack_time: float = 0.0        # 最近本端发出确认的时刻（t2 完成）
    t1_reported: bool = False
    t2_reported: bool = False
    pending_testfr: bool = False


@dataclass
class ComplianceViolation:
    """一条合规违规."""
    ts: float
    kind: str       # seq-jump / seq-dup / ack-ahead / t1 / t2 / t3 / k-exceed /
                    # no-startdt / startdt-dup / testfr-dup / decode
    side: str       # master / slave（违规行为归属侧）
    detail: str


@dataclass
class ComplianceMonitor:
    """按客户端连接（一条主站↔子站链路对）维护传输账目并指认违规."""

    t1: float = 15.0
    t2: float = 10.0
    t3: float = 20.0
    k: int = 12
    expected_ca: int | None = None   # T86：显式期望公共地址（None=首帧建基线）
    w: int = 8
    max_violations: int = _MAX_VIOLATIONS
    violations: deque = field(default_factory=lambda: deque(maxlen=_MAX_VIOLATIONS))
    violation_counts: dict = field(default_factory=dict)

    master: _SideState = field(default_factory=_SideState)   # 发送方向 = tx（主站→子站）
    slave: _SideState = field(default_factory=_SideState)    # 发送方向 = rx（子站→主站）
    last_frame_time: float = 0.0
    _pending_acts: dict = field(default_factory=dict)        # type_id → 最近 ACT 时刻（T81）
    _gi_pending: bool = False
    _ci_pending: bool = False
    _ca_baseline: int | None = None                          # T86：会话公共地址基线
    _last_spont: tuple | None = None                        # T86：最近自发帧 (type, ioa, value)
    _last_spont_ts: float = 0.0
    t3_reported: bool = False
    _frames_seen: int = 0

    # ── 观察入口 ──────────────────────────────────────────────

    def observe(self, direction: str, frame: bytes, ts: float | None = None) -> None:
        """喂一帧（direction: tx=主站→子站 / rx=子站→主站）."""
        now = ts if ts is not None else time.time()
        self.last_frame_time = now
        self.t3_reported = False  # 任何帧都解除 t3 静默
        self._frames_seen += 1
        try:
            apci, _ = APCICodec.decode(frame)
        except Exception:  # noqa: BLE001 — 解码失败由桥的 resync 计数覆盖
            return

        sender = self.master if direction == "tx" else self.slave
        receiver = self.slave if direction == "tx" else self.master

        if apci.frame_type.name == "U":
            self._observe_u(apci.u_func, direction, sender, now)
            return

        if apci.frame_type.name == "I":
            self._check_send_seq(sender, apci.tx_seq, direction, now)
            sender.unacked += 1
            sender.last_send_time = now
            receiver.last_recv_i_time = now
            if sender.unacked > self.k:
                self._add(now, "k-exceed", _side_of(direction),
                          f"未确认 I 帧达 {sender.unacked} 超过 k={self.k}")
            # I 帧的 rx_seq 字段同时确认接收方已发送的帧
            self._check_ack(receiver, apci.rx_seq, now, direction)
            sender.last_ack_time = now
            # 应用层语义检查（T81）
            self._observe_asdu(direction, frame, now)
        elif apci.frame_type.name == "S":
            # S 帧是发送方对**接收方**发送帧的显式确认
            self._check_ack(receiver, apci.rx_seq, now, direction)
            sender.last_ack_time = now

    # ── 周期检查（超时类）─────────────────────────────────────

    def poll(self, now: float | None = None) -> None:
        """超时类检查（t1/t2/t3）：由桥的状态轮询驱动，无帧也能发现静默违规."""
        now = now if now is not None else time.time()
        if not self.master.started and not self.slave.started:
            return
        if self.last_frame_time and now - self.last_frame_time > self.t3:
            if not self.t3_reported:
                self._add(now, "t3", "link", f"链路静默超过 t3={self.t3:.0f}s")
                self.t3_reported = True
        for side, label in ((self.master, "master"), (self.slave, "slave")):
            if not side.started:
                continue
            # t1：有未确认 I 帧，超 t1 未获确认
            if side.unacked > 0 and side.last_send_time:
                if now - side.last_send_time > self.t1 and not side.t1_reported:
                    self._add(now, "t1", label,
                              f"{side.unacked} 个 I 帧超过 t1={self.t1:.0f}s 未获确认")
                    side.t1_reported = True
            # t2：收到 I 帧后超 t2 未确认
            if side.last_recv_i_time > side.last_ack_time and side.last_recv_i_time:
                if now - side.last_recv_i_time > self.t2 and not side.t2_reported:
                    self._add(now, "t2", label,
                              f"收到 I 帧超过 t2={self.t2:.0f}s 未确认")
                    side.t2_reported = True

    # ── 读取 ──────────────────────────────────────────────────

    def violation_list(self, limit: int = 20) -> list[dict]:
        out = []
        for v in reversed(self.violations):  # 最新在前
            out.append({"ts": v.ts, "kind": v.kind, "side": v.side, "detail": v.detail})
            if len(out) >= limit:
                break
        return out

    def as_dict(self) -> dict:
        return {"violation_total": sum(self.violation_counts.values()),
                "counts": dict(self.violation_counts),
                "frames_seen": self._frames_seen}

    # ── 内部 ──────────────────────────────────────────────────

    def _add(self, ts: float, kind: str, side: str, detail: str) -> None:
        self.violations.append(ComplianceViolation(ts=ts, kind=kind, side=side,
                                                   detail=detail))
        self.violation_counts[kind] = self.violation_counts.get(kind, 0) + 1

    def _observe_u(self, func: int, direction: str, sender: _SideState,
                   now: float) -> None:
        peer = self.slave if direction == "tx" else self.master
        if func == U_STARTDT_ACT:
            if sender.started:
                self._add(now, "startdt-dup", _side_of(direction),
                          "STARTDT_ACT 重复（中间无 STOPDT）")
        elif func == U_STARTDT_CON:
            if not sender.started:
                # 启动完成：两侧序号基线复位
                for side in (self.master, self.slave):
                    side.started = True
                    side.send_seq = None
                    side.unacked = 0
        elif func == U_STOPDT_ACT:
            for side in (self.master, self.slave):
                side.started = False
        elif func == U_TESTFR_ACT:
            if sender.pending_testfr:
                self._add(now, "testfr-dup", _side_of(direction),
                          "TESTFR_ACT 未获确认即重复发送")
            sender.pending_testfr = True
        elif func == U_TESTFR_CON:
            # 对端（TESTFR_ACT 的发送方）的 pending 由本端 CON 解除
            peer.pending_testfr = False

    def _observe_asdu(self, direction: str, frame: bytes, now: float) -> None:
        """应用层语义检查（T81/T86）：方向/请求响应/召唤期/COT/CA/重复自发/时标.

        头部用 ``ASDU.decode_header``（不解析信息体——畸形对象体不影响监视）；
        T86 的重复帧/时标检查尝试 ``ASDU.decode``，失败一律跳过（保守）。
        规则刻意保守：仅指认无歧义的违规，宁漏勿错。
        """
        try:
            asdu = ASDU.decode_header(frame[6:])
        except Exception:  # noqa: BLE001 — 半包/畸形由桥 resync 覆盖
            return
        type_id = asdu.type_id
        value = type_id.value if isinstance(type_id, TypeID) else type_id
        cot = asdu.cot
        ca = asdu.common_addr
        from_master = direction == "tx"

        # ── T86：公共地址一致性（首帧建基线，后续不符即违规）──
        if self._ca_baseline is None:
            self._ca_baseline = ca
        elif ca != self._ca_baseline:
            self._add(now, "ca-mismatch", _side_of(direction),
                      f"公共地址 {ca} 与会话基线 {self._ca_baseline} 不符")
        if self.expected_ca is not None and ca != self.expected_ca:
            self._add(now, "ca-mismatch", _side_of(direction),
                      f"公共地址 {ca} 与期望配置 {self.expected_ca} 不符")

        if cot == 0:
            self._add(now, "cot-zero", _side_of(direction), "传送原因 COT=0（非法）")
        # 方向错位：子站发送控制激活帧 / 主站发送监视帧
        if (not from_master) and value in _CMD_TYPES and cot == COT.ACT:
            self._add(now, "dir-wrong", _side_of(direction),
                      f"监视方向出现控制激活帧（类型 {value}，COT=6）")
        if from_master and value in _MON_TYPES:
            self._add(now, "dir-wrong", _side_of(direction),
                      f"控制方向出现监视类型（类型 {value}）")
        # 请求/响应配对
        if from_master and cot == COT.ACT:
            if value == TypeID.C_IC_NA_1.value and self._gi_pending:
                self._add(now, "gi-not-term", _side_of(direction),
                          "总召唤未终止（未见 COT=10）即再次启动")
            self._pending_acts[value] = now
            if value == TypeID.C_IC_NA_1.value:
                self._gi_pending = True
            if value == TypeID.C_CI_NA_1.value:
                self._ci_pending = True
        if (not from_master) and cot == COT.ACTCON:
            sent_at = self._pending_acts.pop(value, None)
            if sent_at is None or now - sent_at > _ACT_EXPIRE_S:
                self._add(now, "no-request-ack", _side_of(direction),
                          f"无对应请求的响应帧（类型 {value}，COT=7）")
        # 总召唤数据必须在召唤期内
        if (not from_master) and not self._gi_pending and (cot == COT.INTROGEN or 21 <= cot <= 36):
            self._add(now, "intg-no-gi", _side_of(direction),
                      f"非总召唤期收到召唤响应数据（COT={cot}）")
        if (not from_master) and not self._ci_pending and COT.COUNTER_REQ <= cot <= 41:
            self._add(now, "ci-no-req", _side_of(direction),
                      f"非累计量召唤期收到累计量响应（COT={cot}）")
        # 总召唤终止帧到达 → 召唤期结束
        if (not from_master) and value == TypeID.C_IC_NA_1.value and cot == COT.INTROGEN:
            self._gi_pending = False

        # ── T86：重复自发帧（同类型/IOA/值连续重复，COT=3）──
        # 设备常在变化时重复上送同一值——同值自发帧连续出现即指认（NC/抖动缺陷）
        if (not from_master) and cot == COT.SPONT:
            try:
                full = ASDU.decode(frame[6:])
                first = full.objects[0] if full.objects else None
                ioa = getattr(first, "ioa", None)
                raw = getattr(first, "data", None)
                val = getattr(raw, "value", raw)
                key = (value, ioa, str(val))
                if key == self._last_spont and now - self._last_spont_ts < _SPONT_WINDOW_S:
                    self._add(now, "spont-duplicate", _side_of(direction),
                              f"连续重复自发帧（类型 {value} IOA={ioa} 值={val}）")
                self._last_spont = key
                self._last_spont_ts = now
                # 时标偏离（带 CP56 时标的对象）：与观察时刻差超阈值
                tag = getattr(first, "time_tag", None)
                if tag is not None and hasattr(tag, "to_epoch"):
                    delta = abs(tag.to_epoch() - now)
                    if delta > _MAX_TIME_SKEW_S:
                        self._add(now, "time-skew", _side_of(direction),
                                  f"时标偏离观察时刻 {delta:.0f}s（阈值 {_MAX_TIME_SKEW_S:.0f}s）")
            except Exception:  # noqa: BLE001 — 对象体解析失败一律跳过（保守）
                pass

    def _check_send_seq(self, sender: _SideState, seq: int, direction: str,
                        now: float) -> None:
        if not sender.started:
            self._add(now, "no-startdt", _side_of(direction),
                      "STARTDT 完成前发送 I 帧（传输数据）")
        if sender.send_seq is not None:
            expected = (sender.send_seq + 1) % _SEQ_MOD
            if seq != expected:
                kind = "seq-dup" if seq == sender.send_seq else "seq-jump"
                self._add(now, kind, _side_of(direction),
                          f"I 帧发送序号 {seq}，期望 {expected}")
        sender.send_seq = seq

    def _check_ack(self, receiver: _SideState, rx_seq: int, now: float,
                   direction: str) -> None:
        """rx_seq 确认接收方发送的帧；超前 = 确认未发出的帧."""
        if receiver.send_seq is None:
            return
        acked_up_to = (rx_seq - 1) % _SEQ_MOD
        # 接收方 send_seq 是其最近发送序号；确认不得超前
        distance = (rx_seq - 1 - receiver.send_seq) % _SEQ_MOD
        if distance < _SEQ_MOD // 2 and distance != 0:
            # rx_seq-1 超过了 send_seq → 确认了不存在的帧（违规归属确认帧的发送方）
            self._add(now, "ack-ahead", _side_of(direction),
                      f"确认序号 {rx_seq} 超前（对端仅发送至 {receiver.send_seq}）")
        # 未确认数 = send_seq 与 acked_up_to 之间的距离
        gap = (receiver.send_seq - acked_up_to) % _SEQ_MOD
        receiver.unacked = gap
        if gap == 0:
            receiver.t1_reported = False
        receiver.last_ack_time = now


def _side_of(direction: str) -> str:
    """tx（主站→子站）上的违规行为归属主站，反之子站."""
    return "master" if direction == "tx" else "slave"
