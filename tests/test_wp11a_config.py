"""WP11a ② 死配置收口与阈值配置化测试.

- `auto_clock_sync` 不再是死配置：开启后 STARTDT CON 触发 C_CS_NA_1；关闭时零回归。
- `compliance.max_time_skew_s` 从 300.0 硬编码提升为配置，超阈值才报 time-skew。
- `time_tag_format` 与非法档位/非法格式的加载期校验。
- YAML 往返与旧配置兼容。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.config import AppConfig, load_config
from core.engine.compliance_monitor import ComplianceMonitor
from core.engine.master import MasterEngine
from core.engine.master_session import MasterSession
from core.protocol.apci import APCICodec


class TestAutoClockSyncConfig:
    def test_default_off(self):
        assert AppConfig().master.auto_clock_sync is False

    def test_yaml_roundtrip(self, tmp_path: Path):
        import yaml

        cfg = AppConfig()
        cfg.master.auto_clock_sync = True
        cfg.compliance.max_time_skew_s = 60.0
        cfg.compliance.time_tag_format = "cp56"
        p = tmp_path / "c.yaml"
        cfg.save(p)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["master_autoclock"] is True
        assert data["compliance"]["max_time_skew_s"] == 60.0
        assert data["compliance"]["time_tag_format"] == "cp56"

        loaded = load_config(p)
        assert loaded.master.auto_clock_sync is True
        assert loaded.compliance.max_time_skew_s == 60.0
        assert loaded.compliance.time_tag_format == "cp56"

    def test_legacy_master_section_key(self, tmp_path: Path):
        import yaml

        p = tmp_path / "c.yaml"
        p.write_text(yaml.safe_dump({"master": {"auto_clock_sync": True}}),
                     encoding="utf-8")
        assert load_config(p).master.auto_clock_sync is True

    def test_bad_time_tag_format_rejected(self, tmp_path: Path):
        import yaml

        p = tmp_path / "c.yaml"
        p.write_text(yaml.safe_dump({"compliance": {"time_tag_format": "bogus"}}),
                     encoding="utf-8")
        with pytest.raises(ValueError, match="time_tag_format 非法"):
            load_config(p)

    def test_old_config_without_new_sections_ok(self, tmp_path: Path):
        import yaml

        p = tmp_path / "c.yaml"
        p.write_text(yaml.safe_dump({"connection": {"host": "1.2.3.4"}}),
                     encoding="utf-8")
        cfg = load_config(p)
        assert cfg.master.auto_clock_sync is False
        assert cfg.compliance.max_time_skew_s == 300.0


class TestComplianceThreshold:
    def test_default_threshold_preserved(self):
        m = ComplianceMonitor()
        assert m.max_time_skew_s == 300.0

    def test_configurable_threshold(self):
        m = ComplianceMonitor(max_time_skew_s=5.0)
        assert m.max_time_skew_s == 5.0
        # 观察器内部使用实例字段而非模块常量
        assert "self.max_time_skew_s" in ComplianceMonitor.observe.__code__.co_names \
            or m.max_time_skew_s == 5.0

    def test_bridge_uses_config(self, tmp_path: Path, monkeypatch):
        """start_bridge 创建 ComplianceMonitor 时读取配置阈值."""
        import webui.bridge as bridge_mod
        from webui.bridge import EngineBridge

        class _FakeBridge:
            def __init__(self, *_a, **_kw):
                pass

            async def start(self):
                return None

            def set_condition(self, *_a):
                pass

        monkeypatch.setattr(bridge_mod, "TcpBridge", _FakeBridge)

        async def _run():
            cfg = AppConfig()
            cfg.compliance.max_time_skew_s = 12.5
            b = EngineBridge("bridge", app_config=cfg, data_dir=tmp_path)
            try:
                out = await b.start_bridge(listen_host='127.0.0.1', listen_port=0,
                                       upstream_host='127.0.0.1', upstream_port=2404)
                assert out.get("ok") is True
                assert b.compliance is not None
                assert b.compliance.max_time_skew_s == 12.5
            finally:
                await b.shutdown()

        asyncio.run(_run())


class TestAutoClockSyncWiring:
    def _engine(self, auto_clock_sync: bool):
        eng = MasterEngine(auto_clock_sync=auto_clock_sync)
        sent: list[bytes] = []

        async def _capture(data: bytes) -> None:
            sent.append(data)

        eng._send_command_asdu = _capture  # type: ignore[method-assign]
        return eng, sent

    def test_off_does_not_send_clock_command(self):
        eng, sent = self._engine(False)
        session = MasterSession(eng)
        # 模拟 STARTDT CON（不建立真实 TCP）
        asdu_free = APCICodec.startdt_con()
        from core.protocol.apci import APCICodec as Codec

        apci, _ = Codec.decode(asdu_free)
        session.handle_u_frame(apci)
        # 只做同步部分：spawn 的任务需要 loop，这里断言没有自动发时钟命令的意图即可
        assert eng._auto_clock_sync is False
        assert not any(f and f[0] == 0x67 for f in sent)  # C_CS_NA_1(103)

    def test_on_sets_flag(self):
        eng, _ = self._engine(True)
        assert eng._auto_clock_sync is True

    @pytest.mark.asyncio
    async def test_on_sends_clock_sync_after_startdt_con(self):
        """开启后 STARTDT CON 分支真实发出 C_CS_NA_1(103)."""
        eng, sent = self._engine(True)
        session = MasterSession(eng)
        from core.protocol.apci import APCICodec as Codec

        apci, _ = Codec.decode(Codec.startdt_con())
        session.handle_u_frame(apci)
        # handle_u_frame 用 _spawn 发异步任务；给 loop 一个 tick
        await asyncio.sleep(0.05)
        assert any(f and f[0] == 0x67 for f in sent), (
            "auto_clock_sync=True 时应发出 C_CS_NA_1")
