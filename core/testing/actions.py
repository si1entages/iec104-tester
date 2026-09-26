"""内置动作注册表 — 定义测试脚本可调用的所有动作."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from .context import TestContext

logger = logging.getLogger("iec104.testing.actions")


class ActionRegistry:
    """动作注册表.

    每个动作是一个 async 函数: async def action(ctx: TestContext, params: dict) -> dict
    返回值包含执行结果信息。
    """

    def __init__(self):
        self._actions: dict[str, Callable] = {}
        self._register_builtins()

    def register(self, name: str, handler: Callable) -> None:
        self._actions[name] = handler

    def get(self, name: str) -> Callable | None:
        return self._actions.get(name)

    def list_actions(self) -> list[str]:
        return sorted(self._actions.keys())

    async def execute(self, name: str, ctx: TestContext, params: dict) -> dict:
        handler = self._actions.get(name)
        if not handler:
            raise ValueError(f"Unknown action: {name}. Available: {self.list_actions()}")
        return await handler(ctx, params)

    def _register_builtins(self) -> None:
        """注册所有内置动作."""
        self.register("connect", action_connect)
        self.register("disconnect", action_disconnect)
        self.register("wait", action_wait)
        self.register("send_startdt", action_send_startdt)
        self.register("send_stopdt", action_send_stopdt)
        self.register("general_interrogation", action_general_interrogation)
        self.register("counter_interrogation", action_counter_interrogation)
        self.register("clock_sync", action_clock_sync)
        self.register("reset_process", action_reset_process)
        self.register("send_test_command", action_send_test_command)
        self.register("single_command", action_single_command)
        self.register("double_command", action_double_command)
        self.register("setpoint_normalized", action_setpoint_normalized)
        self.register("setpoint_shortfloat", action_setpoint_shortfloat)
        self.register("wait_state", action_wait_state)
        self.register("wait_frames", action_wait_frames)
        self.register("wait_asdu", action_wait_asdu)
        self.register("set_variable", action_set_variable)
        self.register("clear_buffers", action_clear_buffers)
        self.register("log", action_log)
        self.register("slave_set_yx", action_slave_set_yx)
        self.register("slave_set_yc", action_slave_set_yc)
        self.register("slave_start_sim", action_slave_start_sim)
        self.register("slave_stop_sim", action_slave_stop_sim)
        self.register("apply_network_condition", action_apply_network_condition)
        self.register("remove_network_condition", action_remove_network_condition)
        self.register("network_disconnect", action_network_disconnect)


# ═══════════════════════════════════════════════════════════════════
#  连接管理
# ═══════════════════════════════════════════════════════════════════

async def action_connect(ctx: TestContext, params: dict) -> dict:
    """建立 TCP 连接."""
    engine = ctx.engine
    if not engine:
        raise RuntimeError("Engine not initialized")

    if ctx.role == "master":
        await engine.start()
        ctx.connected = True
        return {"message": f"Master connecting to {engine.host}:{engine.port}"}
    else:
        await engine.start()
        ctx.connected = True
        return {"message": f"Slave listening on port {engine.port}"}


async def action_disconnect(ctx: TestContext, params: dict) -> dict:
    """断开连接."""
    engine = ctx.engine
    if engine:
        await engine.stop()
    ctx.connected = False
    ctx.running = False
    return {"message": "Disconnected"}


# ═══════════════════════════════════════════════════════════════════
#  协议命令
# ═══════════════════════════════════════════════════════════════════

async def action_send_startdt(ctx: TestContext, params: dict) -> dict:
    """发送 STARTDT."""
    await ctx.engine.send_startdt()
    return {"message": "STARTDT ACT sent"}


async def action_send_stopdt(ctx: TestContext, params: dict) -> dict:
    """发送 STOPDT."""
    await ctx.engine.send_stopdt()
    return {"message": "STOPDT ACT sent"}


async def action_general_interrogation(ctx: TestContext, params: dict) -> dict:
    """总召唤."""
    qoi = params.get("qoi", 20)
    await ctx.engine.general_interrogation(qoi=qoi)
    return {"message": f"General Interrogation sent (QOI={qoi})"}


async def action_counter_interrogation(ctx: TestContext, params: dict) -> dict:
    """累计量召唤."""
    qcc = params.get("qcc", 0)
    await ctx.engine.counter_interrogation(qcc=qcc)
    return {"message": f"Counter Interrogation sent (QCC={qcc})"}


async def action_clock_sync(ctx: TestContext, params: dict) -> dict:
    """时钟同步."""
    await ctx.engine.clock_sync()
    return {"message": "Clock Sync sent"}


async def action_reset_process(ctx: TestContext, params: dict) -> dict:
    """复位进程."""
    qrp = params.get("qrp", 1)
    await ctx.engine.reset_process(qrp=qrp)
    return {"message": f"Reset Process sent (QRP={qrp})"}


async def action_send_test_command(ctx: TestContext, params: dict) -> dict:
    """测试命令."""
    await ctx.engine.send_test_command()
    return {"message": "Test Command sent"}


async def action_single_command(ctx: TestContext, params: dict) -> dict:
    """单命令."""
    ioa = params["ioa"]
    state = params.get("state", True)
    select = params.get("select", False)
    qu = params.get("qu", 0)
    await ctx.engine.single_command(ioa, state, select=select, qu=qu)
    action = "SELECT" if select else "EXECUTE"
    return {"message": f"Single Command: IOA={ioa} {action} state={state}"}


async def action_double_command(ctx: TestContext, params: dict) -> dict:
    """双命令."""
    ioa = params["ioa"]
    state = params.get("state", 1)
    select = params.get("select", False)
    await ctx.engine.double_command(ioa, state, select=select)
    return {"message": f"Double Command: IOA={ioa} state={state}"}


async def action_setpoint_normalized(ctx: TestContext, params: dict) -> dict:
    """归一化设点."""
    ioa = params["ioa"]
    value = params["value"]
    select = params.get("select", False)
    await ctx.engine.setpoint_normalized(ioa, value, select=select)
    return {"message": f"Setpoint Normalized: IOA={ioa} value={value}"}


async def action_setpoint_shortfloat(ctx: TestContext, params: dict) -> dict:
    """短浮点设点."""
    ioa = params["ioa"]
    value = params["value"]
    select = params.get("select", False)
    await ctx.engine.setpoint_shortfloat(ioa, value, select=select)
    return {"message": f"Setpoint ShortFloat: IOA={ioa} value={value}"}


# ═══════════════════════════════════════════════════════════════════
#  等待与同步
# ═══════════════════════════════════════════════════════════════════

async def action_wait(ctx: TestContext, params: dict) -> dict:
    """等待指定秒数."""
    seconds = params.get("seconds", 1.0)
    await asyncio.sleep(seconds)
    return {"message": f"Waited {seconds}s"}


async def action_wait_state(ctx: TestContext, params: dict) -> dict:
    """等待引擎达到指定状态."""
    target = params.get("state", "running")
    timeout = params.get("timeout", 10.0)
    poll_interval = params.get("poll_interval", 0.2)

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if ctx.role == "master":
            if target == "running" and ctx.engine.is_running:
                ctx.running = True
                return {"message": f"State reached: {target}"}
            if target == "connected" and ctx.connected:
                return {"message": f"State reached: {target}"}
        else:
            if target == "listening" and ctx.engine.is_running:
                return {"message": f"State reached: {target}"}
        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"Timeout waiting for state '{target}' after {timeout}s")


async def action_wait_frames(ctx: TestContext, params: dict) -> dict:
    """等待收到指定数量的帧."""
    direction = params.get("direction", "rx")
    count = params.get("count", 1)
    frame_type = params.get("frame_type")
    timeout = params.get("timeout", 10.0)
    poll_interval = params.get("poll_interval", 0.1)

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if direction == "rx":
            actual = ctx.get_rx_frame_count(frame_type)
        else:
            actual = ctx.get_tx_frame_count(frame_type)
        if actual >= count:
            return {"message": f"Got {actual} {direction.upper()} frames (>= {count})"}
        await asyncio.sleep(poll_interval)

    actual = ctx.get_rx_frame_count(frame_type) if direction == "rx" else ctx.get_tx_frame_count(frame_type)
    raise TimeoutError(
        f"Timeout waiting for {count} {direction.upper()} frames. "
        f"Got {actual} after {timeout}s"
    )


async def action_wait_asdu(ctx: TestContext, params: dict) -> dict:
    """等待收到指定类型的 ASDU."""
    type_id = params.get("type_id")
    cot = params.get("cot")
    timeout = params.get("timeout", 10.0)
    count = params.get("count", 1)
    poll_interval = params.get("poll_interval", 0.1)


    start = time.monotonic()
    matched = 0
    while time.monotonic() - start < timeout:
        for asdu_info in ctx.received_asdus:
            tid_match = (type_id is None or asdu_info.get("type_id") == type_id)
            cot_match = (cot is None or asdu_info.get("cot") == cot)
            if tid_match and cot_match:
                matched += 1
        if matched >= count:
            return {
                "message": f"Received {matched} ASDU(s) type={type_id} cot={cot}",
                "matched": matched,
            }
        await asyncio.sleep(poll_interval)

    raise TimeoutError(
        f"Timeout waiting for ASDU type={type_id} cot={cot}. "
        f"Got {matched}/{count} after {timeout}s"
    )


# ═══════════════════════════════════════════════════════════════════
#  子站操作
# ═══════════════════════════════════════════════════════════════════

async def action_slave_set_yx(ctx: TestContext, params: dict) -> dict:
    """子站设置遥信值."""
    ioa = params["ioa"]
    value = params["value"]
    quality = params.get("quality", 0)
    await ctx.engine.send_spontaneous_yx(ioa, value, quality)
    return {"message": f"YX set: IOA={ioa} value={value}"}


async def action_slave_set_yc(ctx: TestContext, params: dict) -> dict:
    """子站设置遥测值."""
    ioa = params["ioa"]
    value = params["value"]
    quality = params.get("quality", 0)
    await ctx.engine.send_spontaneous_yc(ioa, value, quality)
    return {"message": f"YC set: IOA={ioa} value={value}"}


async def action_slave_start_sim(ctx: TestContext, params: dict) -> dict:
    """子站启动数据模拟."""
    yx_interval = params.get("yx_interval", 5.0)
    yc_interval = params.get("yc_interval", 2.0)
    yx_change_rate = params.get("yx_change_rate", 0.1)
    yc_change_range = params.get("yc_change_range", 0.05)
    await ctx.engine.start_simulation(
        yx_interval=yx_interval,
        yc_interval=yc_interval,
        yx_change_rate=yx_change_rate,
        yc_change_range=yc_change_range,
    )
    return {"message": "Simulation started"}


async def action_slave_stop_sim(ctx: TestContext, params: dict) -> dict:
    """子站停止数据模拟."""
    await ctx.engine.stop_simulation()
    return {"message": "Simulation stopped"}


# ═══════════════════════════════════════════════════════════════════
#  辅助动作
# ═══════════════════════════════════════════════════════════════════

async def action_set_variable(ctx: TestContext, params: dict) -> dict:
    """设置变量."""
    name = params["name"]
    value = params["value"]
    ctx.set_variable(name, value)
    return {"message": f"Variable set: {name} = {value}"}


async def action_clear_buffers(ctx: TestContext, params: dict) -> dict:
    """清空帧缓冲."""
    ctx.rx_frames.clear()
    ctx.tx_frames.clear()
    ctx.received_asdus.clear()
    return {"message": "Buffers cleared"}


async def action_log(ctx: TestContext, params: dict) -> dict:
    """输出日志."""
    message = params.get("message", "")
    level = params.get("level", "INFO")
    getattr(logger, level.lower(), logger.info)(f"[SCRIPT] {message}")
    return {"message": message}


# ═══════════════════════════════════════════════════════════════════
#  网络异常模拟
# ═══════════════════════════════════════════════════════════════════

async def action_apply_network_condition(ctx: TestContext, params: dict) -> dict:
    """应用网络异常条件.

    params:
        preset: 预设名称 (可选)
        loss_rate: 丢包率
        delay_ms: 延迟
        delay_variance_ms: 抖动
        corrupt_rate: 损坏率
        duplicate_rate: 重复率
        reorder_rate: 乱序率
        disconnect_rate: 断线率
        disconnect_duration_s: 断线时长
        bandwidth_bps: 带宽限制
        direction: "rx"/"tx"/"both"
    """
    from ..simulation import SimulationManager

    preset = params.get("preset")
    sim = SimulationManager()

    if preset:
        sim.apply_preset(preset)
    else:
        sim.apply_condition(
            loss_rate=params.get("loss_rate", 0),
            delay_ms=params.get("delay_ms", 0),
            delay_variance_ms=params.get("delay_variance_ms", 0),
            corrupt_rate=params.get("corrupt_rate", 0),
            duplicate_rate=params.get("duplicate_rate", 0),
            reorder_rate=params.get("reorder_rate", 0),
            disconnect_rate=params.get("disconnect_rate", 0),
            disconnect_duration_s=params.get("disconnect_duration_s", 3.0),
            bandwidth_bps=params.get("bandwidth_bps", 0),
            direction=params.get("direction", "both"),
        )

    sim.install(ctx.engine)
    ctx.set_variable("_sim_manager", sim)
    return {"message": f"Network condition applied: {sim.condition.describe()}"}


async def action_remove_network_condition(ctx: TestContext, params: dict) -> dict:
    """移除网络异常条件."""
    sim = ctx.get_variable("_sim_manager")
    if sim:
        stats = sim.stats()
        sim.remove()
        return {"message": f"Network condition removed. Stats: {stats}"}
    return {"message": "No active network condition"}


async def action_network_disconnect(ctx: TestContext, params: dict) -> dict:
    """手动触发断线.

    params:
        duration: 断线时长(秒)
    """
    duration = params.get("duration", 5.0)
    sim = ctx.get_variable("_sim_manager")
    if sim:
        sim.disconnect(duration)
        return {"message": f"Network disconnect for {duration}s"}
    return {"message": "No active simulation, skipping disconnect"}
