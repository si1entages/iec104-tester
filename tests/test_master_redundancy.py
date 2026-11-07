"""主站冗余双通道测试（T21）.

覆盖:
- 去重窗口（单元）：同 ASDU 不同 APCI 序号 → 重复；不同 ASDU → 放行；
  非 I 帧 → 不去重；窗口过期 → 放行
- 切换 E2E：主用前置机断开 → 备用接管 → STARTDT 重建（VS/VR 归零）→
  总召唤重建 → 数据继续；耗时 < 阈值（3.0s，含 STARTDT+GI，见用例内注释）
- 去重生效（单元级路由）：备用通道先见 ASDU，切换窗口内活动通道同 ASDU 被丢弃
- 配置无效失败路径：standby_host 为空 / 端口非法 / 备用地址与主用相同
- 未启用冗余 → 行为与单通道完全一致
"""

from __future__ import annotations

import asyncio
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.protocol.apci import APCICodec

# ---- 测试用最小 ASDU（M_SP_NA_1 单点遥信，1 个信息对象）----------------
# COT=3(突发) + 公共地址 1 + IOA 1 + 值/品质
_ASDU = bytes([
    0x01, 0x01, 0x03, 0x00, 0x01, 0x00,          # ASDU 头: type=1, n=1, cot=3, ca=1
    0x01, 0x00, 0x00, 0x01, 0x00,                # IOA=1, 值=1/品质=0
])
_ASDU_OTHER = bytes([
    0x01, 0x01, 0x03, 0x00, 0x01, 0x00,
    0x02, 0x00, 0x00, 0x01, 0x00,                # IOA=2
])


def _i_frame(tx_seq: int, rx_seq: int, asdu: bytes = _ASDU) -> bytes:
    return APCICodec.encode_i(tx_seq, rx_seq, asdu)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_until(predicate, timeout: float = 8.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def _demo_points():
    from core.data.point_table import PointTable
    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=2, yk_count=0, ym_count=0)
    pt.common_addr = 1
    pt.station_name = "T21"
    return pt


# ── 去重窗口（单元）──────────────────────────────────────────────

class TestDedupWindow:
    def test_key_is_asdu_part_ignoring_apci(self):
        """去重键取 ASDU：同一 ASDU、不同发送序号（两条链路各自的 VS）→ 同键."""
        from core.engine.master_redundancy import _DedupWindow

        k0 = _DedupWindow._key_of(_i_frame(0, 0))
        k1 = _DedupWindow._key_of(_i_frame(1, 0))
        k7 = _DedupWindow._key_of(_i_frame(7, 3))
        assert k0 is not None and k0 == k1 == k7
        assert _DedupWindow._key_of(_i_frame(0, 0, _ASDU_OTHER)) != k0

    def test_non_i_frame_has_no_key(self):
        from core.engine.master_redundancy import _DedupWindow

        assert _DedupWindow._key_of(APCICodec.startdt_act()) is None
        assert _DedupWindow._key_of(APCICodec.encode_s(1)) is None
        assert _DedupWindow._key_of(b"") is None

    def test_observe_detects_duplicate_and_expires(self):
        from core.engine.master_redundancy import _DedupWindow

        w = _DedupWindow(5.0)
        key = _DedupWindow._key_of(_i_frame(0, 0))
        assert w.observe(key) is False   # 首发
        assert w.observe(key) is True    # 窗口内重复
        w2 = _DedupWindow(0.05)
        k2 = _DedupWindow._key_of(_i_frame(0, 0))
        assert w2.observe(k2) is False
        time.sleep(0.08)
        assert w2.observe(k2) is False   # 窗口已过

    def test_zero_window_disables_dedup(self):
        from core.engine.master_redundancy import _DedupWindow

        w = _DedupWindow(0.0)
        key = _DedupWindow._key_of(_i_frame(0, 0))
        assert w.observe(key) is False
        assert w.observe(key) is False


# ── 路由与去重（管理器单元）──────────────────────────────────────

class _FakeEngine:
    def __init__(self):
        self.frames: list[bytes] = []
        self.connected_calls = 0
        self.disconnected_calls = 0
        self._auto_start = True
        self._host, self._port = "127.0.0.1", 2404
        self.is_running = False
        self._client = None
        self.spawned: list = []

    def _on_frame_received(self, frame):
        self.frames.append(frame)

    def _on_tcp_connected(self):
        self.connected_calls += 1

    def _on_tcp_disconnected(self):
        self.disconnected_calls += 1

    def _spawn(self, coro):
        self.spawned.append(coro)
        coro.close()   # 单测路由不真正执行切换协程，避免未 await 告警
        return None


class TestRedundancyRouting:
    def _manager(self):
        from core.config import RedundancyConfig
        from core.engine.master_redundancy import MasterRedundancy

        eng = _FakeEngine()
        mgr = MasterRedundancy(
            eng, RedundancyConfig(enabled=True, standby_host="127.0.0.1",
                                  standby_port=2405),
            host="127.0.0.1", port=2404, reconnect_interval=5.0,
            max_reconnects=0,
            on_frame=eng._on_frame_received,
            on_connected=eng._on_tcp_connected,
            on_disconnected=eng._on_tcp_disconnected,
        )
        mgr._active = mgr._primary   # 不经 start() 直接置活动态（单测路由）
        return eng, mgr

    def test_active_channel_always_forwards_to_engine(self):
        """活动通道**始终转发**（序列号消费照常）——传输层绝不丢 I 帧."""
        eng, mgr = self._manager()
        f0, f1 = _i_frame(0, 0), _i_frame(1, 0)   # 同 ASDU 不同序号
        mgr._route_frame(mgr._primary, f0)
        mgr._route_frame(mgr._primary, f1)
        assert eng.frames == [f0, f1]

    def test_standby_frame_absorbed_and_learned(self):
        eng, mgr = self._manager()
        mgr._route_frame(mgr._standby, _i_frame(5, 5))
        assert eng.frames == []      # 备用静默吸收，不进引擎
        # 但去重键已学习：应用层门控会把同 ASDU 判为重复
        assert mgr.is_duplicate_asdu(_ASDU) is True

    def test_status_snapshot_for_web(self):
        """E3：Web 状态页读取的冗余快照（活动通道/连接态/切换次数）."""
        _, mgr = self._manager()
        st = mgr.status()
        assert st["enabled"] is True
        assert st["active"] == "primary"
        assert st["standby_host"] == "127.0.0.1"
        assert st["standby_port"] == 2405
        assert st["primary_connected"] is False
        assert st["standby_connected"] is False
        assert st["failovers"] == 0

        mgr._active = mgr._standby
        mgr._failover_count = 2
        st = mgr.status()
        assert st["active"] == "standby"
        assert st["failovers"] == 2

    def test_is_duplicate_asdu_semantics(self):
        eng, mgr = self._manager()
        assert mgr.is_duplicate_asdu(_ASDU) is False        # 首发
        assert mgr.is_duplicate_asdu(_ASDU) is True         # 窗口内重复
        assert mgr.is_duplicate_asdu(_ASDU_OTHER) is False  # 不同 ASDU


class TestSessionDedupGate:
    """会话层去重门控：I 帧序列号/确认照常，重复 ASDU 不重复分发."""

    def test_duplicate_asdu_dispatched_once(self):
        from core.config import RedundancyConfig
        from core.engine.master import MasterEngine
        from core.engine.master_redundancy import MasterRedundancy

        eng = MasterEngine()   # 未启用冗余的真实引擎（会话层被门控短路的前提）
        mgr = MasterRedundancy(
            eng, RedundancyConfig(enabled=True, standby_host="127.0.0.1",
                                  standby_port=2405),
            host="127.0.0.1", port=2404, reconnect_interval=1.0,
            max_reconnects=0,
            on_frame=eng._on_frame_received,
            on_connected=eng._on_tcp_connected,
            on_disconnected=eng._on_tcp_disconnected,
        )
        eng._redundancy = mgr

        dispatched: list[bytes] = []
        eng._protocol.decode_and_dispatch = lambda asdu: dispatched.append(bytes(asdu))

        # 三个连续 I 帧：前两个 ASDU 相同（仅 APCI 序号不同），第三个不同
        for tx in (0, 1, 2):
            frame = _i_frame(tx, 1, _ASDU if tx < 2 else _ASDU_OTHER)
            apci, _ = APCICodec.decode(frame)
            eng._session.handle_i_frame(apci, frame)

        assert dispatched == [_ASDU, _ASDU_OTHER], \
            "重复 ASDU 只分发一次；不同 ASDU 正常分发"


# ── 配置无效失败路径 ─────────────────────────────────────────────

class TestRedundancyConfigValidation:
    def test_empty_standby_host_rejected(self):
        from core.config import RedundancyConfig
        from core.engine.master import MasterEngine

        with pytest.raises(ValueError, match="standby_host"):
            MasterEngine(redundancy=RedundancyConfig(enabled=True, standby_host=""))

    def test_invalid_standby_port_rejected(self):
        from core.config import RedundancyConfig
        from core.engine.master import MasterEngine

        with pytest.raises(ValueError, match="standby_port"):
            MasterEngine(redundancy=RedundancyConfig(
                enabled=True, standby_host="127.0.0.1", standby_port=70000))

    def test_standby_same_as_primary_rejected(self):
        from core.config import RedundancyConfig
        from core.engine.master import MasterEngine

        with pytest.raises(ValueError, match="相同"):
            MasterEngine(redundancy=RedundancyConfig(
                enabled=True, standby_host="127.0.0.1", standby_port=2404))

    def test_disabled_redundancy_behaves_as_single_channel(self):
        """未启用冗余 → 与既有单通道行为完全一致（seam 不变）."""
        from core.config import RedundancyConfig
        from core.engine.master import MasterEngine
        from core.transport.connection import TCPClient

        eng = MasterEngine(redundancy=RedundancyConfig(enabled=False))
        assert eng._redundancy is None
        assert isinstance(eng._client, TCPClient)
        eng2 = MasterEngine()
        assert eng2._redundancy is None and isinstance(eng2._client, TCPClient)

    def test_redundancy_config_yaml_roundtrip(self, tmp_path):
        from core.config import AppConfig, load_config

        cfg = AppConfig()
        cfg.redundancy.enabled = True
        cfg.redundancy.standby_host = "10.0.0.2"
        cfg.redundancy.standby_port = 2405
        cfg.redundancy.switch_timeout = 1.5
        cfg.redundancy.dedup_window = 3.0
        out = tmp_path / "c.yaml"
        cfg.save(out)
        assert load_config(out).redundancy == cfg.redundancy

    def test_shipped_master_config_has_redundancy_disabled(self):
        from core.config import load_config

        root = Path(__file__).parent.parent
        cfg = load_config(root / "configs" / "master_config.yaml")
        assert cfg.redundancy.enabled is False


# ── 切换 E2E：主用断开 → 备用接管 → STARTDT/GI 重建 → 数据继续 ──

class TestRedundancySwitchEndToEnd:
    @pytest.mark.asyncio
    async def test_failover_switchover_time_and_gi_rebuild(self):
        """主用前置机停机 → 备用接管（STARTDT CON 归零 VS/VR）→ 总召唤重建.

        切换耗时阈值：**3.0s**（从主用 TCP 断开到备用上总召唤下发；
        组成：TCP 断开检测 ~0s + 切换 ~0s + auto STARTDT 0.2s 延迟 +
        STARTDT 往返 + GI 下发。冗余配置 switch_timeout=2.0 只约束
        STARTDT CON 等待，实测余量充足）。
        """
        from core.config import RedundancyConfig
        from core.engine.master import MasterEngine
        from core.engine.slave import SlaveEngine, SlaveEvent

        port_primary = _free_port()
        port_standby = _free_port()

        async def _make_slave(port):
            eng = SlaveEngine(host="127.0.0.1", port=port, common_addr=1,
                              point_table=_demo_points(),
                              spontaneous_enabled=False)
            eng.data_store.init_from_point_table(eng.point_table)
            return eng

        slave_primary = await _make_slave(port_primary)
        slave_standby = await _make_slave(port_standby)
        standby_gi: list = []
        slave_standby.set_event_callback(
            lambda e, d: standby_gi.append(e) if e == SlaveEvent.GI_RECEIVED else None)

        master = MasterEngine(
            host="127.0.0.1", port=port_primary, common_addr=1,
            auto_start=True, auto_gi=False, reconnect=True,
            reconnect_interval=0.2,
            redundancy=RedundancyConfig(
                enabled=True, standby_host="127.0.0.1",
                standby_port=port_standby, switch_timeout=2.0,
                dedup_window=5.0),
        )

        await slave_primary.start()
        await slave_standby.start()
        try:
            await master.start()
            # 1) 主用通道建立并 Running
            assert await _wait_until(lambda: master.is_running, timeout=8.0), \
                f"主用通道未进入 Running: {master.state}"
            # 2) 备用通道预连接就绪（TCP + STARTDT）
            assert await _wait_until(
                lambda: slave_standby.client_count > 0, timeout=8.0), \
                "备用前置机未收到预连接"

            primary_client = master._client
            assert primary_client is master._redundancy.primary

            # 3) 主用前置机停机 → 切换
            t0 = time.monotonic()
            await asyncio.wait_for(slave_primary.stop(), timeout=5.0)

            # 4) 备用接管：活动客户端切换 + 重新 Running + 总召唤重建
            assert await _wait_until(
                lambda: master._client is master._redundancy.standby,
                timeout=8.0), "切换后活动客户端应为备用通道"
            assert master._redundancy.active is master._redundancy.standby

            # 5) 切换后总召唤在备用前置机上发生（链路重建的标志）
            assert await _wait_until(
                lambda: bool(standby_gi), timeout=8.0), \
                "切换后未在备用通道上重走总召唤"
            elapsed = time.monotonic() - t0
            assert elapsed < 3.0, f"切换耗时 {elapsed:.3f}s 超过阈值 3.0s"

            # 6) VS/VR 已归零（STARTDT CON 既有行为）：主站随后能以新序号收发
            #    —— 备用前置机响应总召唤且主站成功接收（序号失配会触发断链）
            assert await _wait_until(
                lambda: master.data_store.stats.get("yx_count", 0) > 0
                or master.data_store.stats.get("yc_count", 0) > 0,
                timeout=8.0), f"切换后未收到总召唤数据: {master.data_store.stats}"

            # 7) 原主用前置机恢复 → 自动成为新的备用预连接
            await slave_primary.start()
            assert await _wait_until(
                lambda: slave_primary.client_count > 0 and
                master._redundancy.primary.is_connected, timeout=8.0), \
                "原主用通道恢复后应自动重建预连接"
            assert master._client is master._redundancy.standby, \
                "恢复的通道不得抢占活动态"
        finally:
            await asyncio.wait_for(master.stop(), timeout=6.0)
            for s in (slave_primary, slave_standby):
                try:
                    await asyncio.wait_for(s.stop(), timeout=5.0)
                except Exception:
                    pass

    @pytest.mark.asyncio
    async def test_switch_with_plaintext_data_continues(self):
        """切换后主站继续处理备用链路的自发数据（数据继续的直证）."""
        from core.config import RedundancyConfig
        from core.engine.master import MasterEngine
        from core.engine.slave import SlaveEngine

        port_primary = _free_port()
        port_standby = _free_port()
        slave_primary = SlaveEngine(host="127.0.0.1", port=port_primary,
                                    common_addr=1, point_table=_demo_points(),
                                    spontaneous_enabled=False)
        slave_primary.data_store.init_from_point_table(slave_primary.point_table)
        slave_standby = SlaveEngine(host="127.0.0.1", port=port_standby,
                                    common_addr=1, point_table=_demo_points(),
                                    spontaneous_enabled=False)
        slave_standby.data_store.init_from_point_table(slave_standby.point_table)

        master = MasterEngine(
            host="127.0.0.1", port=port_primary, common_addr=1,
            auto_start=True, auto_gi=False, reconnect=True,
            reconnect_interval=0.2,
            redundancy=RedundancyConfig(
                enabled=True, standby_host="127.0.0.1",
                standby_port=port_standby, switch_timeout=2.0),
        )
        await slave_primary.start()
        await slave_standby.start()
        try:
            await master.start()
            assert await _wait_until(lambda: master.is_running, timeout=8.0)
            await asyncio.wait_for(slave_primary.stop(), timeout=5.0)
            assert await _wait_until(
                lambda: master._client is master._redundancy.standby
                and master.is_running, timeout=8.0)

            # 备用前置机自发上送 → 主站经去重路由正常入库
            await slave_standby.send_spontaneous_yx(1, True)
            assert await _wait_until(
                lambda: master.data_store.stats.get("yx_count", 0) > 0,
                timeout=8.0), "切换后备用链路自发数据未到达主站"
        finally:
            await asyncio.wait_for(master.stop(), timeout=6.0)
            for s in (slave_primary, slave_standby):
                try:
                    await asyncio.wait_for(s.stop(), timeout=5.0)
                except Exception:
                    pass
