"""`core/testing/actions.py` 内置动作注册表单元测试.

覆盖注册/查询/执行分发与全部内置动作的成功路径、参数默认值与超时路径。

时序控制：等待类动作用「条件已满足立即返回」或 ``timeout=0``（循环体不执行）
来覆盖，**不产生真实等待**；`wait` 动作用 ``seconds=0``。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.simulation.manager import SimulationManager
from core.testing.actions import ActionRegistry
from core.testing.context import TestContext as ScriptContext

_ENGINE_ASYNC_METHODS = (
    "start", "stop", "send_startdt", "send_stopdt",
    "general_interrogation", "counter_interrogation", "clock_sync",
    "reset_process", "send_test_command", "single_command", "double_command",
    "setpoint_normalized", "setpoint_shortfloat",
    "send_spontaneous_yx", "send_spontaneous_yc",
    "start_simulation", "stop_simulation",
)


def _engine(**overrides) -> SimpleNamespace:
    """最小引擎替身：全部引擎方法为 AsyncMock，可注入状态字段."""
    eng = SimpleNamespace(host="127.0.0.1", port=2404, is_running=False)
    for name in _ENGINE_ASYNC_METHODS:
        setattr(eng, name, AsyncMock())
    eng._send_frame = AsyncMock()
    eng._on_frame_received = lambda frame: None
    eng._raw_cb = None
    eng.get_raw_frame_callback = lambda: eng._raw_cb

    def _set_raw(cb):
        eng._raw_cb = cb

    eng.set_raw_frame_callback = _set_raw
    for key, value in overrides.items():
        setattr(eng, key, value)
    return eng


@pytest.fixture
def registry() -> ActionRegistry:
    return ActionRegistry()


@pytest.fixture
def ctx() -> ScriptContext:
    c = ScriptContext()
    c.engine = _engine()
    return c


# ── 注册表 ───────────────────────────────────────────────────────

def test_registry_exposes_all_builtin_actions(registry):
    names = registry.list_actions()

    assert names == sorted(names)                     # 已排序
    for expected in ("connect", "disconnect", "wait", "send_startdt", "single_command",
                     "wait_state", "wait_frames", "wait_asdu", "set_variable",
                     "clear_buffers", "log", "slave_set_yx", "slave_set_yc",
                     "slave_start_sim", "slave_stop_sim", "apply_network_condition",
                     "remove_network_condition", "network_disconnect"):
        assert expected in names, expected


def test_registry_get_and_register_custom(registry, ctx):
    assert registry.get("connect") is not None
    assert registry.get("no-such-action") is None

    async def custom(_ctx, params):
        return {"message": "custom", "params": params}

    registry.register("custom_action", custom)
    assert registry.get("custom_action") is custom
    assert "custom_action" in registry.list_actions()


@pytest.mark.asyncio
async def test_registry_execute_dispatches_to_handler(registry, ctx):
    result = await registry.execute("log", ctx, {"message": "hello"})
    assert result == {"message": "hello"}


@pytest.mark.asyncio
async def test_registry_execute_unknown_action_raises_with_available_list(registry, ctx):
    with pytest.raises(ValueError, match="Unknown action: nope"):
        await registry.execute("nope", ctx, {})


# ── 连接管理 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_master_and_slave(registry, ctx):
    result = await registry.execute("connect", ctx, {})
    ctx.engine.start.assert_awaited_once()
    assert ctx.connected is True
    assert "Master connecting to 127.0.0.1:2404" in result["message"]

    ctx2 = ScriptContext()
    ctx2.engine = _engine()
    ctx2.role = "slave"
    result = await registry.execute("connect", ctx2, {})
    assert "Slave listening on port 2404" in result["message"]


@pytest.mark.asyncio
async def test_connect_without_engine_raises(registry):
    ctx = ScriptContext()        # engine 为 None
    with pytest.raises(RuntimeError, match="Engine not initialized"):
        await registry.execute("connect", ctx, {})


@pytest.mark.asyncio
async def test_disconnect_stops_engine_and_clears_flags(registry, ctx):
    ctx.connected = True
    ctx.running = True

    result = await registry.execute("disconnect", ctx, {})

    ctx.engine.stop.assert_awaited_once()
    assert ctx.connected is False
    assert ctx.running is False
    assert result["message"] == "Disconnected"


@pytest.mark.asyncio
async def test_disconnect_without_engine_is_safe(registry):
    ctx = ScriptContext()
    assert (await registry.execute("disconnect", ctx, {}))["message"] == "Disconnected"


# ── 协议命令 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("action,method,message_part", [
    ("send_startdt", "send_startdt", "STARTDT ACT sent"),
    ("send_stopdt", "send_stopdt", "STOPDT ACT sent"),
    ("clock_sync", "clock_sync", "Clock Sync sent"),
    ("send_test_command", "send_test_command", "Test Command sent"),
])
async def test_simple_command_actions(registry, ctx, action, method, message_part):
    result = await registry.execute(action, ctx, {})

    getattr(ctx.engine, method).assert_awaited_once()
    assert message_part in result["message"]


@pytest.mark.asyncio
async def test_general_and_counter_interrogation_defaults_and_params(registry, ctx):
    result = await registry.execute("general_interrogation", ctx, {})
    ctx.engine.general_interrogation.assert_awaited_once_with(qoi=20)
    assert "QOI=20" in result["message"]

    await registry.execute("general_interrogation", ctx, {"qoi": 1})
    ctx.engine.general_interrogation.assert_awaited_with(qoi=1)

    await registry.execute("counter_interrogation", ctx, {})
    ctx.engine.counter_interrogation.assert_awaited_once_with(qcc=0)

    result = await registry.execute("reset_process", ctx, {"qrp": 2})
    ctx.engine.reset_process.assert_awaited_once_with(qrp=2)
    assert "QRP=2" in result["message"]


@pytest.mark.asyncio
async def test_single_command_action_with_defaults_and_overrides(registry, ctx):
    result = await registry.execute("single_command", ctx, {"ioa": 100})
    ctx.engine.single_command.assert_awaited_once_with(100, True, select=False, qu=0)
    assert "EXECUTE" in result["message"]

    result = await registry.execute("single_command", ctx,
                                    {"ioa": 101, "state": False, "select": True, "qu": 3})
    ctx.engine.single_command.assert_awaited_with(101, False, select=True, qu=3)
    assert "SELECT" in result["message"]


@pytest.mark.asyncio
async def test_double_and_setpoint_actions(registry, ctx):
    await registry.execute("double_command", ctx, {"ioa": 200})
    ctx.engine.double_command.assert_awaited_once_with(200, 1, select=False)

    await registry.execute("setpoint_normalized", ctx,
                           {"ioa": 300, "value": 0.5, "select": True})
    ctx.engine.setpoint_normalized.assert_awaited_once_with(300, 0.5, select=True)

    await registry.execute("setpoint_shortfloat", ctx, {"ioa": 301, "value": 220.5})
    ctx.engine.setpoint_shortfloat.assert_awaited_once_with(301, 220.5, select=False)


# ── 等待与同步 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wait_action_with_zero_seconds(registry, ctx):
    result = await registry.execute("wait", ctx, {"seconds": 0})
    assert "Waited 0s" in result["message"]


@pytest.mark.asyncio
async def test_wait_state_master_running_and_connected(registry, ctx):
    ctx.engine.is_running = True
    result = await registry.execute("wait_state", ctx, {"state": "running"})
    assert "State reached: running" in result["message"]
    assert ctx.running is True

    ctx.connected = True
    result = await registry.execute("wait_state", ctx, {"state": "connected"})
    assert "State reached: connected" in result["message"]


@pytest.mark.asyncio
async def test_wait_state_slave_listening(registry, ctx):
    ctx.role = "slave"
    ctx.engine.is_running = True

    result = await registry.execute("wait_state", ctx, {"state": "listening"})
    assert "State reached: listening" in result["message"]


@pytest.mark.asyncio
async def test_wait_state_timeout_with_zero_timeout(registry, ctx):
    """timeout=0 → 轮询循环不执行，立即超时（不产生真实等待）."""
    with pytest.raises(TimeoutError, match="Timeout waiting for state 'running'"):
        await registry.execute("wait_state", ctx, {"state": "running", "timeout": 0})


@pytest.mark.asyncio
async def test_wait_frames_polls_then_succeeds(monkeypatch, registry, ctx):
    """wait_frames 的「先轮询再成功」路径（sleep 被替换为"让条件成立"，无真实等待）."""
    import core.testing.actions as actions_mod

    polls: list[float] = []

    async def fake_sleep(delay):
        polls.append(delay)
        ctx.add_rx_frame(b"\x68\x04\x0b\x00\x00\x00")

    # 只替换被测模块命名空间的 asyncio 绑定（actions 仅用 asyncio.sleep），
    # 避免篡改进程级 asyncio 模块污染同循环上的其它任务/用例。
    monkeypatch.setattr(actions_mod, "asyncio", SimpleNamespace(sleep=fake_sleep))

    result = await registry.execute(
        "wait_frames", ctx, {"direction": "rx", "count": 1, "timeout": 5}
    )

    assert "Got 1 RX frames" in result["message"]
    assert polls == [pytest.approx(0.1)]


@pytest.mark.asyncio
async def test_wait_asdu_polls_then_succeeds(monkeypatch, registry, ctx):
    """wait_asdu 的「先轮询再成功」路径."""
    import core.testing.actions as actions_mod

    polls: list[float] = []

    async def fake_sleep(delay):
        polls.append(delay)
        ctx.received_asdus.append({"type_id": 100, "cot": 7})

    # 只替换被测模块命名空间的 asyncio 绑定（actions 仅用 asyncio.sleep），
    # 避免篡改进程级 asyncio 模块污染同循环上的其它任务/用例。
    monkeypatch.setattr(actions_mod, "asyncio", SimpleNamespace(sleep=fake_sleep))

    result = await registry.execute("wait_asdu", ctx,
                                    {"type_id": 100, "cot": 7, "timeout": 5})

    assert result["matched"] == 1
    assert polls == [pytest.approx(0.1)]


@pytest.mark.asyncio
async def test_wait_state_polls_then_succeeds(monkeypatch, registry, ctx):
    """wait_state 的「先轮询再成功」路径."""
    import core.testing.actions as actions_mod

    polls: list[float] = []

    async def fake_sleep(delay):
        polls.append(delay)
        ctx.engine.is_running = True

    # 只替换被测模块命名空间的 asyncio 绑定（actions 仅用 asyncio.sleep），
    # 避免篡改进程级 asyncio 模块污染同循环上的其它任务/用例。
    monkeypatch.setattr(actions_mod, "asyncio", SimpleNamespace(sleep=fake_sleep))

    result = await registry.execute("wait_state", ctx, {"state": "running", "timeout": 5})

    assert "State reached: running" in result["message"]
    assert polls == [pytest.approx(0.2)]


@pytest.mark.asyncio
async def test_wait_frames_rx_and_tx(registry, ctx):
    ctx.add_rx_frame(b"\x68\x04\x0b\x00\x00\x00")

    result = await registry.execute("wait_frames", ctx, {"direction": "rx", "count": 1})
    assert "Got 1 RX frames" in result["message"]

    tx_result = await registry.execute("wait_frames", ctx, {"direction": "tx", "count": 0})
    assert "TX frames" in tx_result["message"]


@pytest.mark.asyncio
async def test_wait_frames_with_frame_type_filter(registry, ctx):
    ctx.add_rx_frame(b"\x68\x0e\x00\x00\x00\x00" + b"\x00" * 8)   # I 帧

    result = await registry.execute(
        "wait_frames", ctx, {"direction": "rx", "count": 1, "frame_type": "I"}
    )
    assert result["message"].startswith("Got 1 RX frames")


@pytest.mark.asyncio
async def test_wait_frames_timeout_reports_actual_count(registry, ctx):
    with pytest.raises(TimeoutError, match="Got 0 after 0s"):
        await registry.execute(
            "wait_frames", ctx, {"direction": "rx", "count": 3, "timeout": 0}
        )


@pytest.mark.asyncio
async def test_wait_asdu_matching_and_filters(registry, ctx):
    ctx.received_asdus.extend([
        {"type_id": 1, "cot": 3},
        {"type_id": 100, "cot": 7},
    ])

    result = await registry.execute("wait_asdu", ctx, {"type_id": 100, "cot": 7})
    assert result["matched"] == 1

    # 不限定 type_id/cot → 全部匹配
    result = await registry.execute("wait_asdu", ctx, {"count": 2})
    assert result["matched"] == 2


@pytest.mark.asyncio
async def test_wait_asdu_timeout(registry, ctx):
    ctx.received_asdus.append({"type_id": 1, "cot": 3})

    with pytest.raises(TimeoutError, match="Got 0/1 after 0s"):
        await registry.execute("wait_asdu", ctx, {"type_id": 99, "timeout": 0})


# ── 子站操作 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_set_yx_and_yc(registry, ctx):
    result = await registry.execute("slave_set_yx", ctx, {"ioa": 1, "value": True})
    ctx.engine.send_spontaneous_yx.assert_awaited_once_with(1, True, 0)
    assert "YX set: IOA=1" in result["message"]

    result = await registry.execute("slave_set_yc", ctx,
                                    {"ioa": 2, "value": 1.5, "quality": 4})
    ctx.engine.send_spontaneous_yc.assert_awaited_once_with(2, 1.5, 4)
    assert "YC set: IOA=2" in result["message"]


@pytest.mark.asyncio
async def test_slave_simulation_start_and_stop(registry, ctx):
    await registry.execute("slave_start_sim", ctx, {"yx_interval": 1.0, "yc_interval": 2.0})
    ctx.engine.start_simulation.assert_awaited_once_with(
        yx_interval=1.0, yc_interval=2.0, yx_change_rate=0.1, yc_change_range=0.05
    )

    result = await registry.execute("slave_stop_sim", ctx, {})
    ctx.engine.stop_simulation.assert_awaited_once()
    assert result["message"] == "Simulation stopped"


# ── 辅助动作 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_variable_and_clear_buffers(registry, ctx):
    result = await registry.execute("set_variable", ctx, {"name": "ioa", "value": 100})
    assert ctx.get_variable("ioa") == 100
    assert "Variable set: ioa = 100" in result["message"]

    ctx.add_rx_frame(b"\x01")
    ctx.add_tx_frame(b"\x02")
    ctx.received_asdus.append({"type_id": 1})

    result = await registry.execute("clear_buffers", ctx, {})

    assert ctx.rx_frames == [] and ctx.tx_frames == [] and ctx.received_asdus == []
    assert result["message"] == "Buffers cleared"


@pytest.mark.asyncio
async def test_log_action_with_levels(registry, ctx):
    assert (await registry.execute("log", ctx, {}))["message"] == ""

    for level in ("info", "debug", "warning", "error"):
        result = await registry.execute("log", ctx, {"message": "msg-" + level, "level": level.upper()})
        assert result["message"] == "msg-" + level


@pytest.mark.asyncio
async def test_apply_network_condition_with_preset(registry, ctx):
    result = await registry.execute("apply_network_condition", ctx, {"preset": "congested"})

    sim = ctx.get_variable("_sim_manager")
    assert isinstance(sim, SimulationManager)
    assert sim.condition.delay_ms == pytest.approx(100)
    assert "loss=" in result["message"]


@pytest.mark.asyncio
async def test_apply_network_condition_with_custom_params(registry, ctx):
    await registry.execute("apply_network_condition", ctx, {
        "loss_rate": 0.2, "delay_ms": 40, "delay_variance_ms": 5,
        "corrupt_rate": 0.01, "duplicate_rate": 0.02, "reorder_rate": 0.03,
        "disconnect_rate": 0.04, "disconnect_duration_s": 2.0,
        "bandwidth_bps": 4096, "direction": "rx",
    })

    cond = ctx.get_variable("_sim_manager").condition
    assert cond.loss_rate == pytest.approx(0.2)
    assert cond.delay_ms == pytest.approx(40)
    assert cond.bandwidth_bps == 4096
    assert cond.direction == "rx"


@pytest.mark.asyncio
async def test_remove_network_condition_with_and_without_manager(registry, ctx):
    assert (await registry.execute("remove_network_condition", ctx, {}))["message"] \
        == "No active network condition"

    await registry.execute("apply_network_condition", ctx, {"preset": "clean"})
    sim = ctx.get_variable("_sim_manager")
    result = await registry.execute("remove_network_condition", ctx, {})

    assert "Network condition removed" in result["message"]
    assert sim.proxy is None


@pytest.mark.asyncio
async def test_network_disconnect_with_and_without_manager(registry, ctx):
    assert "No active simulation" in (
        await registry.execute("network_disconnect", ctx, {})
    )["message"]

    await registry.execute("apply_network_condition", ctx, {"preset": "clean"})
    result = await registry.execute("network_disconnect", ctx, {"duration": 2.0})

    sim = ctx.get_variable("_sim_manager")
    assert "for 2.0s" in result["message"]
    assert sim.stats()["disconnects"] == 1
