"""对点 / 传动验收编排服务（WP2）.

把「勾选点 → 批量顺序下发 → 等回读/变位 → 自动判定 → 留存证据」串成一条
可中断的后台任务。设计约束：

* **同一时刻只允许 1 个活动会话**：避免与手动命令、周期总召抢 I 帧序号；
* 执行期间暂停周期 GI（``gi_interval`` 任务 + scheduler 模板任务），退出恢复；
* 变位等待用 ``data_store.subscribe`` 回调投递 ``asyncio.Future``，回调里
  **绝不 await**（它运行在引擎事件循环内）；
* 每步通过现有 ``event`` kind 广播 ``commission.*`` 进度，前端复用
  ``useLiveEvents()`` 即可，无需新增 WS kind；
* 帧证据从 ``bus.recent("frame")`` 取该步骤窗口内的帧 hex，不额外挂回调；
* ``stop`` 时对已选择未执行的 SBO 发 DEACT 清理，不留悬空选择。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from core.data.commission_store import CommissionStore
from core.data.commissioning import (
    CommissionItem,
    CommissionSession,
    ItemKind,
    SessionStatus,
    Verdict,
    build_items_from_points,
    judge,
)

logger = logging.getLogger("iec104.commission")

DEFAULT_STEP_TIMEOUT = 5.0


class CommissioningService:
    """验收会话编排器（挂到 EngineBridge 上，由 Web API 驱动）."""

    def __init__(self, bridge, store: CommissionStore,
                 step_timeout: float = DEFAULT_STEP_TIMEOUT):
        self._bridge = bridge
        self._store = store
        self._step_timeout = step_timeout
        self._active: CommissionSession | None = None
        self._task: asyncio.Task | None = None
        self._stop_requested = False
        self._waiters: dict[int, list[asyncio.Future]] = {}
        self._subscribed_engine: Any = None
        self._paused_gi = False

    # ── 公开 API（同步部分；handler 内用 to_thread 包 DB 操作） ─────

    def list_sessions(self, limit: int = 100) -> list[dict]:
        return self._store.list_sessions(limit)

    def get_session(self, session_id: str) -> dict | None:
        s = self._store.load(session_id)
        return s.to_dict() if s else None

    def create_session(self, name: str = "", operator: str = "",
                       ioas: list[int] | None = None,
                       expected: dict[int, Any] | None = None,
                       command_ioas: dict[int, int] | None = None) -> dict:
        """从当前点表快照创建会话。

        ``ioas`` 为空表示全选；``expected`` 为 ``{ioa: 期望值}``，缺省的点
        保留 PENDING 交人工复核；``command_ioas`` 为 ``{回读 IOA: 下发 IOA}``，
        用于遥控与其回读遥信地址不同的现场装置。
        """
        if self.status()["running"]:
            raise RuntimeError("已有正在运行的验收会话，请先停止")
        pts = self._bridge.snapshot_points()
        if ioas:
            wanted = set(int(i) for i in ioas)
            pts = [p for p in pts if int(p["ioa"]) in wanted]
        items = build_items_from_points(pts, command_ioas)
        for it in items:
            if expected and it.ioa in expected:
                it.expected = expected[it.ioa]
        s = CommissionSession(
            id=CommissionStore.new_id(),
            name=name or f"对点验收 {time.strftime('%Y-%m-%d %H:%M')}",
            operator=operator,
            items=items,
            point_table_snapshot=[
                {"ioa": p["ioa"], "type": p["type"], "name": p.get("name", ""),
                 "group": p.get("group", 1), "enabled": p.get("enabled", True)}
                for p in pts
            ],
        )
        self._store.save(s)
        return s.to_dict()

    def delete_session(self, session_id: str) -> bool:
        if self._active and self._active.id == session_id and self.status()["running"]:
            raise RuntimeError("不能删除正在运行的会话")
        return self._store.delete(session_id)

    def set_verdict(self, session_id: str, ioa: int, verdict: str,
                    note: str = "", operator: str = "") -> dict | None:
        return self._store.set_verdict(session_id, ioa, verdict, note, operator)

    def status(self) -> dict:
        # running 由后台任务是否结束决定：session.status 在 try 末尾就会写
        # DONE/STOPPED，但 finally 里的 DEACT 清理尚未完成，此时若按
        # session.status 判断会让前端误以为收尾已结束。
        running = self._task is not None and not self._task.done()
        return {
            "ok": True,
            "running": running,
            "session_id": self._active.id if self._active else None,
            "cursor": self._active.cursor if self._active else 0,
            "total": len(self._active.items) if self._active else 0,
        }

    # ── 运行 / 停止 ───────────────────────────────────────────────

    def run(self, session_id: str, operator: str = "") -> dict:
        """启动后台批量传动（幂等保护）。"""
        if self._task is not None and not self._task.done():
            raise RuntimeError("已有正在运行的验收会话")
        s = self._store.load(session_id)
        if s is None:
            raise KeyError(f"session not found: {session_id}")
        if s.status == SessionStatus.DONE:
            raise RuntimeError("该会话已完成；请新建会话重跑")
        eng = self._require_master()
        s.status = SessionStatus.RUNNING
        s.started_at = time.time()
        s.operator = operator or s.operator
        s.finished_at = 0.0
        self._store.save(s)
        self._active = s
        self._stop_requested = False
        self._paused_gi = self._pause_periodic_gi(eng)
        self._subscribe(eng)
        self._task = asyncio.create_task(self._run_loop(s), name="commission-run")
        self._emit("commission.started", {"id": s.id, "total": len(s.items)})
        return {"ok": True, **self.status()}

    def stop(self) -> dict:
        """请求中止；实际清理在后台任务退出时完成。"""
        if self._task is None or self._task.done():
            return {"ok": True, **self.status()}
        self._stop_requested = True
        for waiters in self._waiters.values():
            for fut in waiters:
                if not fut.done():
                    fut.cancel()
        self._emit("commission.stopping", {"id": self._active.id if self._active else None})
        return {"ok": True, **self.status()}

    async def _run_loop(self, s: CommissionSession) -> None:
        eng = self._require_master()
        try:
            for idx in range(s.cursor, len(s.items)):
                if self._stop_requested:
                    break
                item = s.items[idx]
                s.cursor = idx
                self._store.save(s)
                await self._run_item(eng, s, item)
                self._store.save(s)
                self._emit("commission.item", {
                    "id": s.id, "index": idx, "total": len(s.items),
                    "item": item.to_dict(),
                })
            s.cursor = len(s.items) if not self._stop_requested else s.cursor
            s.status = SessionStatus.STOPPED if self._stop_requested else SessionStatus.DONE
        except Exception as exc:  # noqa: BLE001 — 后台任务必须吞异常并留痕
            logger.exception("commission run failed: %s", exc)
            s.note = f"编排异常: {exc}"
            s.status = SessionStatus.STOPPED
        finally:
            await self._cleanup_sbo(eng, s)
            self._unsubscribe(eng)
            self._resume_periodic_gi(eng)
            # 状态/落盘放到清理之后：running 在 DEACT 等收尾动作完成前
            # 必须保持，否则前端会误判会话已结束而漏掉最后的清理帧。
            s.finished_at = time.time()
            self._store.save(s)
            self._emit("commission.finished", {
                "id": s.id, "status": s.status.value, "summary": s.summary(),
            })

    # ── 单点执行 ──────────────────────────────────────────────────

    async def _run_item(self, eng, s: CommissionSession, item: CommissionItem) -> None:
        """下发 → 等回读/变位 → 判定 → 填证据帧。"""
        if item.expected is None:
            item.verdict = Verdict.MANUAL
            item.reason = "未设期望值，跳过自动下发"
            item.checked_at = time.time()
            return

        frame_before = len(self._bridge.recent("frame", 2000))
        tx_time = time.time()
        item.tx_time = tx_time
        reason = ""
        try:
            await self._send(eng, item, operator=s.operator)
        except Exception as exc:  # noqa: BLE001 — 命令失败也是可判定结论
            reason = f"命令下发失败: {exc}"

        observed: Any = None
        quality = ""
        if not reason:
            try:
                observed, quality = await self._await_observed(eng, item)
            except asyncio.TimeoutError:
                reason = "等待回读/变位超时"
            except asyncio.CancelledError:
                reason = "会话中止" if self._stop_requested else "等待被取消"
            except Exception as exc:  # noqa: BLE001
                reason = f"等待观测失败: {exc}"

        item.rx_time = time.time()
        judge(item, observed=observed, quality=quality,
              rx_time=item.rx_time, reason=reason)
        item.checked_at = time.time()
        item.operator = s.operator
        self._fill_frame_evidence(item, frame_before)

    async def _send(self, eng, item: CommissionItem, operator: str = "") -> None:
        """按点类型下发；YK/YX 走遥控，YC 走设点，STEP 走升降。

        统一走 ``EngineBridge`` 的门面方法（与 UI 手动下发同一路径），
        保证 SBO 两段式、DEACT 等既有语义不变。
        编排不是 HTTP 请求，无请求级身份上下文——这里显式设置审计身份
        （WP4a：每条传动记录复用同一条审计链，operator 取会话检查人）。
        """
        from .audit import AuditIntent, Identity, set_audit_intent, set_operator_context

        b = self._bridge
        ioa = item.target_ioa
        operator = operator or "commission"
        set_operator_context(Identity(name=operator, role="system", source_ip=""))
        set_audit_intent(AuditIntent(action=f"commission/{item.kind.value.lower()}",
                                     target=str(ioa)))
        try:
            if item.kind in (ItemKind.YK, ItemKind.YX):
                # YX 对点用配对遥控点驱动变位。本仓演示点表 YK/YX 同 IOA；
                # 现场不同地址时用 command_ioas 显式指定，避免误打到无关对象。
                await b.send_yk(ioa, int(bool(item.expected)))
            elif item.kind == ItemKind.YC:
                await b.send_setpoint(ioa, float(item.expected))
                # 设点后再发读命令，主动取回当前值（部分装置不主动回读）
                await b.read_command(ioa)
            elif item.kind == ItemKind.STEP:
                await b.send_step_command(ioa, 2 if int(item.expected) >= 0 else 1)
        finally:
            set_audit_intent(None)
            set_operator_context(None)

    async def _await_observed(self, eng, item: CommissionItem) -> tuple[Any, str]:
        """等待目标 IOA 的值变化，返回 (值, 品质字符串)。

        * YK 点：等待命令确认 ACTCON（``data_store.get_yk().last_command``
          变为 ``"ack"``/``"nack"``）。``DataChangeEvent`` 不含 yk，
          用轮询而非订阅；NACK 直接给 fail 原因。
        * YX/YC/STEP：订阅 ``data_store`` 变位事件，回调只 resolve 一个
          Future（回调运行在引擎循环内，绝不 await）；0.1s 轮询兜底防竞态。
        """
        if item.kind == ItemKind.YK:
            return await self._await_command_ack(eng, item)

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        cb = self._make_callback(item, fut, loop)
        store = eng.data_store
        store.subscribe(cb)
        self._waiters.setdefault(item.ioa, []).append(fut)
        try:
            # 先查一次：值可能已经在等待开始前就更新了
            hit = self._read_value(store, item)
            if hit is not None and self._value_matches(item, hit[0]):
                return hit
            deadline = loop.time() + self._step_timeout
            while not fut.done():
                if self._stop_requested:
                    raise asyncio.CancelledError()
                timeout = deadline - loop.time()
                if timeout <= 0:
                    raise asyncio.TimeoutError()
                try:
                    await asyncio.wait_for(asyncio.shield(fut), timeout=min(0.1, timeout))
                except asyncio.TimeoutError:
                    hit = self._read_value(store, item)
                    if hit is not None and self._value_matches(item, hit[0]):
                        return hit
                    continue
            return fut.result()
        finally:
            store.unsubscribe(cb)
            waiters = self._waiters.get(item.ioa, [])
            if fut in waiters:
                waiters.remove(fut)

    async def _await_command_ack(self, eng, item: CommissionItem) -> tuple[Any, str]:
        """YK 点：轮询命令确认；返回 (True/False, "") 或抛含原因的异常。"""
        store = eng.data_store
        deadline = asyncio.get_running_loop().time() + self._step_timeout
        while True:
            if self._stop_requested:
                raise asyncio.CancelledError()
            d = store.get_yk(item.target_ioa)
            if d is not None and d.last_command in ("ack", "nack"):
                if d.last_command == "nack":
                    raise RuntimeError("SBO 被拒 / 命令否定确认 (P/N=1)")
                return True, ""
            if asyncio.get_running_loop().time() >= deadline:
                raise asyncio.TimeoutError()
            await asyncio.sleep(0.05)

    def _make_callback(self, item: CommissionItem, fut: asyncio.Future,
                       loop: asyncio.AbstractEventLoop) -> Callable:
        def cb(event) -> None:
            if fut.done() or event.ioa != item.ioa:
                return
            try:
                val = event.new_value
                quality = str(getattr(event, "quality", "") or "")
                if self._value_matches(item, val):
                    loop.call_soon_threadsafe(self._resolve, fut, (val, quality))
            except Exception:  # noqa: BLE001 — 回调异常不得影响引擎
                logger.exception("commission change callback failed")
        return cb

    @staticmethod
    def _resolve(fut: asyncio.Future, value) -> None:
        if not fut.done():
            fut.set_result(value)

    @staticmethod
    def _value_matches(item: CommissionItem, value: Any) -> bool:
        if value is None:
            return False
        if item.kind == ItemKind.YC:
            try:
                return abs(float(value) - float(item.expected)) <= float(item.tolerance or 0.0)
            except (TypeError, ValueError):
                return False
        if isinstance(item.expected, bool):
            return bool(value) is item.expected
        try:
            return float(value) == float(item.expected)
        except (TypeError, ValueError):
            return value == item.expected

    @staticmethod
    def _read_value(store, item: CommissionItem) -> tuple[Any, str] | None:
        """从实时库读当前值 + 品质；YX 返回 bool，YC/STEP 返回数值。"""
        try:
            if item.kind == ItemKind.YX:
                d = store.get_yx(item.ioa)
                return (d.value, str(d.quality)) if d else None
            if item.kind == ItemKind.YC:
                d = store.get_yc(item.ioa)
                return (float(d.value), str(d.quality)) if d else None
            if item.kind == ItemKind.STEP:
                d = store.get_step(item.ioa)
                return (int(d.value), str(d.quality)) if d else None
            # YK 由 _await_command_ack 单独处理；保留分支供初始快查
            d = store.get_yk(item.target_ioa)
            if d is not None and d.last_command == "ack":
                return True, ""
            return None
        except Exception:  # noqa: BLE001 — 单个点读取异常按未观测处理
            return None

    def _fill_frame_evidence(self, item: CommissionItem, frame_before: int) -> None:
        """取本步骤窗口内的帧作为证据（下发帧 + 回读/变位帧）。

        ``EventBus.recent`` 返回的是 ``{kind, ts, data}`` 信封，帧字段在
        ``data`` 内；用 ``frame_before``（步骤开始时的缓冲长度）切窗口，
        并额外按 ``ts`` 过滤，兼容环形缓冲被截断的情况。
        """
        raw = self._bridge.recent("frame", 2000)
        window = raw[frame_before:] if frame_before < len(raw) else raw
        frames = []
        for msg in window:
            d = msg.get("data", msg) if isinstance(msg, dict) else {}
            ts = msg.get("ts", 0) if isinstance(msg, dict) else 0
            if ts and ts < item.tx_time - 0.001:
                continue
            frames.append(d)
        tx = [d for d in frames if d.get("direction") == "tx"]
        rx = [d for d in frames if d.get("direction") == "rx"]
        if tx:
            item.tx_frame = str(tx[0].get("hex", ""))[:512]
        if rx:
            item.rx_frame = str(rx[-1].get("hex", ""))[:512]

    # ── 周期任务 / SBO 清理 / 订阅 ────────────────────────────────

    def _require_master(self):
        eng = self._bridge.engine
        if eng is None:
            raise RuntimeError("主站未连接")
        return eng

    def _pause_periodic_gi(self, eng) -> bool:
        """暂停周期总召，避免与批量传动抢 I 帧序号；返回是否真的暂停了。"""
        paused = False
        try:
            task = getattr(eng, "_periodic_gi_task", None)
            if task is not None and not task.done():
                task.cancel()
                paused = True
        except Exception:  # noqa: BLE001
            pass
        try:
            sched = getattr(eng, "scheduler", None)
            if sched is not None:
                for t in sched.get_all_tasks():
                    if getattr(t, "name", "") == "periodic_gi" and getattr(t, "enabled", False):
                        sched.disable_task("periodic_gi")
                        paused = True
        except Exception:  # noqa: BLE001
            pass
        return paused

    def _resume_periodic_gi(self, eng) -> None:
        if not self._paused_gi:
            return
        try:
            sched = getattr(eng, "scheduler", None)
            if sched is not None:
                sched.enable_task("periodic_gi")
        except Exception:  # noqa: BLE001
            pass
        # 独立 gi_interval 任务的重建需要原始 interval，交由下次 start 恢复；
        # 这里显式记日志，避免静默丢配置。
        logger.info("commission finished; periodic GI task needs restart on next connect")

    def _subscribe(self, eng) -> None:
        self._subscribed_engine = eng

    def _unsubscribe(self, eng) -> None:
        self._subscribed_engine = None

    async def _cleanup_sbo(self, eng, s: CommissionSession) -> None:
        """中止时对所有已下发但未确认的 YK 点发 DEACT，清掉悬空选择。"""
        if not self._stop_requested:
            return
        for item in s.items:
            # 判定依据是「已下发过命令」而非 verdict：中止时当前点已被
            # judge 写成 FAIL（reason=会话中止），用 verdict 判断会漏清理。
            if item.kind != ItemKind.YK or item.tx_time <= 0:
                continue
            try:
                await self._bridge.send_yk(item.target_ioa, 0, deactivate=True)
            except Exception as exc:  # noqa: BLE001 — 清理失败不影响收尾
                logger.warning("DEACT cleanup failed for ioa=%s: %s", item.ioa, exc)

    # ── 进度广播（复用 event kind，前端零改动） ───────────────────

    def _emit(self, type_: str, data: dict) -> None:
        try:
            self._bridge.publish("event", {"type": type_, "data": data})
        except Exception:  # noqa: BLE001 — 广播失败不得中断编排
            logger.exception("commission event publish failed")

    # ── 关停 ──────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        self._stop_requested = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._store.close()
