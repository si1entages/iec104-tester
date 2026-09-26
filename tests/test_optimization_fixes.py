"""针对 12 项优化修复的回归验证测试.

覆盖:
- P0-1: asdu.py 解码器字典提升为类属性（lazy init，只初始化一次）
- P0-3: config.py hex_view_bytes_per_line / table_page_size roundtrip
- P0-6: assertions.py AssertionError → AssertionFailed 重命名
- P1-1: master.py _send_command_asdu 公共方法
- P1-2: slave.py _build_command_ack 助手
- P1-3: APCICodec.frame_type_of + EngineBase._spawn
- P1-4: master/slave buffer 改为 deque(maxlen=1000)
"""

import sys
from collections import deque
from pathlib import Path

import pytest

# 确保项目根目录在 sys.path 中（与其他测试文件保持一致）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import AppConfig, load_config
from core.engine.base import EngineBase
from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine
from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU
from core.testing import assertions as assertions_module
from core.testing.assertions import AssertionFailed

# ── P0-1: ASDU 解码器字典类级缓存 ───────────────────────────────


class TestAsduDecoderCache:
    """验证 ASDU._ensure_decoders() 延迟初始化只执行一次."""

    def test_ensure_decoders_initializes_cache(self):
        """调用后三个类属性均被填充."""
        ASDU._ensure_decoders()
        assert ASDU._DECODERS is not None
        assert ASDU._TIMED_TYPES is not None
        assert ASDU._CP56_TYPES is not None

    def test_ensure_decoders_idempotent(self):
        """重复调用不重建字典（对象身份保持不变）."""
        ASDU._ensure_decoders()
        decoders_before = ASDU._DECODERS
        timed_before = ASDU._TIMED_TYPES
        cp56_before = ASDU._CP56_TYPES

        ASDU._ensure_decoders()

        assert ASDU._DECODERS is decoders_before
        assert ASDU._TIMED_TYPES is timed_before
        assert ASDU._CP56_TYPES is cp56_before

    def test_decoders_cache_reused_across_decode_calls(self):
        """多次 decode 使用同一缓存字典."""
        from core.protocol.asdu import ASDUBuilder
        from core.protocol.types import COT

        ASDU._ensure_decoders()
        snapshot = ASDU._DECODERS

        # 构造一个 M_SP_NA_1 (单点遥信) ASDU 并解码
        asdu_data = ASDUBuilder.build_single_point(
            common_addr=1, ioa=100, value=True, cot=COT.SPONT
        )
        ASDU.decode(asdu_data)
        ASDU.decode(asdu_data)

        assert ASDU._DECODERS is snapshot


# ── P0-3: 配置 roundtrip ────────────────────────────────────────


class TestConfigRoundtrip:
    """验证 hex_view_bytes_per_line / table_page_size 保存/加载一致."""

    def test_display_config_roundtrip(self, tmp_path):
        """修改 display 配置后 save → load，字段值保持一致."""
        cfg = AppConfig()
        cfg.display.hex_view_bytes_per_line = 32
        cfg.display.table_page_size = 500

        path = tmp_path / "config.yaml"
        cfg.save(path)
        assert path.exists()

        loaded = load_config(path)
        assert loaded.display.hex_view_bytes_per_line == 32
        assert loaded.display.table_page_size == 500

    def test_display_config_defaults_preserved(self, tmp_path):
        """未修改的字段使用默认值 roundtrip 不丢失."""
        cfg = AppConfig()
        path = tmp_path / "config_default.yaml"
        cfg.save(path)
        loaded = load_config(path)

        assert loaded.display.hex_view_bytes_per_line == cfg.display.hex_view_bytes_per_line
        assert loaded.display.table_page_size == cfg.display.table_page_size
        assert loaded.display.theme == cfg.display.theme
        assert loaded.display.max_log_lines == cfg.display.max_log_lines

    def test_load_config_missing_file_returns_defaults(self, tmp_path):
        """加载不存在的文件返回默认配置而不抛异常."""
        cfg = load_config(tmp_path / "nonexistent.yaml")
        assert isinstance(cfg, AppConfig)
        assert cfg.display.hex_view_bytes_per_line == 16
        assert cfg.display.table_page_size == 1000


# ── P0-6: AssertionFailed 重命名 ────────────────────────────────


class TestAssertionFailedRename:
    """验证 AssertionError 已重命名为 AssertionFailed."""

    def test_no_assertionerror_exported(self):
        """assertions 模块不再导出 AssertionError 类名."""
        assert not hasattr(assertions_module, "AssertionError")
        assert hasattr(assertions_module, "AssertionFailed")

    def test_assertion_failed_is_exception(self):
        """AssertionFailed 是 Exception 子类，可正常抛出/捕获."""
        assert issubclass(AssertionFailed, Exception)
        with pytest.raises(AssertionFailed):
            raise AssertionFailed("test failure")

    def test_report_module_uses_new_name(self):
        """report.py 已改用 AssertionFailed."""
        from core.testing import report as report_module

        assert not hasattr(report_module, "AssertionError")


# ── P1-1 / P1-2: 公共方法抽取 ───────────────────────────────────


class TestExtractedHelpers:
    """验证公共方法抽取后的接口存在性."""

    def test_master_send_command_asdu_exists(self):
        """MasterEngine 拥有 _send_command_asdu 公共发送方法."""
        assert hasattr(MasterEngine, "_send_command_asdu")

    def test_slave_build_command_ack_exists(self):
        """SlaveEngine 拥有 _build_command_ack 助手方法."""
        assert hasattr(SlaveEngine, "_build_command_ack")

    def test_engine_base_spawn_exists(self):
        """EngineBase 提供 _spawn 且 master/slave 均继承它."""
        assert hasattr(EngineBase, "_spawn")
        assert issubclass(MasterEngine, EngineBase)
        assert issubclass(SlaveEngine, EngineBase)


# ── P1-3: APCICodec.frame_type_of ──────────────────────────────


class TestFrameTypeOf:
    """验证 frame_type_of 正确区分 I/S/U 三种帧."""

    def test_i_frame(self):
        """I 帧（控制域 bit0=0）返回 'I'."""
        frame = APCICodec.encode_i(tx_seq=0, rx_seq=0, asdu_data=b"\x01\x02")
        assert APCICodec.frame_type_of(frame) == "I"

    def test_s_frame(self):
        """S 帧（控制域低 2 位 = 01）返回 'S'."""
        frame = APCICodec.encode_s(rx_seq=5)
        assert APCICodec.frame_type_of(frame) == "S"

    def test_u_frame(self):
        """U 帧返回 'U'."""
        for frame in (
            APCICodec.startdt_act(),
            APCICodec.startdt_con(),
            APCICodec.stopdt_act(),
            APCICodec.testfr_act(),
            APCICodec.testfr_con(),
        ):
            assert APCICodec.frame_type_of(frame) == "U"

    def test_short_frame_returns_u(self):
        """长度不足 6 字节的帧降级返回 'U'（不抛异常）."""
        assert APCICodec.frame_type_of(b"\x68\x04") == "U"
        assert APCICodec.frame_type_of(b"") == "U"


# ── P1-4: deque(maxlen=1000) 报文缓冲 ──────────────────────────


class TestDequeBuffers:
    """验证 master/slave 的 rx/tx buffer 是有界 deque."""

    def test_master_buffers_are_bounded_deque(self):
        engine = MasterEngine(host="127.0.0.1", port=2404)
        for buf in (engine._rx_buffer, engine._tx_buffer):
            assert isinstance(buf, deque)
            assert buf.maxlen == 1000

    def test_slave_buffers_are_bounded_deque(self):
        engine = SlaveEngine(host="127.0.0.1", port=2404)
        for buf in (engine._rx_buffer, engine._tx_buffer):
            assert isinstance(buf, deque)
            assert buf.maxlen == 1000

    def test_buffer_evicts_oldest_when_full(self):
        """缓冲满后追加会淘汰最旧元素（防内存泄漏）."""
        engine = MasterEngine(host="127.0.0.1", port=2404)
        for i in range(1500):
            engine._rx_buffer.append((float(i), f"frame-{i}".encode(), "RX"))

        assert len(engine._rx_buffer) == 1000
        assert engine._rx_buffer[0][1] == b"frame-500"
        assert engine._rx_buffer[-1][1] == b"frame-1499"
