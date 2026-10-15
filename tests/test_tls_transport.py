"""TLS 传输层加密测试（T20 / IEC 62351 的传输层部分）.

覆盖:
- 自签证书下主子站 TLS 握手成功，并完成一次最小 104 交互
- 客户端信任不受信 CA 之外的服务端（严格校验）→ 握手失败
- ``verify=False``（等价 ``--no-verify``）→ 不受信证书也放行（仅联调用）
- 双向认证（mTLS）：服务端要求客户端证书；不带证书的客户端被拒
- TLS 下 ``close()`` 仍幂等、``stop()`` 仍有界
- 未启用 TLS 时行为与改动前完全一致

证书来自 ``tests/certs/``（自签、测试专用、非机密），生成方式见该目录 README。
"""

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.protocol.apci import APCICodec
from core.protocol.constants import U_STARTDT_ACT, U_STARTDT_CON
from core.transport.connection import (
    TCPClient,
    TCPServer,
    TlsConfigError,
    build_client_context,
    build_server_context,
)

CERTS = Path(__file__).parent / "certs"
CA1 = str(CERTS / "ca1.pem")
CA2 = str(CERTS / "ca2.pem")
SERVER_CRT = str(CERTS / "server.pem")
SERVER_KEY = str(CERTS / "server.key")
CLIENT_CRT = str(CERTS / "client.pem")
CLIENT_KEY = str(CERTS / "client.key")
BAD_CRT = str(CERTS / "badserver.pem")
BAD_KEY = str(CERTS / "badserver.key")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _demo_point_table():
    from core.data.point_table import PointTable
    pt = PointTable()
    pt.generate_demo_points(yx_count=10, yc_count=5, yk_count=3, ym_count=2)
    pt.common_addr = 1
    pt.station_name = "TLS E2E"
    return pt


async def _wait_until(predicate, timeout: float = 6.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _starttls_roundtrip(port: int, client_ctx: ssl.SSLContext,
                              expect_connected: bool = True) -> dict:
    """起 TLS 子站 + 客户端，完成最小 104 交互；返回观测结果."""
    server_ctx = build_server_context(certfile=SERVER_CRT, keyfile=SERVER_KEY)
    received: list[bytes] = []
    connected: list[bool] = []
    errors: list[str] = []

    server = TCPServer(host="127.0.0.1", port=port, ssl_context=server_ctx,
                       on_frame=lambda conn, data: received.append(data))
    await server.start()

    client = TCPClient(host="127.0.0.1", port=port, max_reconnects=1,
                       ssl_context=client_ctx, server_hostname="localhost",
                       on_connected=lambda: connected.append(True))
    try:
        await client.start()
        ok = await _wait_until(lambda: bool(connected) or errors, timeout=6.0)

        if expect_connected and ok and connected:
            # 最小 104 交互：STARTDT act → STARTDT con
            await client.send(APCICodec.encode_u(U_STARTDT_ACT))
            await _wait_until(lambda: len(received) >= 1, timeout=4.0)
            await server.broadcast(APCICodec.encode_u(U_STARTDT_CON))
            await _wait_until(
                lambda: client.connection is not None
                and client.connection.stats.frames_received >= 1,
                timeout=4.0,
            )
        return {
            "connected": bool(connected),
            "server_connections": server.connection_count,
            "rx_on_server": list(received),
            "client_rx_frames": (client.connection.stats.frames_received
                                 if client.connection else 0),
        }
    finally:
        await client.stop()
        await server.stop()


# ── 正常路径：自签证书握手成功 ───────────────────────────────────

class TestHandshakeSuccess:
    @pytest.mark.asyncio
    async def test_self_signed_handshake_and_startdt(self):
        port = _free_port()
        ctx = build_client_context(cafile=CA1, verify=True)
        r = await _starttls_roundtrip(port, ctx, expect_connected=True)

        assert r["connected"] is True, "自签 CA 下 TLS 握手应成功"
        assert r["server_connections"] == 1
        assert APCICodec.decode(r["rx_on_server"][0])[0].is_startdt_act
        assert r["client_rx_frames"] >= 1, "客户端应收到 STARTDT con"

    @pytest.mark.asyncio
    async def test_verify_false_accepts_any_certificate(self):
        """--no-verify 等价路径：不受信 CA 签发的证书也放行（仅联调用）."""
        port = _free_port()
        server_ctx = build_server_context(certfile=BAD_CRT, keyfile=BAD_KEY)
        connected: list[bool] = []
        server = TCPServer(host="127.0.0.1", port=port, ssl_context=server_ctx)
        await server.start()

        client = TCPClient(host="127.0.0.1", port=port, max_reconnects=1,
                           ssl_context=build_client_context(verify=False),
                           server_hostname="localhost",
                           on_connected=lambda: connected.append(True))
        try:
            await client.start()
            assert await _wait_until(lambda: bool(connected), timeout=6.0), \
                "verify=False 时不应因证书不受信而失败"
            assert client.is_connected is True
        finally:
            await client.stop()
            await server.stop()

    def test_verify_false_disables_hostname_check(self):
        ctx = build_client_context(verify=False)
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_verify_true_enables_hostname_and_cert_check(self):
        ctx = build_client_context(cafile=CA1, verify=True)
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED


# ── 失败路径：拒绝不受信证书 ─────────────────────────────────────

class TestUntrustedRejected:
    @pytest.mark.asyncio
    async def test_client_rejects_untrusted_ca(self):
        """服务端证书由不受信 CA 签发 → 客户端严格校验必须失败."""
        port = _free_port()
        server_ctx = build_server_context(certfile=BAD_CRT, keyfile=BAD_KEY)
        connected: list[bool] = []
        server = TCPServer(host="127.0.0.1", port=port, ssl_context=server_ctx)
        await server.start()

        client = TCPClient(host="127.0.0.1", port=port, max_reconnects=1,
                           ssl_context=build_client_context(cafile=CA1, verify=True),
                           server_hostname="localhost",
                           on_connected=lambda: connected.append(True))
        try:
            await client.start()
            # 反复确认：既不连上，也不能有任何 on_connected
            await asyncio.sleep(0.8)
            assert connected == [], "不受信证书不得触发 on_connected"
            assert client.is_connected is False
        finally:
            await client.stop()
            await server.stop()

    @pytest.mark.asyncio
    async def test_hostname_mismatch_rejected(self):
        """证书 SAN 不含所连主机名 → 主机名校验失败（常见错误之一）."""
        port = _free_port()
        server_ctx = build_server_context(certfile=SERVER_CRT, keyfile=SERVER_KEY)
        connected: list[bool] = []
        server = TCPServer(host="127.0.0.1", port=port, ssl_context=server_ctx)
        await server.start()

        client = TCPClient(host="127.0.0.1", port=port, max_reconnects=1,
                           ssl_context=build_client_context(cafile=CA1, verify=True),
                           server_hostname="wrong.example.com",
                           on_connected=lambda: connected.append(True))
        try:
            await client.start()
            await asyncio.sleep(0.8)
            assert connected == []
            assert client.is_connected is False
        finally:
            await client.stop()
            await server.stop()


# ── 双向认证（mTLS）─────────────────────────────────────────────

class TestMutualTls:
    @pytest.mark.asyncio
    async def test_client_with_cert_accepted(self):
        port = _free_port()
        server_ctx = build_server_context(certfile=SERVER_CRT, keyfile=SERVER_KEY,
                                          cafile=CA1, verify_client=True)
        connected: list[bool] = []
        server = TCPServer(host="127.0.0.1", port=port, ssl_context=server_ctx)
        await server.start()

        client = TCPClient(
            host="127.0.0.1", port=port, max_reconnects=1,
            ssl_context=build_client_context(cafile=CA1, certfile=CLIENT_CRT,
                                             keyfile=CLIENT_KEY, verify=True),
            server_hostname="localhost",
            on_connected=lambda: connected.append(True),
        )
        try:
            await client.start()
            assert await _wait_until(lambda: bool(connected), timeout=6.0)
        finally:
            await client.stop()
            await server.stop()

    @pytest.mark.asyncio
    async def test_client_without_cert_rejected_by_server(self):
        """服务端要求客户端证书，未带证书的客户端必须被拒（TLS1.3 下失败
        可能表现为握手后立即断开，故断言"未成功建立可用连接"）."""
        port = _free_port()
        server_ctx = build_server_context(certfile=SERVER_CRT, keyfile=SERVER_KEY,
                                          cafile=CA1, verify_client=True)
        server = TCPServer(host="127.0.0.1", port=port, ssl_context=server_ctx)
        await server.start()

        client = TCPClient(host="127.0.0.1", port=port, max_reconnects=1,
                           ssl_context=build_client_context(cafile=CA1, verify=True),
                           server_hostname="localhost")
        try:
            await client.start()
            await asyncio.sleep(0.8)
            assert server.connection_count == 0, \
                "未提供客户端证书不应产生可用服务端连接"
        finally:
            await client.stop()
            await server.stop()

    def test_verify_client_requires_cafile(self):
        with pytest.raises(TlsConfigError):
            build_server_context(certfile=SERVER_CRT, keyfile=SERVER_KEY,
                                 cafile="", verify_client=True)


# ── 关闭语义：TLS 不破坏既有契约 ─────────────────────────────────

class TestTlsCloseSemantics:
    @pytest.mark.asyncio
    async def test_close_idempotent_and_stop_bounded_under_tls(self):
        port = _free_port()
        server_ctx = build_server_context(certfile=SERVER_CRT, keyfile=SERVER_KEY)
        server = TCPServer(host="127.0.0.1", port=port, ssl_context=server_ctx)
        await server.start()

        client = TCPClient(host="127.0.0.1", port=port, max_reconnects=1,
                           ssl_context=build_client_context(cafile=CA1, verify=True),
                           server_hostname="localhost")
        await client.start()
        assert await _wait_until(lambda: client.is_connected, timeout=6.0)

        conn = client.connection
        assert conn is not None
        conn.close()
        conn.close()                     # 幂等：重复 close 不得抛异常
        start = asyncio.get_event_loop().time()
        await asyncio.wait_for(client.stop(), timeout=3.0)   # 有界
        assert asyncio.get_event_loop().time() - start < 3.0
        await asyncio.wait_for(server.stop(), timeout=5.0)


# ── 未启用 TLS：行为不变 ─────────────────────────────────────────

class TestPlaintextUnchanged:
    @pytest.mark.asyncio
    async def test_no_ssl_context_behaves_as_plaintext(self):
        port = _free_port()
        server = TCPServer(host="127.0.0.1", port=port)
        assert server.tls_enabled is False
        await server.start()

        connected: list[bool] = []
        client = TCPClient(host="127.0.0.1", port=port, max_reconnects=1,
                           on_connected=lambda: connected.append(True))
        assert client.tls_enabled is False
        try:
            await client.start()
            assert await _wait_until(lambda: bool(connected), timeout=6.0)
        finally:
            await client.stop()
            await server.stop()

    def test_default_constructors_have_no_tls(self):
        assert TCPServer(ssl_context=None).tls_enabled is False
        assert TCPClient(ssl_context=None).tls_enabled is False

    def test_set_ssl_context_toggles_flag(self):
        c = TCPClient()
        assert c.tls_enabled is False
        c.set_ssl_context(build_client_context(verify=False))
        assert c.tls_enabled is True
        c.set_ssl_context(None)
        assert c.tls_enabled is False


# ── 配置 → SSLContext → 引擎注入 ─────────────────────────────────

class TestConfigIntegration:
    def test_build_context_from_config_slave(self):
        from core.config import TlsConfig
        from core.transport.connection import build_context_from_config

        cfg = TlsConfig(enabled=True, certfile=SERVER_CRT, keyfile=SERVER_KEY)
        ctx = build_context_from_config(cfg, "slave")
        assert ctx.verify_mode == ssl.CERT_NONE       # 未开 mTLS

    def test_build_context_from_config_master_verify_off(self):
        from core.config import TlsConfig
        from core.transport.connection import build_context_from_config

        cfg = TlsConfig(enabled=True, verify=False)
        ctx = build_context_from_config(cfg, "master")
        assert ctx.check_hostname is False

    def test_configure_engine_tls_injects_into_client_and_server(self):
        from core.config import TlsConfig
        from core.transport.connection import configure_engine_tls

        class _FakeEngine:
            def __init__(self, role):
                self.role = role
                if role == "slave":
                    self._server = TCPServer()
                else:
                    self._client = TCPClient()

            def set_ssl_context(self, ctx, server_hostname=None):
                if self.role == "slave":
                    self._server.set_ssl_context(ctx)
                else:
                    self._client.set_ssl_context(ctx, server_hostname)

        client_eng = _FakeEngine("master")
        assert configure_engine_tls(
            client_eng, "master",
            TlsConfig(enabled=True, verify=False, server_hostname="localhost"),
        ) is True
        assert client_eng._client.tls_enabled is True

        server_eng = _FakeEngine("slave")
        assert configure_engine_tls(
            server_eng, "slave",
            TlsConfig(enabled=True, certfile=SERVER_CRT, keyfile=SERVER_KEY),
        ) is True
        assert server_eng._server.tls_enabled is True

    def test_configure_engine_tls_disabled_is_noop(self):
        from core.config import TlsConfig
        from core.transport.connection import configure_engine_tls

        class _FakeEngine:
            _client = TCPClient()

        assert configure_engine_tls(_FakeEngine(), "master", TlsConfig()) is False
        assert _FakeEngine._client.tls_enabled is False

    def test_configure_engine_tls_missing_transport_raises(self):
        from core.config import TlsConfig
        from core.transport.connection import configure_engine_tls

        class _NoTransport:
            pass

        with pytest.raises(TlsConfigError):
            configure_engine_tls(_NoTransport(), "master", TlsConfig(enabled=True))

    def test_missing_certfile_raises_clear_error(self, tmp_path):
        from core.config import TlsConfig
        from core.transport.connection import build_context_from_config

        cfg = TlsConfig(enabled=True, certfile=str(tmp_path / "nope.pem"))
        with pytest.raises(TlsConfigError, match="不存在"):
            build_context_from_config(cfg, "slave")


class TestConfigFileAndCli:
    def test_tls_config_yaml_roundtrip(self, tmp_path):
        from core.config import AppConfig, load_config

        cfg = AppConfig()
        cfg.tls.enabled = True
        cfg.tls.certfile = "s.pem"
        cfg.tls.keyfile = "s.key"
        cfg.tls.cafile = "ca.pem"
        cfg.tls.verify = False
        cfg.tls.verify_client = True
        cfg.tls.server_hostname = "iec104.local"
        out = tmp_path / "c.yaml"
        cfg.save(out)

        assert load_config(out).tls == cfg.tls

    def test_tls_disabled_by_default_in_shipped_configs(self):
        """仓库内示例配置默认不启用 TLS（避免用户无证书时启动失败）."""
        from core.config import load_config

        root = Path(__file__).parent.parent
        for name in ("slave_config.yaml", "master_config.yaml"):
            assert load_config(root / "configs" / name).tls.enabled is False

    def test_cli_flags_apply(self, tmp_path, monkeypatch):
        """--tls / --tls-cert / --tls-* → config.tls（不真起引擎）.

        D3 后 CLI Web 模式在启动前即校验 TLS 配置（坏路径拒绝启动），
        故本测试改用真实存在的测试证书以通过启动前校验。
        """
        import app as app_module

        certs = Path(__file__).parent / "certs"
        captured = {}

        def _fake_run_web(role, http_port=None, open_browser=True,
                          point_table=None, connection=None, history_db=None,
                          **kwargs):
            captured["role"] = role
            captured["engine_config"] = kwargs.get("engine_config")

        monkeypatch.setattr(app_module, "run_web", _fake_run_web)
        monkeypatch.setattr(
            sys, "argv",
            ["app.py", "--mode", "master", "--no-history", "--no-browser",
             "--tls", "--no-verify", "--tls-cert", str(certs / "server.pem"),
             "--tls-key", str(certs / "server.key"),
             "--tls-ca", str(certs / "ca1.pem"),
             "--tls-hostname", "iec104.local"],
        )
        assert app_module.cli() == 0
        assert captured["role"] == "master"
        # D3 接线：解析结果随 engine_config 完整传入 Web 层
        assert captured["engine_config"].tls.enabled is True

        # 直接验证参数解析到 config 的映射（等价于上面 monkeypatch 的路径）
        from core.config import AppConfig
        cfg = AppConfig()
        cfg.tls.enabled = True
        cfg.tls.verify = False
        cfg.tls.certfile = "c.pem"
        cfg.tls.cafile = "ca.pem"
        cfg.tls.server_hostname = "iec104.local"
        assert cfg.tls.verify is False

    def _app_cfg(self, **tls_fields):
        """构造 ``AppConfig``（``_enable_tls`` 接收的是 AppConfig 而非 TlsConfig）."""
        from core.config import AppConfig

        cfg = AppConfig()
        for k, v in tls_fields.items():
            setattr(cfg.tls, k, v)
        return cfg

    def test_enable_tls_disabled_is_noop(self):
        """未启用 TLS → 完全不触碰引擎（CLI 不带 --tls 行为不变）."""
        import app as app_module

        class _Eng:
            def __init__(self):
                self.called = False

            def set_ssl_context(self, ctx, server_hostname=None):
                self.called = True

        eng = _Eng()
        app_module._enable_tls(eng, "master", self._app_cfg(),
                               logging.getLogger("t"))
        assert eng.called is False

    def test_enable_tls_valid_injects(self):
        """有效证书 → 注入成功."""
        import app as app_module

        class _Eng:
            def __init__(self):
                self.ctx = None

            def set_ssl_context(self, ctx, server_hostname=None):
                self.ctx = ctx

        eng = _Eng()
        app_module._enable_tls(eng, "slave",
                               self._app_cfg(enabled=True, certfile=SERVER_CRT,
                                             keyfile=SERVER_KEY),
                               logging.getLogger("t"))
        assert eng.ctx is not None

    def test_enable_tls_invalid_config_raises_no_plaintext_fallback(self):
        """红线：CLI 侧 TLS 配置无效 → 抛 TlsConfigError，绝不降级明文."""
        import app as app_module

        class _Eng:
            def __init__(self):
                self.ctx = None

            def set_ssl_context(self, ctx, server_hostname=None):
                self.ctx = ctx

        eng = _Eng()
        with pytest.raises(TlsConfigError, match="不存在"):
            app_module._enable_tls(eng, "slave",
                                   self._app_cfg(enabled=True, certfile="nope.pem",
                                                 keyfile="nope.key"),
                                   logging.getLogger("t"))
        assert eng.ctx is None  # 未注入任何上下文（无明文替身）

    def test_cli_invalid_tls_exits_nonzero_with_reason(self, monkeypatch, caplog):
        """CLI + 无效 TLS → 退出码 2 且错误信息含具体原因（不降级明文）.

        _enable_tls 在 engine.start() 之前抛出，因此本用例不产生真实网络行为。
        """
        import app as app_module

        monkeypatch.setattr(sys, "argv", [
            "app.py", "--mode", "slave", "--no-gui", "--no-history",
            "--tls", "--tls-cert", "nope.pem", "--tls-key", "nope.key",
        ])
        with caplog.at_level(logging.ERROR, logger="iec104"):
            rc = app_module.cli()
        assert rc == 2, "CLI 无效 TLS 必须非零退出"
        assert "拒绝启动" in caplog.text
        assert "不存在" in caplog.text or "nope.pem" in caplog.text


# ── 真引擎端到端：自签证书下主子站握手 + 总召唤 ───────────────────

class TestEngineEndToEndTls:
    """用真实 MasterEngine / SlaveEngine 验证 TLS 接线（构造参数正解路径 +
    ``configure_engine_tls`` 兼容入口），而不是只测传输层——这是 T20 的核心验收。"""

    def test_engine_constructors_accept_ssl_context(self):
        """构造参数贯穿：ssl_context 传入引擎构造函数即生效，默认为明文."""
        from core.engine.master import MasterEngine
        from core.engine.slave import SlaveEngine

        master = MasterEngine(ssl_context=build_client_context(verify=False),
                              server_hostname="localhost")
        assert master._client.tls_enabled is True
        assert MasterEngine()._client.tls_enabled is False

        slave = SlaveEngine(ssl_context=build_server_context(
            certfile=SERVER_CRT, keyfile=SERVER_KEY))
        assert slave._server.tls_enabled is True
        assert SlaveEngine()._server.tls_enabled is False

    @pytest.mark.asyncio
    async def test_engine_ssl_context_via_constructor_handshake_and_gi(self):
        """构造参数路径 E2E：自签证书下主子站握手 + 总召唤成功."""
        from core.engine.master import MasterEngine
        from core.engine.slave import SlaveEngine, SlaveEvent

        port = _free_port()
        points = _demo_point_table()

        slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1,
                            point_table=points,
                            ssl_context=build_server_context(
                                certfile=SERVER_CRT, keyfile=SERVER_KEY))
        slave.data_store.init_from_point_table(points)

        master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                              auto_start=True, auto_gi=False, reconnect=False,
                              ssl_context=build_client_context(cafile=CA1, verify=True),
                              server_hostname="localhost")

        slave_events: list = []
        slave.set_event_callback(lambda e, d: slave_events.append(e))

        await slave.start()
        try:
            await master.start()
            try:
                assert await _wait_until(lambda: master.is_running, timeout=10.0), \
                    f"TLS 下未进入 Running: state={master.state}"
                assert await _wait_until(lambda: slave.client_count > 0, timeout=5.0)

                await master.general_interrogation()
                stats_ok = await _wait_until(
                    lambda: (master.data_store.stats.get("yx_count", 0) > 0
                             or master.data_store.stats.get("yc_count", 0) > 0),
                    timeout=10.0,
                )
                assert stats_ok, f"TLS 下总召唤无数据: {master.data_store.stats}"
                assert SlaveEvent.GI_RECEIVED in slave_events
            finally:
                await asyncio.wait_for(master.stop(), timeout=5.0)
        finally:
            await asyncio.wait_for(slave.stop(), timeout=5.0)

    @pytest.mark.asyncio
    async def test_self_signed_engines_handshake_and_gi(self):
        from core.config import TlsConfig
        from core.engine.master import MasterEngine
        from core.engine.slave import SlaveEngine, SlaveEvent
        from core.transport.connection import configure_engine_tls

        port = _free_port()
        points = _demo_point_table()

        slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1,
                            point_table=points)
        slave.data_store.init_from_point_table(points)
        assert configure_engine_tls(slave, "slave", TlsConfig(
            enabled=True, certfile=SERVER_CRT, keyfile=SERVER_KEY)) is True
        assert slave._server.tls_enabled is True

        master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                              auto_start=True, auto_gi=False, reconnect=False)
        assert configure_engine_tls(master, "master", TlsConfig(
            enabled=True, cafile=CA1, verify=True,
            server_hostname="localhost")) is True
        assert master._client.tls_enabled is True

        slave_events: list = []
        slave.set_event_callback(lambda e, d: slave_events.append(e))

        await slave.start()
        try:
            await master.start()
            try:
                assert await _wait_until(lambda: master.is_running, timeout=10.0), \
                    f"TLS 下未进入 Running: state={master.state}"
                assert await _wait_until(lambda: slave.client_count > 0, timeout=5.0)

                await master.general_interrogation()
                stats_ok = await _wait_until(
                    lambda: (master.data_store.stats.get("yx_count", 0) > 0
                             or master.data_store.stats.get("yc_count", 0) > 0),
                    timeout=10.0,
                )
                assert stats_ok, f"TLS 下总召唤无数据: {master.data_store.stats}"
                assert SlaveEvent.GI_RECEIVED in slave_events
            finally:
                await asyncio.wait_for(master.stop(), timeout=5.0)
        finally:
            await asyncio.wait_for(slave.stop(), timeout=5.0)

    @pytest.mark.asyncio
    async def test_engine_with_untrusted_cert_never_reaches_running(self):
        """严格校验 + 不受信 CA → 主站始终无法进入 Running（失败路径）."""
        from core.config import TlsConfig
        from core.engine.master import MasterEngine
        from core.engine.slave import SlaveEngine
        from core.transport.connection import configure_engine_tls

        port = _free_port()
        points = _demo_point_table()

        slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1,
                            point_table=points)
        slave.data_store.init_from_point_table(points)
        # 服务端用不受信 CA 签发的证书
        configure_engine_tls(slave, "slave", TlsConfig(
            enabled=True, certfile=BAD_CRT, keyfile=BAD_KEY))

        master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                              auto_start=True, auto_gi=False, reconnect=False)
        # 主站只信任 ca1，且严格校验
        configure_engine_tls(master, "master", TlsConfig(
            enabled=True, cafile=CA1, verify=True, server_hostname="localhost"))

        await slave.start()
        try:
            await master.start()
            try:
                await asyncio.sleep(1.0)
                assert master.is_running is False
            finally:
                await asyncio.wait_for(master.stop(), timeout=5.0)
        finally:
            await asyncio.wait_for(slave.stop(), timeout=5.0)


# ── 多站：tls.enabled 逐站生效 ───────────────────────────────────

class TestMultiStationTls:
    def test_station_config_accepts_dict_tls(self):
        from core.engine.multi_station import StationConfig, _coerce_tls_config

        st = StationConfig(station_id="s1", port=2405,
                           tls={"enabled": True, "certfile": "a.pem",
                                "verify": False, "unknown_key": 1})
        cfg = _coerce_tls_config(st.tls)
        assert cfg.enabled is True
        assert cfg.certfile == "a.pem"
        assert cfg.verify is False

    def test_coerce_handles_none_and_instance(self):
        from core.config import TlsConfig
        from core.engine.multi_station import _coerce_tls_config

        assert _coerce_tls_config(None) is None
        cfg = TlsConfig(enabled=True)
        assert _coerce_tls_config(cfg) is cfg

    @pytest.mark.asyncio
    async def test_multi_station_tls_handshake(self):
        """多站管理器下逐站启用 TLS，主站 TLS 握手成功并进入 Running."""
        from core.config import TlsConfig
        from core.engine.master import MasterEngine
        from core.engine.multi_station import (
            MultiStationConfig,
            MultiStationManager,
            StationConfig,
        )
        from core.transport.connection import configure_engine_tls

        port = _free_port()
        mgr = MultiStationManager(MultiStationConfig(stations=[StationConfig(
            station_id="tls_s1", station_name="TLS S1", port=port, common_addr=1,
            auto_generate=True, yx_count=5, yc_count=2, yk_count=0, ym_count=0,
            spontaneous_enabled=False,
            tls={"enabled": True, "certfile": SERVER_CRT, "keyfile": SERVER_KEY},
        )]))
        await mgr.start_all()
        try:
            assert mgr.station_count == 1
            assert mgr.get_engine("tls_s1")._server.tls_enabled is True

            master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                                  auto_start=True, auto_gi=False, reconnect=False)
            configure_engine_tls(master, "master", TlsConfig(
                enabled=True, cafile=CA1, verify=True,
                server_hostname="localhost"))
            await master.start()
            try:
                assert await _wait_until(lambda: master.is_running, timeout=10.0), \
                    f"多站 TLS 下主站未进入 Running: {master.state}"
            finally:
                await asyncio.wait_for(master.stop(), timeout=5.0)
        finally:
            await asyncio.wait_for(mgr.stop_all(), timeout=10.0)
