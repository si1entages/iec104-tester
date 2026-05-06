"""测试运行器 — 执行测试脚本并收集结果."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Callable

from .context import TestContext, TestResult, StepResult, TestStatus, StepStatus
from .script import ScriptLoader, TestScript, TestStep
from .actions import ActionRegistry
from .assertions import AssertionEngine
from .report import ReportGenerator

logger = logging.getLogger("iec104.testing.runner")


class TestRunner:
    """测试运行器.

    用法:
        runner = TestRunner()
        runner.load_script("tests/scripts/basic_gi.yaml")
        result = await runner.run()

        # 或批量运行
        runner.load_directory("tests/scripts/")
        results = await runner.run_all()
    """

    def __init__(
        self,
        report_dir: str = "test_reports",
        on_step_complete: Optional[Callable[[StepResult], None]] = None,
        on_test_complete: Optional[Callable[[TestResult], None]] = None,
    ):
        self._scripts: list[TestScript] = []
        self._report_dir = Path(report_dir)
        self._actions = ActionRegistry()
        self._assertions = AssertionEngine()
        self._on_step_complete = on_step_complete
        self._on_test_complete = on_test_complete

    @property
    def scripts(self) -> list[TestScript]:
        return list(self._scripts)

    def load_script(self, path: str | Path) -> TestScript:
        """加载单个测试脚本."""
        script = ScriptLoader.load(path)
        self._scripts.append(script)
        return script

    def load_directory(self, directory: str | Path) -> list[TestScript]:
        """加载目录下所有测试脚本."""
        scripts = ScriptLoader.load_directory(directory)
        self._scripts.extend(scripts)
        return scripts

    def load_string(self, yaml_str: str, name: str = "<inline>") -> TestScript:
        """从 YAML 字符串加载."""
        script = ScriptLoader.loads(yaml_str, name)
        self._scripts.append(script)
        return script

    def clear(self) -> None:
        self._scripts.clear()

    async def run(self, script: TestScript = None) -> TestResult:
        """运行单个测试脚本.

        Args:
            script: 要运行的脚本。如果为 None，运行第一个已加载的脚本。
        """
        if script is None:
            if not self._scripts:
                raise ValueError("No scripts loaded")
            script = self._scripts[0]

        result = TestResult(
            script_name=script.name,
            script_path=script.path,
            status=TestStatus.RUNNING,
            start_time=time.time(),
        )

        # 创建上下文
        ctx = TestContext()
        ctx.role = script.role

        # 初始化引擎
        try:
            engine = self._create_engine(script)
            ctx.engine = engine
            self._setup_callbacks(engine, ctx)
        except Exception as e:
            result.status = TestStatus.ERROR
            result.error_message = f"Engine init failed: {e}"
            result.end_time = time.time()
            return result

        # 执行步骤
        try:
            for i, step in enumerate(script.steps):
                step_result = await self._execute_step(step, ctx, script.timeout)

                # 检查是否超时
                if result.start_time and script.timeout > 0:
                    elapsed = time.time() - result.start_time
                    if elapsed > script.timeout:
                        step_result.status = StepStatus.ERROR
                        step_result.message = f"Script timeout ({script.timeout}s) exceeded"

                result.steps.append(step_result)

                if self._on_step_complete:
                    try:
                        self._on_step_complete(step_result)
                    except Exception:
                        pass

                # 失败处理
                if step_result.status in (StepStatus.FAILED, StepStatus.ERROR):
                    if step.on_failure == "abort":
                        logger.warning(f"Step {i} failed, aborting script")
                        break
                    elif step.on_failure == "skip_rest":
                        # 跳过剩余步骤
                        for j in range(i + 1, len(script.steps)):
                            skipped = StepResult(
                                step_index=j,
                                action=script.steps[j].action,
                                description=script.steps[j].description,
                                status=StepStatus.SKIPPED,
                            )
                            result.steps.append(skipped)
                        break

        except Exception as e:
            result.status = TestStatus.ERROR
            result.error_message = str(e)
            logger.error(f"Script execution error: {e}", exc_info=True)
        finally:
            # 清理引擎
            try:
                if ctx.engine:
                    await ctx.engine.stop()
            except Exception:
                pass

        # 判定整体结果
        result.end_time = time.time()
        if result.status != TestStatus.ERROR:
            has_failure = any(
                s.status in (StepStatus.FAILED, StepStatus.ERROR)
                for s in result.steps
            )
            result.status = TestStatus.FAILED if has_failure else TestStatus.PASSED

        if self._on_test_complete:
            try:
                self._on_test_complete(result)
            except Exception:
                pass

        return result

    async def run_all(self) -> list[TestScript]:
        """运行所有已加载的脚本."""
        results = []
        for script in self._scripts:
            logger.info(f"Running script: {script.name}")
            result = await self.run(script)
            results.append(result)

            # 保存报告
            report_path = self._report_dir / f"{script.name}.txt"
            ReportGenerator.save(result, report_path, format="text")
            json_path = self._report_dir / f"{script.name}.json"
            ReportGenerator.save(result, json_path, format="json")

            logger.info(result.summary())

        return results

    # ── 步骤执行 ──────────────────────────────────────────────────

    async def _execute_step(
        self, step: TestStep, ctx: TestContext, script_timeout: float
    ) -> StepResult:
        """执行单个步骤."""
        step_result = StepResult(
            step_index=step.index,
            action=step.action,
            description=step.description,
            status=StepStatus.RUNNING,
        )

        start_time = time.monotonic()

        try:
            # 执行动作
            logger.info(f"Step {step.index}: {step.action} — {step.description}")
            action_result = await self._actions.execute(step.action, ctx, step.params)
            step_result.message = action_result.get("message", "")
            step_result.details = action_result

            # 执行断言
            all_assertions_passed = True
            for assertion in step.assertions:
                a_result = self._assertions.check(assertion.type, ctx, assertion.params)
                step_result.assertions.append(a_result)
                if not a_result["passed"]:
                    all_assertions_passed = False

            step_result.status = StepStatus.PASSED if all_assertions_passed else StepStatus.FAILED

        except TimeoutError as e:
            step_result.status = StepStatus.FAILED
            step_result.message = str(e)
            logger.warning(f"Step {step.index} timeout: {e}")

        except Exception as e:
            step_result.status = StepStatus.ERROR
            step_result.message = str(e)
            logger.error(f"Step {step.index} error: {e}", exc_info=True)

        step_result.duration_ms = (time.monotonic() - start_time) * 1000
        return step_result

    # ── 引擎工厂 ──────────────────────────────────────────────────

    def _create_engine(self, script: TestScript):
        """根据脚本配置创建引擎."""
        conn = script.connection
        timers = script.timers
        fc = script.flow_control

        if script.role == "master":
            from ..engine.master import MasterEngine
            return MasterEngine(
                host=conn.get("host", "127.0.0.1"),
                port=conn.get("port", 2404),
                common_addr=conn.get("common_addr", 1),
                k=fc.get("k", 12),
                w=fc.get("w", 8),
                t0=timers.get("t0", 30),
                t1=timers.get("t1", 15),
                t2=timers.get("t2", 10),
                t3=timers.get("t3", 20),
                auto_start=conn.get("auto_start", True),
                auto_gi=False,
                reconnect=conn.get("reconnect", True),
                reconnect_interval=conn.get("reconnect_interval", 5.0),
            )
        else:
            from ..engine.slave import SlaveEngine
            from ..data.point_table import PointTable

            pt = PointTable()
            pt_config = script.point_table
            if pt_config.get("file"):
                pt.load_yaml(pt_config["file"])
            elif pt_config.get("auto_generate", True):
                pt.generate_demo_points(
                    yx_count=pt_config.get("yx_count", 100),
                    yc_count=pt_config.get("yc_count", 50),
                    yk_count=pt_config.get("yk_count", 20),
                    ym_count=pt_config.get("ym_count", 10),
                )

            return SlaveEngine(
                host="0.0.0.0",
                port=conn.get("port", 2404),
                common_addr=conn.get("common_addr", 1),
                k=fc.get("k", 12),
                w=fc.get("w", 8),
                t0=timers.get("t0", 30),
                t1=timers.get("t1", 15),
                t2=timers.get("t2", 10),
                t3=timers.get("t3", 20),
                max_connections=conn.get("max_connections", 16),
                point_table=pt,
                spontaneous_enabled=conn.get("spontaneous_enabled", True),
            )

    def _setup_callbacks(self, engine, ctx: TestContext) -> None:
        """设置引擎回调，将事件同步到上下文."""
        if ctx.role == "master":
            from ..engine.master import MasterEvent

            def on_master_event(event, data):
                ctx.add_event(event.value, data)
                if event == MasterEvent.CONNECTED:
                    ctx.connected = True
                elif event == MasterEvent.DISCONNECTED:
                    ctx.connected = False
                elif event == MasterEvent.STARTED:
                    ctx.running = True
                elif event == MasterEvent.DATA_RECEIVED:
                    # 记录 ASDU
                    ctx.received_asdus.append({
                        "type_id": data.get("type_id"),
                        "cot": data.get("cot"),
                        "objects": data.get("objects"),
                    })

            def on_raw_frame(data, direction):
                if direction == "rx":
                    ctx.add_rx_frame(data)
                else:
                    ctx.add_tx_frame(data)

            engine.set_event_callback(on_master_event)
            engine.set_raw_frame_callback(on_raw_frame)
        else:
            from ..engine.slave import SlaveEvent

            def on_slave_event(event, data):
                ctx.add_event(event.value, data)
                if event == SlaveEvent.CLIENT_CONNECTED:
                    ctx.client_count += 1
                    ctx.connected = True
                elif event == SlaveEvent.CLIENT_DISCONNECTED:
                    ctx.client_count = max(0, ctx.client_count - 1)
                    if ctx.client_count == 0:
                        ctx.connected = False

            def on_raw_frame_slave(data, direction, client_id=""):
                if direction == "rx":
                    ctx.add_rx_frame(data)
                else:
                    ctx.add_tx_frame(data)

            engine.set_event_callback(on_slave_event)
            engine.set_raw_frame_callback(on_raw_frame_slave)
