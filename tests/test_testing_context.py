"""`core/testing/context.py` 测试上下文与结果模型单元测试."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.testing.context import StepResult, StepStatus
from core.testing.context import TestContext as ScriptContext
from core.testing.context import TestResult as ScriptResult
from core.testing.context import TestStatus as ScriptStatus

# ── StepResult / TestResult 模型 ─────────────────────────────────

def test_step_result_autofills_timestamp():
    step = StepResult(step_index=1, action="connect", description="建立连接")

    assert step.timestamp > 0
    assert step.status is StepStatus.PENDING
    assert step.details == {}
    assert step.assertions == []


def test_step_result_keeps_explicit_timestamp():
    step = StepResult(timestamp=123.0)
    assert step.timestamp == 123.0


def test_test_result_counters_and_duration():
    result = ScriptResult(script_name="demo.yaml", start_time=100.0, end_time=102.5)
    result.steps = [
        StepResult(status=StepStatus.PASSED),
        StepResult(status=StepStatus.PASSED),
        StepResult(status=StepStatus.FAILED),
        StepResult(status=StepStatus.ERROR),
        StepResult(status=StepStatus.SKIPPED),
    ]

    assert result.duration_s == 2.5
    assert result.total == 5
    assert result.passed == 2
    assert result.failed == 1
    assert result.errors == 1
    assert result.skipped == 1


def test_test_result_duration_zero_without_timestamps():
    assert ScriptResult().duration_s == 0.0


def test_test_result_summary_passed_and_failed_variants():
    passed = ScriptResult(script_name="ok.yaml", status=ScriptStatus.PASSED,
                        start_time=1.0, end_time=2.0)
    text = passed.summary()
    assert "✅ ok.yaml" in text
    assert "Status: PASSED" in text
    assert "Duration: 1.00s" in text
    assert "Steps: 0 total" in text
    assert "Error:" not in text

    failed = ScriptResult(script_name="bad.yaml", status=ScriptStatus.FAILED,
                        error_message="步骤 2 断言失败")
    text = failed.summary()
    assert "❌ bad.yaml" in text
    assert "Error: 步骤 2 断言失败" in text


# ── TestContext ─────────────────────────────────────────────────

def test_context_defaults():
    ctx = ScriptContext()

    assert ctx.connected is False
    assert ctx.running is False
    assert ctx.client_count == 0
    assert ctx.role == "master"
    assert ctx.engine is None
    assert ctx.rx_frames == [] and ctx.tx_frames == []
    assert ctx.received_asdus == []
    assert ctx.variables == {}


def test_frame_helpers_record_timestamp_and_data():
    ctx = ScriptContext()
    before = time.time()

    ctx.add_rx_frame(b"\x68\x04\x0b\x00\x00\x00")
    ctx.add_tx_frame(b"\x68\x04\x07\x00\x00\x00")
    ctx.add_event("connected", {"addr": "127.0.0.1"})

    assert len(ctx.rx_frames) == 1 and len(ctx.tx_frames) == 1
    assert ctx.rx_frames[0][1] == b"\x68\x04\x0b\x00\x00\x00"
    assert ctx.rx_frames[0][0] >= before
    assert ctx.events[0][1] == "connected"
    assert ctx.events[0][2] == {"addr": "127.0.0.1"}


def test_variables_get_set_with_default():
    ctx = ScriptContext()

    assert ctx.get_variable("missing") is None
    assert ctx.get_variable("missing", 7) == 7

    ctx.set_variable("ioa", 100)
    assert ctx.get_variable("ioa") == 100


def test_reset_clears_runtime_state_but_keeps_variables_and_engine():
    ctx = ScriptContext()
    ctx.connected = True
    ctx.running = True
    ctx.client_count = 3
    ctx.add_rx_frame(b"\x01")
    ctx.add_tx_frame(b"\x02")
    ctx.received_asdus.append({"type_id": 1})
    ctx.yx_data[1] = True
    ctx.yc_data[2] = 1.0
    ctx.ym_data[3] = 5
    ctx.add_event("x", {})
    ctx.set_variable("keep", 42)
    ctx.engine = object()

    ctx.reset()

    assert ctx.connected is False
    assert ctx.running is False
    assert ctx.client_count == 0
    assert ctx.rx_frames == [] and ctx.tx_frames == []
    assert ctx.received_asdus == []
    assert ctx.yx_data == {} and ctx.yc_data == {} and ctx.ym_data == {}
    assert ctx.events == []
    assert ctx.get_variable("keep") == 42      # 变量与引擎引用被保留
    assert ctx.engine is not None


# ── 按帧型计数 ───────────────────────────────────────────────────

I_FRAME = b"\x68\x0e\x00\x00\x00\x00" + b"\x00" * 8   # 控制域 bit0=0
S_FRAME = b"\x68\x04\x01\x00\x00\x00"                 # bit0=1, bits1-2=01
U_FRAME = b"\x68\x04\x0b\x00\x00\x00"                 # bit0=1, bits1-2=11
SHORT = b"\x68\x04"                                   # < 6 字节，无法判定


def test_get_rx_frame_count_by_type():
    ctx = ScriptContext()
    for frame in (I_FRAME, I_FRAME, S_FRAME, U_FRAME, SHORT):
        ctx.add_rx_frame(frame)

    assert ctx.get_rx_frame_count() == 5           # None = 全部
    assert ctx.get_rx_frame_count("I") == 2
    assert ctx.get_rx_frame_count("S") == 1
    assert ctx.get_rx_frame_count("U") == 1        # 过短帧不计入任何帧型


def test_get_tx_frame_count_by_type():
    ctx = ScriptContext()
    for frame in (I_FRAME, S_FRAME, U_FRAME):
        ctx.add_tx_frame(frame)

    assert ctx.get_tx_frame_count() == 3
    assert ctx.get_tx_frame_count("I") == 1
    assert ctx.get_tx_frame_count("S") == 1
    assert ctx.get_tx_frame_count("U") == 1


def test_frame_count_on_empty_buffers():
    ctx = ScriptContext()
    assert ctx.get_rx_frame_count("I") == 0
    assert ctx.get_tx_frame_count("U") == 0
