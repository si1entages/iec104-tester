"""透明桥（T73）测试：切帧器单元 + 真主站↔桥↔真子站全链路集成."""

from __future__ import annotations

import asyncio

import pytest

from core.data.point_table import PointTable
from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine
from core.engine.tcp_bridge import BridgeConfig, FrameSplitter, TcpBridge, describe_frame
from core.protocol.apci import APCICodec

# ── FrameSplitter 单元 ──────────────────────────────────────────────────


def test_splitter_partial_then_complete():
    s = FrameSplitter()
    frame = APCICodec.startdt_act()  # U 帧：68 04 07 00 00 00
    assert s.feed(frame[:3]) == []
    assert s.feed(frame[3:]) == [frame]


def test_splitter_coalesced_and_split_mix():
    """多帧粘连、跨段分割混着来也要切对."""
    f1 = APCICodec.startdt_act()
    f2 = APCICodec.encode_s(rx_seq=5)
    f3 = APCICodec.stopdt_act()
    s = FrameSplitter()
    assert s.feed(f1 + f2) == [f1, f2]
    assert s.feed(f3[:5]) == []          # 半包
    assert s.feed(f3[5:]) == [f3]        # 补齐后吐出


def test_splitter_garbage_resync_count():
    s = FrameSplitter()
    frame = APCICodec.startdt_act()
    assert s.feed(b"\x00\x00" + frame) == [frame]
    assert s.resyncs == 2


def test_splitter_all_garbage_drops_all():
    s = FrameSplitter()
    assert s.feed(b"\xff\xfe\xfd") == []
    assert s.resyncs == 3


def test_splitter_bad_length_resync():
    s = FrameSplitter()
    frame = APCICodec.startdt_act()
    # 68 01（长度域非法）→ 丢 1 字节重同步；随后 0x01 也是脏字节再丢 1 字节，
    # 之后帧头出现、真帧完整切出——透传与观察互不影响
    assert s.feed(b"\x68\x01" + frame) == [frame]
    assert s.resyncs == 2


# ── describe_frame（旁路摘要，绝不抛异常）────────────────────────────────


def test_describe_frame_u_and_garbage():
    u = describe_frame(APCICodec.startdt_act())
    assert "U" in u
    # 垃圾数据回退 raw，不抛
    assert describe_frame(b"\x68\xff\xff\xff").startswith("raw(")


# ── 全链路集成：真主站 ↔ 桥 ↔ 真子站 ────────────────────────────────────


@pytest.mark.asyncio
async def test_bridge_end_to_end_with_real_engines():
    """主站经桥连子站：STARTDT + 总召唤全链路透传，双向帧被旁路观察到."""
    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=3, yk_count=1, ym_count=1)

    slave = SlaveEngine(port=0, point_table=pt)
    await slave.start()
    upstream_port = slave._server._server.sockets[0].getsockname()[1]

    observed: list[tuple[str, bytes]] = []
    bridge = TcpBridge(
        BridgeConfig(listen_host="127.0.0.1", listen_port=0,
                     upstream_host="127.0.0.1", upstream_port=upstream_port),
        on_frame=lambda data, direction, client_id: observed.append((direction, data)),
    )
    await bridge.start()
    bridge_port = bridge.listen_port
    assert bridge_port != 0

    master = MasterEngine(host="127.0.0.1", port=bridge_port, common_addr=1,
                          point_table=pt, auto_gi=True)
    await master.start()

    try:
        # 等 STARTDT + 总召唤往返（上限 10s）
        for _ in range(100):
            if bridge.stats.frames_dn >= 2 and bridge.stats.frames_up >= 2:
                break
            await asyncio.sleep(0.1)
        assert bridge.stats.frames_dn >= 2, f"下行帧不足: {bridge.stats.as_dict()}"
        assert bridge.stats.frames_up >= 2, f"上行帧不足: {bridge.stats.as_dict()}"

        # 双方向都被观察到；client_id 标签一致
        assert {d for d, _ in observed} == {"tx", "rx"}

        # 上行第一帧是子站的 STARTDT_CON（U 帧）——透传内容正确
        first_rx = next(data for d, data in observed if d == "rx")
        apci, _ = APCICodec.decode(first_rx)
        assert apci.is_u_frame and apci.is_startdt_con

        # 下行有总召唤请求（I 帧）
        dn_i_frames = [data for d, data in observed
                       if d == "tx" and APCICodec.decode(data)[0].is_i_frame]
        assert dn_i_frames, "下行应包含总召唤 I 帧"
    finally:
        await master.stop()
        await bridge.stop()
        await slave.stop()

    # 停止后统计保留（只增计数），监听已关
    assert bridge._server is None
    assert bridge.stats.clients_total == 1


@pytest.mark.asyncio
async def test_bridge_upstream_unreachable_closes_client():
    """上游不可达：客户端连接被立即关闭（主站按既有重连逻辑重试），不挂起."""
    bridge = TcpBridge(BridgeConfig(
        listen_host="127.0.0.1", listen_port=0,
        upstream_host="127.0.0.1", upstream_port=1,  # 不可达端口
        connect_timeout=1.0,
    ))
    await bridge.start()
    port = bridge.listen_port

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    # 上游失败 → 服务端关连接 → read 返回 EOF
    try:
        data = await asyncio.wait_for(reader.read(100), timeout=5.0)
        assert data == b""  # EOF
    finally:
        writer.close()
    for _ in range(20):
        if bridge.stats.upstream_errors >= 1:
            break
        await asyncio.sleep(0.1)
    assert bridge.stats.upstream_errors == 1
    await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_start_twice_raises():
    bridge = TcpBridge(BridgeConfig(listen_port=0))
    await bridge.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            await bridge.start()
    finally:
        await bridge.stop()


def test_describe_frame_i_includes_asdu_summary():
    """I 帧摘要带 ASDU 概要（曾因字段名写错静默回退——回归锁定）."""
    apdu = APCICodec.encode_i(
        tx_seq=0, rx_seq=1,
        asdu_data=bytes([100, 1, 6, 0, 1, 0, 0, 0, 0, 20]),  # C_IC_NA_1 act ca=1 qoi=20
    )
    s = describe_frame(apdu)
    assert "C_IC_NA_1" in s and "ca=1" in s and "cot=6" in s


@pytest.mark.asyncio
async def test_bridge_capture_recording(tmp_path):
    """on_frame → PacketRecorder：stop 时落盘（CLI --capture-file 同一链路）."""
    from core.capture.recorder import PacketRecorder

    pt = PointTable()
    pt.generate_demo_points(yx_count=3, yc_count=2, yk_count=0, ym_count=0)
    slave = SlaveEngine(port=0, point_table=pt)
    await slave.start()
    upstream_port = slave._server._server.sockets[0].getsockname()[1]

    cap = tmp_path / "bridge.json"
    recorder = PacketRecorder()
    recorder.start(cap, description="pytest bridge")

    bridge = TcpBridge(
        BridgeConfig(listen_host="127.0.0.1", listen_port=0,
                     upstream_host="127.0.0.1", upstream_port=upstream_port),
        on_frame=lambda data, direction, cid: recorder.record_frame(
            data, direction, metadata={"client_id": cid}),
    )
    await bridge.start()
    master = MasterEngine(host="127.0.0.1", port=bridge.listen_port, common_addr=1,
                          point_table=pt, auto_gi=True)
    await master.start()
    try:
        for _ in range(100):
            if bridge.stats.frames_up >= 2 and bridge.stats.frames_dn >= 2:
                break
            await asyncio.sleep(0.1)
        await master.stop()
        await bridge.stop()
        total = recorder.stop()
        assert total >= 4
        assert cap.exists() and cap.stat().st_size > 0
    finally:
        await slave.stop()


# ── TLS 桥（T84）：明文↔TLS 混合桥接，证书复用 tests/certs ──────────────

from pathlib import Path  # noqa: E402

from core.transport.tls_context import build_client_context, build_server_context  # noqa: E402

CERTS = Path(__file__).parent / "certs"


@pytest.mark.asyncio
async def test_bridge_tls_mixed_upstream():
    """明文主站 → 桥 → TLS 子站（混合桥接）：透传 + 双向观察正常."""
    from core.engine.slave import SlaveEngine

    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=3, yk_count=0, ym_count=0)
    # 真实子站：TLS 服务端（server.pem，主站侧需信任 ca1）
    slave = SlaveEngine(port=0, point_table=pt,
                        ssl_context=build_server_context(certfile=str(CERTS / "server.pem"),
                                                         keyfile=str(CERTS / "server.key")))
    await slave.start()
    upstream_port = slave._server._server.sockets[0].getsockname()[1]

    observed: list[tuple[str, bytes]] = []
    bridge = TcpBridge(BridgeConfig(
        listen_host="127.0.0.1", listen_port=0,
        upstream_host="127.0.0.1", upstream_port=upstream_port,
        upstream_ssl=build_client_context(cafile=str(CERTS / "ca1.pem"), verify=True),
        upstream_hostname="localhost",
    ), on_frame=lambda data, direction, cid: observed.append((direction, data)))
    await bridge.start()

    # 明文客户端：STARTDT_ACT 经桥（TLS 上游）往返
    reader, writer = await asyncio.open_connection("127.0.0.1", bridge.listen_port)
    writer.write(bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00]))
    await writer.drain()
    data = await asyncio.wait_for(reader.readexactly(6), timeout=10.0)
    assert data == bytes([0x68, 0x04, 0x0B, 0x00, 0x00, 0x00])  # STARTDT_CON
    writer.close()

    await asyncio.sleep(0.3)
    assert {d for d, _ in observed} == {"tx", "rx"}   # 解密后帧双向可见（合规监视/录制可用）
    await bridge.stop()
    await slave.stop()


@pytest.mark.asyncio
async def test_bridge_tls_listen_side():
    """TLS 主站 → 桥（listen TLS）→ 明文子站：监听侧加密同样透传."""
    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=3, yk_count=0, ym_count=0)
    slave = SlaveEngine(port=0, point_table=pt)
    await slave.start()
    upstream_port = slave._server._server.sockets[0].getsockname()[1]

    observed: list[tuple[str, bytes]] = []
    bridge = TcpBridge(BridgeConfig(
        listen_host="127.0.0.1", listen_port=0,
        upstream_host="127.0.0.1", upstream_port=upstream_port,
        listen_ssl=build_server_context(certfile=str(CERTS / "server.pem"),
                                        keyfile=str(CERTS / "server.key")),
    ), on_frame=lambda data, direction, cid: observed.append((direction, data)))
    await bridge.start()

    # TLS 客户端（信任 ca1，主机名 localhost）接入桥
    client_ctx = build_client_context(cafile=str(CERTS / "ca1.pem"), verify=True)
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", bridge.listen_port, ssl=client_ctx, server_hostname="localhost")
    writer.write(bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00]))
    await writer.drain()
    data = await asyncio.wait_for(reader.readexactly(6), timeout=10.0)
    assert data == bytes([0x68, 0x04, 0x0B, 0x00, 0x00, 0x00])
    writer.close()

    await asyncio.sleep(0.3)
    assert {d for d, _ in observed} == {"tx", "rx"}
    await bridge.stop()
    await slave.stop()


# ── 条件注入（T85）──────────────────────────────────────────────────────

from core.simulation.conditions import NetworkCondition  # noqa: E402


@pytest.mark.asyncio
async def test_bridge_injection_loss_drops_forward_but_observes_original():
    """丢包 100%：转发路径无帧，但旁路观察仍看到原始帧（审计证据不污染）."""
    from core.engine.slave import SlaveEngine

    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=3, yk_count=0, ym_count=0)
    slave = SlaveEngine(port=0, point_table=pt)
    await slave.start()
    upstream_port = slave._server._server.sockets[0].getsockname()[1]

    observed: list[tuple[str, bytes]] = []
    bridge = TcpBridge(BridgeConfig(
        listen_host="127.0.0.1", listen_port=0,
        upstream_host="127.0.0.1", upstream_port=upstream_port,
        condition=NetworkCondition(loss_rate=1.0),
    ), on_frame=lambda data, direction, cid: observed.append((direction, data)))
    await bridge.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", bridge.listen_port)
        writer.write(bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00]))
        await writer.drain()
        # 上游收不到 STARTDT → 无 STARTDT_CON
        try:
            data = await asyncio.wait_for(reader.read(6), timeout=1.0)
            assert data == b"" or len(data) == 0  # 无响应
        except asyncio.TimeoutError:
            pass  # 连接保持但无响应，符合丢帧预期
        writer.close()
        await asyncio.sleep(0.2)
        assert any(d == "tx" for d, _ in observed)  # 原始帧被观察
        assert bridge.injection_stats()["dropped"] >= 1
    finally:
        await bridge.stop()
        await slave.stop()


@pytest.mark.asyncio
async def test_bridge_injection_disabled_is_plain_passthrough():
    """无异常条件：字节流原样透传（与 T73 行为一致）."""
    from core.engine.slave import SlaveEngine

    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=3, yk_count=0, ym_count=0)
    slave = SlaveEngine(port=0, point_table=pt)
    await slave.start()
    upstream_port = slave._server._server.sockets[0].getsockname()[1]

    bridge = TcpBridge(BridgeConfig(
        listen_host="127.0.0.1", listen_port=0,
        upstream_host="127.0.0.1", upstream_port=upstream_port,
        condition=NetworkCondition(),  # 无异常 → 直通
    ))
    await bridge.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", bridge.listen_port)
        writer.write(bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00]))
        await writer.drain()
        data = await asyncio.wait_for(reader.readexactly(6), timeout=10.0)
        assert data == bytes([0x68, 0x04, 0x0B, 0x00, 0x00, 0x00])
        writer.close()
    finally:
        await bridge.stop()
        await slave.stop()


@pytest.mark.asyncio
async def test_bridge_set_condition_realtime():
    """运行中动态设置条件：当前链路立即生效."""
    from core.engine.slave import SlaveEngine

    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=3, yk_count=0, ym_count=0)
    slave = SlaveEngine(port=0, point_table=pt)
    await slave.start()
    upstream_port = slave._server._server.sockets[0].getsockname()[1]
    bridge = TcpBridge(BridgeConfig(
        listen_host="127.0.0.1", listen_port=0,
        upstream_host="127.0.0.1", upstream_port=upstream_port))
    await bridge.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", bridge.listen_port)
        await asyncio.sleep(0.1)  # 等链路注入器登记
        assert len(bridge._injectors) == 1
        bridge.set_condition(NetworkCondition(loss_rate=1.0))
        writer.write(bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00]))
        await writer.drain()
        await asyncio.sleep(0.3)
        assert bridge.injection_stats()["dropped"] >= 1
        bridge.set_condition(None)
        writer.close()
    finally:
        await bridge.stop()
        await slave.stop()


@pytest.mark.asyncio
async def test_bridge_injection_corrupt_and_delay_relays():
    """损坏 100% + 延迟：转发帧字节被改、延迟后仍送达（字节流不丢）."""
    from core.engine.slave import SlaveEngine

    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=3, yk_count=0, ym_count=0)
    slave = SlaveEngine(port=0, point_table=pt)
    await slave.start()
    upstream_port = slave._server._server.sockets[0].getsockname()[1]

    observed: list[tuple[str, bytes]] = []
    bridge = TcpBridge(BridgeConfig(
        listen_host="127.0.0.1", listen_port=0,
        upstream_host="127.0.0.1", upstream_port=upstream_port,
        condition=NetworkCondition(corrupt_rate=1.0, corrupt_bits=1,
                                   delay_ms=10, delay_variance_ms=0),
    ), on_frame=lambda data, direction, cid: observed.append((direction, data)))
    await bridge.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", bridge.listen_port)
        # STARTDT_ACT 被损坏 → 上游不识别，无响应；但观察侧仍是原始帧
        writer.write(bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00]))
        await writer.drain()
        await asyncio.sleep(0.2)
        assert bridge.injection_stats()["corrupted"] >= 1
        assert bridge.injection_stats()["delayed"] >= 1
        assert any(d == "tx" and f == bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00])
                   for d, f in observed)
        writer.close()
    finally:
        await bridge.stop()
        await slave.stop()


# ── WP1：桥两侧 ASDU 地址长度隔离 ─────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_two_sides_have_independent_address_config():
    """桥两侧分别包 use_default，describe_frame 各自按所属侧长度解析、互不串味。

    1B CA / 2B IOA 的帧（监听侧）与 2B CA / 3B IOA 的帧（上游侧）在同一
    进程的两个转发任务里必须各自解出正确 CA，不能互相污染。
    """
    from core.protocol.address import AsduAddressConfig, set_default, use_default
    from core.protocol.apci import APCICodec

    set_default(None)  # 进程默认 2/3/2
    short = AsduAddressConfig(1, 2, 2)
    standard = AsduAddressConfig(2, 3, 2)

    # 用显式配置构造两侧各一帧 I 帧（不依赖全局默认）
    from core.protocol.asdu import ASDU, InformationObject
    from core.protocol.types import COT, TypeID

    def make_i(cfg: AsduAddressConfig, ca: int, ioa: int) -> bytes:
        a = ASDU(type_id=TypeID.C_IC_NA_1, sq=False, num=1, cot=COT.ACT,
                 common_addr=ca, address_config=cfg)
        a.objects.append(InformationObject(ioa=ioa, data=bytes([20])))
        return APCICodec.encode_i(0, 0, a.encode())

    short_frame = make_i(short, 7, 0x0102)
    std_frame = make_i(standard, 0x0102, 0x030201)

    async def side(cfg, frame):
        with use_default(cfg):
            await asyncio.sleep(0)
            return describe_frame(frame)

    a, b = await asyncio.gather(side(short, short_frame), side(standard, std_frame))
    assert "ca=7" in a, f"监听侧 1B CA 解析错误: {a}"
    assert "ca=258" in b, f"上游侧 2B CA 解析错误: {b}"
    set_default(None)


def test_bridge_config_defaults_to_process_level():
    """未给两侧单独配置时，use_default(None) 不覆盖进程默认（WP1 回归）。"""
    from core.protocol.address import AsduAddressConfig, set_default
    from core.protocol.apci import APCICodec
    from core.protocol.asdu import ASDUBuilder

    set_default(AsduAddressConfig(1, 2, 2))
    try:
        # 模拟 _pump_with_address(address=None)：不覆盖，仍应按 1/2/2 解析
        frame = APCICodec.encode_i(0, 0, ASDUBuilder.build_general_interrogation(7))
        assert "ca=7" in describe_frame(frame)
    finally:
        set_default(None)
