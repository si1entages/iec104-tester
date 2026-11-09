"""值守告警引擎（T93）：让工具脱离盯屏值守.

四类规则（对当前角色的点值快照 + 连接状态周期评估，1Hz）：

  - **limit**  限值越限：YC 超出点表声明的 ``min_value``/``max_value``；
  - **stale**  死值/陈旧：点曾收到数据但 ``ts`` 距今超过 ``stale_seconds``（默认 60s）
               ——即原 T91 的点表陈旧判定（数据层前提：``data_store`` 各数据类的
               ``last_update_time``，wall clock；**不能复用只在值变化时写的
               ``last_change_time``**，恒定值周期上送会被误判陈旧）；
  - **jump**   突变：相邻两次更新变化幅度超过 ``jump_delta``（缺省关闭，可配置）；
  - **comm**   通信中断（仅 master 角色）：引擎 Running 但 rx 持续 ``comm_seconds``
               （默认 10s）无增长。

生命周期：触发（去抖：连续 ``debounce`` 次评估满足才告警）→ active →（可 ack）→
条件解除自动 cleared；全部记录进有界历史（供报告附「告警历史」段）。

实现说明：前端以 2s 轮询 ``GET /api/alarms`` 获取（计划中的 WS ``alarm`` 事件
改为轮询——避免为单一消费点扩 WS 契约；1Hz 评估 + 2s 轮询的时延对值守场景足够）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

_MAX_HISTORY = 500


@dataclass
class Alarm:
    """单条告警（含生命周期状态）."""

    id: int
    kind: str            # limit / stale / jump / comm
    ioa: int | None
    message: str
    ts: float
    acked: bool = False
    cleared_ts: float | None = None

    def to_dict(self, *, now: float | None = None) -> dict:
        age = round((now if now is not None else time.time()) - self.ts, 1)
        return {
            "id": self.id,
            "kind": self.kind,
            "ioa": self.ioa,
            "message": self.message,
            "ts": self.ts,
            "age_s": max(0.0, age),
            "acked": self.acked,
            "cleared": self.cleared_ts is not None,
        }


@dataclass
class AlarmConfig:
    """告警阈值（可通过 POST /api/alarms/config 运行时调整）."""

    stale_seconds: float = 60.0
    comm_seconds: float = 10.0
    jump_delta: float | None = None   # None=关闭
    debounce: int = 2                 # 连续 N 次评估满足才告警
    sound: bool = False               # 仅影响前端默认值回显


class AlarmService:
    """单角色桥的告警服务（master/slave 角色各一个；bridge 角色不创建）."""

    def __init__(self, bridge, *, stale_seconds: float = 60.0,
                 comm_seconds: float = 10.0, jump_delta: float | None = None,
                 debounce: int = 2) -> None:
        self.bridge = bridge
        self.config = AlarmConfig(stale_seconds=stale_seconds,
                                  comm_seconds=comm_seconds,
                                  jump_delta=jump_delta, debounce=debounce)
        self.active: dict[tuple[str, int | None], Alarm] = {}
        self.history: list[Alarm] = []
        self._next_id = 1
        self._streak: dict[tuple[str, int | None], int] = {}
        self._prev_values: dict[int, float] = {}
        self._last_rx: int | None = None
        self._rx_stall_since: float | None = None
        self._jump_cooldown: dict[int, float] = {}
        self.new_since_poll = 0   # 前端声音提示：自上次轮询以来的新告警数

    # ── 评估 ──────────────────────────────────────────────────────

    def evaluate(self) -> None:
        now = time.time()
        role = self.bridge.role
        status = self.bridge.status()
        points = self.bridge.snapshot_points()
        seen: set[tuple[str, int | None]] = set()

        # ① 限值越限 / ② 死值陈旧 / ③ 突变（逐点）
        for row in points:
            ioa = row.get("ioa")
            kind_prefix = str(row.get("type") or "")
            ts = row.get("ts") or 0
            # ① 限值（YC 且声明了限值）
            if kind_prefix == "YC" and row.get("min_value") is not None \
                    and row.get("max_value") is not None:
                value = row.get("value")
                if isinstance(value, (int, float)):
                    lo, hi = row["min_value"], row["max_value"]
                    key = ("limit", ioa)
                    seen.add(key)
                    if value < lo or value > hi:
                        self._raise(key, "limit", ioa,
                                    f"遥测越限：IOA {ioa} 值 {value} 超出 [{lo}, {hi}]", now)
                    else:
                        self._clear(key, now)
                    self._streak[key] = self._streak.get(key, 0)
            # ② 死值/陈旧（曾收到过数据才判）
            key = ("stale", ioa)
            seen.add(key)
            if ts > 0 and (now * 1000 - ts) / 1000.0 > self.config.stale_seconds:
                self._raise(key, "stale", ioa,
                            f"点值陈旧：IOA {ioa} 已 {(now * 1000 - ts) / 1000.0:.0f}s 未更新"
                            f"（阈值 {self.config.stale_seconds:.0f}s）", now)
            else:
                self._clear(key, now)
            # ③ 突变
            if self.config.jump_delta is not None and kind_prefix == "YC" \
                    and isinstance(row.get("value"), (int, float)):
                value = float(row["value"])
                prev = self._prev_values.get(ioa)
                self._prev_values[ioa] = value
                key = ("jump", ioa)
                seen.add(key)
                if prev is not None and abs(value - prev) > self.config.jump_delta:
                    last = self._jump_cooldown.get(ioa, 0.0)
                    if now - last > 60.0:
                        self._jump_cooldown[ioa] = now
                        self._raise(key, "jump", ioa,
                                    f"遥测突变：IOA {ioa} {prev} → {value}"
                                    f"（变化 {abs(value - prev):.2f} > 阈值 {self.config.jump_delta}）",
                                    now, debounce=1)
                else:
                    self._clear(key, now)

        # ④ 通信中断（仅 master：Running 且 rx 持续无增长）
        if role == "master":
            key = ("comm", None)
            seen.add(key)
            rx = status.get("rx")
            running = bool(status.get("running")) and status.get("state") == "Running"
            if isinstance(rx, int) and running:
                if self._last_rx is None or rx != self._last_rx[0]:
                    self._rx_stall_since = None
                    self._last_rx = (rx, now)
                elif self._rx_stall_since is None:
                    self._rx_stall_since = now
                stalled = (self._rx_stall_since is not None
                           and now - self._rx_stall_since > self.config.comm_seconds)
                if stalled:
                    self._raise(key, "comm", None,
                                f"通信中断：引擎 Running 但已 {now - self._rx_stall_since:.0f}s "
                                f"未收到任何报文（阈值 {self.config.comm_seconds:.0f}s）", now,
                                debounce=1)
                else:
                    self._clear(key, now)
            else:
                self._rx_stall_since = None
                self._last_rx = None
                self._clear(key, now)

        # 清理不再评估的键（点被删除等）
        for key in [k for k in self.active if k not in seen]:
            self._clear(key, now)

    def _raise(self, key: tuple[str, int | None], kind: str, ioa: int | None,
               message: str, now: float, *, debounce: int | None = None) -> None:
        if key in self.active:
            return
        need = self.config.debounce if debounce is None else debounce
        streak = self._streak.get(key, 0) + 1
        self._streak[key] = streak
        if streak < need:
            return
        self._streak[key] = 0
        alarm = Alarm(id=self._next_id, kind=kind, ioa=ioa, message=message, ts=now)
        self._next_id += 1
        self.active[key] = alarm
        self.history.append(alarm)
        if len(self.history) > _MAX_HISTORY:
            del self.history[:len(self.history) - _MAX_HISTORY]
        self.new_since_poll += 1

    def _clear(self, key: tuple[str, int | None], now: float) -> None:
        self._streak[key] = 0
        alarm = self.active.pop(key, None)
        if alarm is not None and alarm.cleared_ts is None:
            alarm.cleared_ts = now

    # ── 查询 / 操作 ───────────────────────────────────────────────

    def snapshot(self) -> dict:
        now = time.time()
        return {
            "ok": True,
            "config": {
                "stale_seconds": self.config.stale_seconds,
                "comm_seconds": self.config.comm_seconds,
                "jump_delta": self.config.jump_delta,
                "debounce": self.config.debounce,
                "sound": self.config.sound,
            },
            "active": [a.to_dict(now=now) for a in self.active.values()],
            "new_since_poll": self.new_since_poll,
            "history_total": len(self.history),
        }

    def ack(self, alarm_id: int) -> bool:
        for alarm in self.active.values():
            if alarm.id == alarm_id:
                alarm.acked = True
                return True
        for alarm in reversed(self.history):
            if alarm.id == alarm_id:
                alarm.acked = True
                return True
        return False

    def history_list(self, limit: int = 100) -> dict:
        rows = [a.to_dict() for a in reversed(self.history[-max(1, min(limit, _MAX_HISTORY)):])]
        return {"ok": True, "history": rows, "total": len(self.history)}

    def history_records(self, limit: int = 100) -> list[dict]:
        """供测试报告附「告警历史」段（旧→新）."""
        return [
            {"ts": a.ts, "kind": a.kind, "ioa": a.ioa,
             "message": a.message, "acked": a.acked,
             "cleared": a.cleared_ts is not None}
            for a in self.history[-max(1, min(limit, _MAX_HISTORY)):]
        ]

    def configure(self, **kwargs: float | bool) -> None:
        if "stale_seconds" in kwargs and kwargs["stale_seconds"] is not None:
            self.config.stale_seconds = max(5.0, min(float(kwargs["stale_seconds"]), 86400.0))
        if "comm_seconds" in kwargs and kwargs["comm_seconds"] is not None:
            self.config.comm_seconds = max(3.0, min(float(kwargs["comm_seconds"]), 3600.0))
        if "jump_delta" in kwargs:
            jd = kwargs["jump_delta"]
            # None/0/负值 → 关闭（正值才启用，钳到正数）
            self.config.jump_delta = None if jd is None or float(jd) <= 0 else float(jd)
        if "debounce" in kwargs and kwargs["debounce"] is not None:
            self.config.debounce = max(1, min(int(kwargs["debounce"]), 10))  # type: ignore[arg-type]
        if "sound" in kwargs and kwargs["sound"] is not None:
            self.config.sound = bool(kwargs["sound"])

    async def loop(self, interval: float = 1.0) -> None:
        """周期评估（create_app on_startup 中由桥拉起；评估异常绝不影响引擎）."""
        import asyncio

        while True:
            try:
                self.evaluate()
            except Exception:  # noqa: BLE001 — 告警评估异常绝不影响引擎
                pass
            await asyncio.sleep(interval)
