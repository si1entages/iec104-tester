"""主站冗余双通道（T21）— 主备切换 / 链路重建 / 切换窗口去重.

模型（详见 ``docs/redundancy.md``）：

- 主/备两条**独立** ``TCPClient`` 分别指向主用/备用前置机；**同一时刻仅一条
  处于活动态**收发 I 帧，活动态客户端即 ``engine._client``。
- 备用通道保持 TCP 连接 + STARTDT 预连接（链路就绪、随时可接管）；其收到的
  帧**不进引擎协议栈**，仅记录去重键（静默吸收）。
- 活动通道 TCP 断开（含 TESTFR/t1 超时经既有 ``disconnect()`` 路径表现出的
  断链）→ 立即切换到备用通道：``engine._client`` 换为备用、重走既有
  ``on_tcp_connected`` 路径；STARTDT CON 使 VS/VR 归零（``SequenceManager
  .process_rx_u_frame_startdt_con`` 既有行为），进入 Running 后自动补一轮
  总召唤 —— 与首连建立链路的过程完全同构。
- 切换窗口去重：键 = **ASDU 字节摘要**（跳过 6 字节 APCI —— 主备链路各自
  维护发送序号，同一数据在两条链路上的 APCI 序号不同，ASDU 才是稳定键）；
  仅对 I 帧生效，窗口 ``dedup_window`` 秒内字节完全相同的 ASDU 只处理一次。

未覆盖（诚实声明，**请勿宣传为"支持完整冗余标准"**）：双通道同时活跃的
热备、IEC 60870-5-10 冗余组管理/选址、备用通道应用层健康度主动探测
（仅依赖 TCP+STARTDT 预连接成功）、备用通道 TESTFR 保活（前置机空闲
超时断开备用时由重连循环自动恢复预连接）。

设计：**组合 + 构造期注入**（沿用 ``master_param_state`` 的拆分手法）——
引擎引用由构造期传入，本模块按需读写引擎状态并直改 ``engine._client`` 活动态；
``MasterEngine`` 只保留薄接入（构造参数 + start/stop 各一处分支）。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import TYPE_CHECKING

from ..protocol.apci import APCICodec
from ..transport.connection import TCPClient

if TYPE_CHECKING:
    from ..config import RedundancyConfig
    from .master import MasterEngine

logger = logging.getLogger("iec104.master.redundancy")


class _DedupWindow:
    """切换窗口去重（键 = ASDU 字节摘要）.

    ⚠ 去重**只发生在应用层分发前**（``MasterSession.handle_i_frame`` 经
    ``is_duplicate_asdu`` 门控）：I 帧的序列号消费与确认**永远照常进行**，
    传输层绝不能丢 I 帧——丢帧会让 VR 失步、触发断链重建，反而放大故障。
    """

    def __init__(self, window: float) -> None:
        self._window = max(0.0, float(window))
        self._seen: dict[bytes, float] = {}

    @staticmethod
    def _key_of(frame: bytes) -> bytes | None:
        """从原始帧提取去重键（ASDU 字节摘要）；非 I 帧返回 None.

        I 帧判定看控制域 1（``frame[2]``，前两字节为起始 0x68 与长度）：
        bit0=0 即 I 格式（S/U 格式 bit0=1）。键取 ASDU 部分（跳过 6 字节
        APCI）：主备链路各自维护发送序号，同一数据在两条链路上的 APCI
        序号不同，ASDU 字节才是稳定键。
        """
        if len(frame) < 12 or frame[2] & 0x01 != 0:
            return None
        return hashlib.sha1(frame[6:]).digest()[:12]

    def observe(self, key: bytes) -> bool:
        """记录键并返回是否为窗口内重复."""
        if self._window <= 0:
            return False
        now = time.monotonic()
        if self._seen:
            expired = [k for k, t in self._seen.items() if now - t > self._window]
            for k in expired:
                del self._seen[k]
        last = self._seen.get(key)
        self._seen[key] = now
        return last is not None


class MasterRedundancy:
    """主站冗余双通道管理器（由 ``MasterEngine`` 组合持有）.

    Args:
        engine: 主站引擎实例（组合子模块按需读写其状态）。
        cfg: ``RedundancyConfig``。
        host/port/reconnect_interval/max_reconnects: 主用通道 TCPClient 参数
            （与未启用冗余时的单通道构造完全一致，由引擎透传）。
        on_frame/on_connected/on_disconnected: 引擎侧回调（活动态时才被路由）。

    Raises:
        ValueError: ``standby_host`` 未配置 / ``standby_port`` 非法 /
            备用地址与主用完全相同。
    """

    def __init__(self, engine: MasterEngine, cfg: RedundancyConfig, *,
                 host: str, port: int, reconnect_interval: float,
                 max_reconnects: int,
                 on_frame, on_connected, on_disconnected,
                 ssl_context=None, server_hostname: str | None = None) -> None:
        if not cfg.standby_host:
            raise ValueError("RedundancyConfig.standby_host 未配置（启用冗余时必填）")
        if not 0 < int(cfg.standby_port) <= 65535:
            raise ValueError(f"RedundancyConfig.standby_port 非法: {cfg.standby_port!r}")
        if cfg.standby_host == host and int(cfg.standby_port) == int(port):
            raise ValueError("备用通道地址不能与主用完全相同（无冗余意义）")

        self._engine = engine
        self._cfg = cfg
        self._dedup = _DedupWindow(cfg.dedup_window)
        self._active: TCPClient | None = None
        self._switch_t0: float | None = None
        self._rebuild_task: asyncio.Task | None = None
        self._failover_count = 0

        self._primary = TCPClient(
            host=host, port=port,
            reconnect_interval=reconnect_interval,
            max_reconnects=max_reconnects,
            on_frame=lambda f: self._route_frame(self._primary, f),
            on_connected=lambda: self._on_channel_connected(self._primary),
            on_disconnected=lambda: self._on_channel_disconnected(self._primary),
            ssl_context=ssl_context,
            server_hostname=server_hostname,
        )
        # 备用通道始终自动重连（max_reconnects=0），保证预连接可持续恢复
        self._standby = TCPClient(
            host=cfg.standby_host, port=cfg.standby_port,
            reconnect_interval=reconnect_interval, max_reconnects=0,
            on_frame=lambda f: self._route_frame(self._standby, f),
            on_connected=lambda: self._on_channel_connected(self._standby),
            on_disconnected=lambda: self._on_channel_disconnected(self._standby),
        )
        # 引擎侧原始回调：活动态路由时使用（on_frame 转发，连接事件直通）
        self._engine_on_frame = on_frame
        self._engine_on_connected = on_connected
        self._engine_on_disconnected = on_disconnected

    # ── 属性 ─────────────────────────────────────────────────────

    @property
    def primary(self) -> TCPClient:
        return self._primary

    @property
    def standby(self) -> TCPClient:
        return self._standby

    @property
    def active(self) -> TCPClient | None:
        """当前活动通道（``start()`` 前为 ``None``）."""
        return self._active

    def status(self) -> dict:
        """冗余运行态快照（Web 状态页展示；只读，不改变切换状态）."""
        if self._active is self._primary:
            active = "primary"
        elif self._active is self._standby:
            active = "standby"
        else:
            active = None
        return {
            "enabled": True,
            "active": active,
            "primary_connected": self._primary.is_connected,
            "standby_connected": self._standby.is_connected,
            "standby_host": self._cfg.standby_host,
            "standby_port": int(self._cfg.standby_port),
            "switch_timeout": float(self._cfg.switch_timeout),
            "dedup_window": float(self._cfg.dedup_window),
            "failovers": self._failover_count,
        }

    # ── 生命周期 ─────────────────────────────────────────────────

    async def start(self) -> None:
        """启动主/备两条通道（备用同步开始预连接）."""
        self._active = self._primary
        await self._primary.start()
        await self._standby.start()

    async def stop(self) -> None:
        """停止两条通道并取消切换重建任务（幂等、尽力而为）."""
        if self._rebuild_task is not None:
            self._rebuild_task.cancel()
            try:
                await self._rebuild_task
            except (asyncio.CancelledError, Exception):
                pass
            self._rebuild_task = None
        for client in (self._primary, self._standby):
            try:
                await client.stop()
            except Exception as exc:
                logger.warning("冗余通道停止失败: %s", exc)

    # ── 帧路由与去重 ─────────────────────────────────────────────

    def _route_frame(self, channel: TCPClient, frame: bytes) -> None:
        if channel is not self._active:
            # 非活动通道：静默吸收，仅学习去重键（切换窗口对齐两侧已见数据）；
            # 通道自身的 TCP/状态由其重连循环自持
            key = self._dedup._key_of(frame)
            if key is not None:
                self._dedup.observe(key)
            return
        # 活动通道：**始终转发**（序列号消费与确认在引擎内照常进行）；
        # 应用层去重在 MasterSession.handle_i_frame 经 is_duplicate_asdu 门控
        self._engine_on_frame(frame)

    def is_duplicate_asdu(self, asdu_data: bytes) -> bool:
        """应用层去重门控（由 ``MasterSession.handle_i_frame`` 调用）.

        调用前提：该 I 帧已完成序列号消费与确认。返回 True 时调用方跳过
        ASDU 解码分发（不重复入库/上事件），帧本身视为已正常处理。
        """
        if not asdu_data:
            return False
        key = hashlib.sha1(asdu_data).digest()[:12]
        return self._dedup.observe(key)

    # ── 通道事件 ─────────────────────────────────────────────────

    def _on_channel_connected(self, channel: TCPClient) -> None:
        if channel is self._active:
            # 活动通道（含切换后备用通道的重连）→ 引擎既有连接路径
            self._engine_on_connected()
        else:
            logger.info("备用通道就绪（TCP 已建立，STARTDT 预连接）")
            self._engine._spawn(self._standby_startdt())

    def _on_channel_disconnected(self, channel: TCPClient) -> None:
        if channel is not self._active:
            logger.warning("非活动通道断开，重连循环将自动恢复预连接")
            return
        self._failover(channel)

    def _failover(self, dead: TCPClient) -> None:
        """活动通道故障 → 切换到另一条通道并触发链路重建."""
        other = self._standby if dead is self._primary else self._primary
        logger.warning("活动通道断开，切换到%s通道",
                       "备用" if other is self._standby else "原主用")
        self._failover_count += 1
        self._switch_t0 = time.monotonic()
        # 引擎先感知断开（状态机离开 Running / DISCONNECTED 事件），再换活动客户端
        self._engine_on_disconnected()
        self._active = other
        self._engine._client = other
        if other.is_connected:
            self._engine_on_connected()   # 重走既有路径：STARTDT（CON 后 VS/VR 归零）
        if not self._engine._auto_start:
            # 未配置自动 STARTDT 时由切换流程显式补发（链路重建的前提）
            self._engine._spawn(self._manual_startdt())
        self._rebuild_task = self._engine._spawn(self._rebuild_link())

    # ── 切换后链路重建 ───────────────────────────────────────────

    async def _rebuild_link(self) -> None:
        """等待新链路进入 Running（STARTDT CON → VS/VR 归零）后补发总召唤."""
        ready = self._active is not None and self._active.is_connected
        timeout = self._cfg.switch_timeout if ready else max(
            self._cfg.switch_timeout * 3, 15.0)
        try:
            await asyncio.wait_for(self._wait_running(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(
                "冗余切换后 %.1fs 未进入 Running（STARTDT 无 CON）；"
                "恢复后不再自动总召唤，可手动召唤", timeout)
            return
        try:
            await self._engine.general_interrogation()
        except Exception as exc:
            logger.warning("切换后总召唤失败: %s", exc)
            return
        if self._switch_t0 is not None:
            logger.info("冗余切换完成：%.3fs（断开 → Running → 总召唤下发）",
                        time.monotonic() - self._switch_t0)
            self._switch_t0 = None

    async def _wait_running(self) -> None:
        while not self._engine.is_running:
            await asyncio.sleep(0.02)

    # ── 备用通道预连接握手 ───────────────────────────────────────

    async def _standby_startdt(self) -> None:
        """备用通道 STARTDT 预连接（U 帧，不涉 VS/VR；失败由重连后重试）."""
        try:
            await asyncio.sleep(0.2)
            await self._standby.send(APCICodec.startdt_act())
        except Exception as exc:
            logger.debug("备用通道 STARTDT 发送失败（重连后重试）: %s", exc)

    async def _manual_startdt(self) -> None:
        try:
            await self._engine.send_startdt()
        except Exception as exc:
            logger.warning("切换后显式 STARTDT 失败: %s", exc)
