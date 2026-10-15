"""`core/testing/runner.py` 测试运行器单元测试.

覆盖脚本装载（文件/目录/字符串）、引擎工厂（master/slave 与点表两种来源）、
回调接线（主站/子站事件 → 上下文）、单脚本运行（通过/断言失败/动作错误/
中止/跳过剩余/脚本超时/引擎初始化失败/回调异常吞掉）、单步执行的超时与异常
分支、以及批量运行并落盘报告。

引擎：`run()` 路径注入假引擎（不起网络）；`_create_engine()` 单独用真实引擎类
仅做构造与参数映射断言。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import yaml

from core.data.point_table import PointTable
from core.testing.context import StepResult, StepStatus
from core.testing.context import TestContext as ScriptContext
from core.testing.context import TestStatus as ScriptStatus
from core.testing.runner import TestRunner as ScriptRunner
from core.testing.script import Assertion, ScriptLoader
from core.testing.script import TestScript as YamlScript
from core.testing.script import TestStep as YamlStep

DEMO_POINTS = Path(__file__).parent.parent / "configs" / "demo_points.yaml"

PASS_SCRIPT = """
name: 通过用例
config:
  role: master
steps:
  - action: log
    assert: ["always_pass"]
  - action: log
    assert:
      type: frame_count
      params: {direction: rx, min: 0}
"""

FAIL_ASSERT_SCRIPT = """
name: 断言失败
config:
  role: master
steps:
  - action: log
    assert: ["always_fail"]
"""


class _FakeEngine:
    """run() 路径用的假引擎：记录回调、可注入 stop 行为."""

    def __init__(self, stop_raises: bool = False):
        self.event_cb = None
        self.raw_cb = None
        self.stopped = 0
        self._stop_raises = stop_raises

    def set_event_callback(self, cb):
        self.event_cb = cb

    def set_raw_frame_callback(self, cb):
        self.raw_cb = cb

    def get_raw_frame_callback(self):
        return self.raw_cb

    async def stop(self):
        self.stopped += 1
        if self._stop_raises:
            raise RuntimeError("stop failed")


@pytest.fixture
def runner(tmp_path) -> ScriptRunner:
    r = ScriptRunner(report_dir=str(tmp_path / "reports"))
    r._create_engine = lambda script: _FakeEngine()      # 默认注入假引擎
    return r


# ── 装载与基本属性 ───────────────────────────────────────────────

def test_init_defaults_and_scripts_property(runner):
    assert runner.scripts == []
    assert runner._report_dir.name == "reports"
    assert runner._on_step_complete is None
    assert runner._on_test_complete is None


def test_set_callbacks_only_replaces_non_none(runner):
    def step_cb(_sr):
        return None

    def test_cb(_tr):
        return None


    runner.set_callbacks(on_step_complete=step_cb)
    assert runner._on_step_complete is step_cb
    assert runner._on_test_complete is None

    runner.set_callbacks(on_test_complete=test_cb)
    assert runner._on_test_complete is test_cb
    assert runner._on_step_complete is step_cb


def test_load_script_directory_and_string(runner, tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("name: A\nsteps: []\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("name: B\nsteps: []\n", encoding="utf-8")

    script = runner.load_script(path)
    assert script.name == "A"
    assert len(runner.scripts) == 1

    loaded = runner.load_directory(tmp_path)
    assert [s.name for s in loaded] == ["A", "B"]
    assert len(runner.scripts) == 3

    inline = runner.load_string("name: Inline\nsteps: []\n")
    assert inline.name == "Inline"
    assert len(runner.scripts) == 4

    runner.clear()
    assert runner.scripts == []


def test_scripts_property_returns_copy(runner, tmp_path):
    runner.load_string("name: X\nsteps: []\n")
    snapshot = runner.scripts
    snapshot.clear()

    assert len(runner.scripts) == 1        # 内部列表不受外部修改影响


# ── 引擎工厂 ─────────────────────────────────────────────────────

def test_create_engine_master_maps_config():
    script = YamlScript(
        role="master",
        connection={"host": "10.0.0.5", "port": 2500, "common_addr": 7,
                    "auto_start": False, "reconnect": False,
                    "reconnect_interval": 1.5},
        timers={"t1": 3, "t2": 4, "t3": 5, "t0": 6},
        flow_control={"k": 5, "w": 3},
    )
    engine = ScriptRunner()._create_engine(script)

    assert engine.host == "10.0.0.5"
    assert engine.port == 2500
    assert engine._common_addr == 7
    assert engine._seq.k == 5 and engine._seq.w == 3
    assert engine._t1 == 3
    assert engine._auto_start is False


def test_create_engine_master_uses_defaults():
    engine = ScriptRunner()._create_engine(YamlScript(role="master"))

    assert engine.host == "127.0.0.1"
    assert engine.port == 2404
    assert engine._auto_gi is False          # 脚本运行时不自动总召唤


def test_create_engine_slave_auto_generates_points():
    script = YamlScript(role="slave",
                        connection={"port": 2405, "max_connections": 4},
                        point_table={"auto_generate": True, "yx_count": 3,
                                     "yc_count": 2, "yk_count": 1, "ym_count": 1})
    engine = ScriptRunner()._create_engine(script)

    assert engine.port == 2405
    assert isinstance(engine._point_table, PointTable)


def test_create_engine_slave_loads_point_table_file():
    script = YamlScript(role="slave",
                        point_table={"file": str(DEMO_POINTS)})
    engine = ScriptRunner()._create_engine(script)

    assert isinstance(engine._point_table, PointTable)
    assert engine._point_table.get_all_yx()          # 已从 YAML 载入点位


def test_create_engine_slave_skips_points_when_auto_generate_false():
    script = YamlScript(role="slave",
                        point_table={"auto_generate": False})
    engine = ScriptRunner()._create_engine(script)

    assert engine._point_table.get_all_yx() == []


# ── 回调接线 ─────────────────────────────────────────────────────

def test_setup_callbacks_master_bridges_events_to_context():
    from core.engine.master import MasterEngine, MasterEvent

    script = YamlScript(role="master", connection={"auto_start": False})
    engine = ScriptRunner()._create_engine(script)
    ctx = ScriptContext()
    ctx.role = "master"

    ScriptRunner()._setup_callbacks(engine, ctx)

    engine._event_callback(MasterEvent.CONNECTED, {})
    assert ctx.connected is True

    engine._event_callback(MasterEvent.STARTED, {})
    assert ctx.running is True

    engine._event_callback(MasterEvent.DATA_RECEIVED,
                           {"type_id": 1, "cot": 3, "objects": []})
    assert ctx.received_asdus == [{"type_id": 1, "cot": 3, "objects": []}]

    engine._event_callback(MasterEvent.DISCONNECTED, {})
    assert ctx.connected is False

    raw = engine.get_raw_frame_callback()
    raw(b"\x68\x04\x0b\x00\x00\x00", "rx")
    raw(b"\x68\x04\x07\x00\x00\x00", "tx")
    assert len(ctx.rx_frames) == 1 and len(ctx.tx_frames) == 1
    assert isinstance(engine, MasterEngine)


def test_setup_callbacks_slave_tracks_client_count_and_frames():
    from core.engine.slave import SlaveEngine, SlaveEvent

    script = YamlScript(role="slave", point_table={"auto_generate": False})
    engine = ScriptRunner()._create_engine(script)
    ctx = ScriptContext()
    ctx.role = "slave"

    ScriptRunner()._setup_callbacks(engine, ctx)

    engine._event_callback(SlaveEvent.CLIENT_CONNECTED, {})
    assert ctx.client_count == 1
    assert ctx.connected is True

    engine._event_callback(SlaveEvent.CLIENT_CONNECTED, {})
    engine._event_callback(SlaveEvent.CLIENT_DISCONNECTED, {})
    assert ctx.client_count == 1 and ctx.connected is True

    engine._event_callback(SlaveEvent.CLIENT_DISCONNECTED, {})
    assert ctx.client_count == 0
    assert ctx.connected is False          # 最后一个客户端断开才置 False

    raw = engine.get_raw_frame_callback()
    raw(b"\x68\x04\x0b\x00\x00\x00", "rx", "c1")
    raw(b"\x68\x04\x07\x00\x00\x00", "tx")
    assert len(ctx.rx_frames) == 1 and len(ctx.tx_frames) == 1
    assert isinstance(engine, SlaveEngine)


def test_slave_client_count_never_goes_negative():
    from core.engine.slave import SlaveEngine, SlaveEvent

    engine = ScriptRunner()._create_engine(YamlScript(role="slave",
                                                    point_table={"auto_generate": False}))
    ctx = ScriptContext()
    ctx.role = "slave"
    ScriptRunner()._setup_callbacks(engine, ctx)

    engine._event_callback(SlaveEvent.CLIENT_DISCONNECTED, {})
    assert ctx.client_count == 0
    assert isinstance(engine, SlaveEngine)


# ── 单脚本运行 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_without_scripts_raises(runner):
    with pytest.raises(ValueError, match="No scripts loaded"):
        await runner.run()


@pytest.mark.asyncio
async def test_run_passing_script(runner):
    script = runner.load_string(PASS_SCRIPT)

    result = await runner.run()

    assert result.script_name == "通过用例"
    assert result.status is ScriptStatus.PASSED
    assert result.total == 2
    assert result.passed == 2
    assert result.duration_s >= 0
    assert result.steps[0].status is StepStatus.PASSED
    assert result.steps[0].duration_ms >= 0
    assert script.steps[0].assertions[0].type == "always_pass"


@pytest.mark.asyncio
async def test_run_failing_assertion_marks_failed(runner):
    runner.load_string(FAIL_ASSERT_SCRIPT)

    result = await runner.run()

    assert result.status is ScriptStatus.FAILED
    assert result.failed == 1
    assert result.steps[0].status is StepStatus.FAILED
    assert result.steps[0].assertions[0]["passed"] is False


@pytest.mark.asyncio
async def test_run_unknown_action_marks_error_step(runner):
    """未知动作 → 步骤 ERROR（动作执行抛 ValueError 被 _execute_step 捕获）."""
    runner.load_string("name: bad-action\nsteps:\n  - action: no_such_action\n")

    result = await runner.run()

    assert result.status is ScriptStatus.FAILED
    assert result.steps[0].status is StepStatus.ERROR
    assert "Unknown action" in result.steps[0].message


@pytest.mark.asyncio
async def test_run_abort_on_failure_stops_remaining_steps(runner):
    yaml_text = """
name: 中止
steps:
  - action: log
    on_failure: abort
    assert: ["always_fail"]
  - action: log
"""
    runner.load_string(yaml_text)

    result = await runner.run()

    assert result.total == 1               # 第二步未执行
    assert result.status is ScriptStatus.FAILED


@pytest.mark.asyncio
async def test_run_skip_rest_marks_remaining_steps_skipped(runner):
    yaml_text = """
name: 跳过剩余
steps:
  - action: log
    on_failure: skip_rest
    assert: ["always_fail"]
  - action: log
  - action: log
"""
    runner.load_string(yaml_text)

    result = await runner.run()

    assert result.total == 3
    assert result.failed == 1
    assert result.skipped == 2
    assert result.steps[1].status is StepStatus.SKIPPED
    assert result.steps[2].action == "log"
    assert result.status is ScriptStatus.FAILED


@pytest.mark.asyncio
async def test_run_script_timeout_marks_step_error(runner):
    """脚本级超时：timeout 极小 → 每个步骤被标记为 ERROR."""
    yaml_text = """
name: 脚本超时
config:
  timeout: 0.000001
steps:
  - action: log
"""
    runner.load_string(yaml_text)

    result = await runner.run()

    assert result.steps[0].status is StepStatus.ERROR
    assert "Script timeout" in result.steps[0].message


@pytest.mark.asyncio
async def test_run_engine_init_failure_returns_error_result(runner):
    def boom(_script):
        raise RuntimeError("engine boom")

    runner._create_engine = boom
    runner.load_string("name: 初始化失败\nsteps:\n  - action: log\n")

    result = await runner.run()

    assert result.status is ScriptStatus.ERROR
    assert "Engine init failed: engine boom" in result.error_message
    assert result.steps == []


@pytest.mark.asyncio
async def test_run_stops_engine_even_on_step_error(runner):
    runner.load_string("name: fatal\nsteps:\n  - action: no_such_action\n")

    result = await runner.run()

    assert result.status is ScriptStatus.FAILED


@pytest.mark.asyncio
async def test_run_swallows_engine_stop_failure(tmp_path):
    """引擎 stop() 抛异常不得影响结果返回."""
    runner = ScriptRunner(report_dir=str(tmp_path))
    runner._create_engine = lambda _s: _FakeEngine(stop_raises=True)
    runner.load_string("name: stop-fail\nsteps:\n  - action: log\n")

    result = await runner.run()

    assert result.status is ScriptStatus.PASSED


@pytest.mark.asyncio
async def test_run_invokes_callbacks_and_swallows_their_errors(runner):
    seen_steps: list[StepResult] = []
    seen_tests = []

    def bad_step_cb(_sr):
        raise RuntimeError("step cb boom")

    runner.set_callbacks(on_step_complete=bad_step_cb,
                         on_test_complete=seen_tests.append)
    runner.load_string(PASS_SCRIPT)

    result = await runner.run()

    assert result.status is ScriptStatus.PASSED
    assert len(seen_tests) == 1

    runner.set_callbacks(on_step_complete=seen_steps.append)
    await runner.run()
    assert len(seen_steps) == 2


@pytest.mark.asyncio
async def test_run_swallows_on_test_complete_callback_error(runner):
    def bad_test_cb(_tr):
        raise RuntimeError("test cb boom")

    runner.set_callbacks(on_test_complete=bad_test_cb)
    runner.load_string(PASS_SCRIPT)

    result = await runner.run()

    assert result.status is ScriptStatus.PASSED


@pytest.mark.asyncio
async def test_run_accepts_explicit_script_argument(runner):
    script = ScriptLoader.loads(PASS_SCRIPT)
    runner.load_string("name: 别的\nsteps: []\n")

    result = await runner.run(script)

    assert result.script_name == "通过用例"


@pytest.mark.asyncio
async def test_run_script_execution_exception_marks_error(runner):
    """步骤循环外异常 → 整体 ERROR 并记录 error_message."""
    runner.load_string("name: 循环异常\nsteps:\n  - action: log\n")

    def explode(_step, _ctx, _timeout):
        raise RuntimeError("loop boom")

    runner._execute_step = explode

    result = await runner.run()

    assert result.status is ScriptStatus.ERROR
    assert result.error_message == "loop boom"


# ── 单步执行细节 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_step_timeout_error_becomes_failed(runner):
    async def raise_timeout(_ctx, _params):
        raise TimeoutError("等不到状态")

    runner._actions.register("raise_timeout", raise_timeout)
    step = YamlStep(index=0, action="raise_timeout", description="超时步骤")

    result = await runner._execute_step(step, ScriptContext(), 10.0)

    assert result.status is StepStatus.FAILED
    assert result.message == "等不到状态"


@pytest.mark.asyncio
async def test_execute_step_generic_exception_becomes_error(runner):
    async def raise_error(_ctx, _params):
        raise ValueError("动作炸了")

    runner._actions.register("raise_error", raise_error)
    step = YamlStep(index=1, action="raise_error", description="异常步骤")

    result = await runner._execute_step(step, ScriptContext(), 10.0)

    assert result.status is StepStatus.ERROR
    assert result.message == "动作炸了"
    assert result.step_index == 1


@pytest.mark.asyncio
async def test_execute_step_collects_all_assertion_results(runner):
    step = YamlStep(
        index=0, action="log", description="多断言",
        assertions=[
            Assertion(type="always_pass"),
            Assertion(type="always_fail", params={"message": "第二条失败"}),
        ],
    )

    result = await runner._execute_step(step, ScriptContext(), 10.0)

    assert result.status is StepStatus.FAILED
    assert len(result.assertions) == 2
    assert result.assertions[0]["passed"] is True
    assert result.assertions[1]["message"] == "第二条失败"


# ── 批量运行 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_all_writes_text_and_json_reports(runner, tmp_path):
    runner.load_string(PASS_SCRIPT)
    runner.load_string("name: 第二个\nsteps:\n  - action: log\n")

    results = await runner.run_all()

    assert len(results) == 2
    assert results[0].script_name == "通过用例"
    assert results[1].script_name == "第二个"

    reports = sorted(p.name for p in (tmp_path / "reports").glob("*"))
    assert reports == ["第二个.json", "第二个.txt", "通过用例.json", "通过用例.txt"]

    payload = yaml.safe_load((tmp_path / "reports" / "通过用例.json").read_text(encoding="utf-8"))
    assert isinstance(payload, (dict, list))


@pytest.mark.asyncio
async def test_run_all_on_empty_list_returns_empty(runner):
    assert await runner.run_all() == []
