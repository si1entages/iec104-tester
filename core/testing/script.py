"""脚本加载器 — 解析 YAML 测试脚本."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger("iec104.testing.script")


@dataclass
class Assertion:
    """单条断言."""
    type: str = ""
    params: dict = field(default_factory=dict)
    description: str = ""


@dataclass
class TestStep:
    """单个测试步骤."""
    index: int = 0
    action: str = ""
    description: str = ""
    params: dict = field(default_factory=dict)
    assertions: list[Assertion] = field(default_factory=list)
    on_failure: str = "continue"  # continue / abort / skip_rest
    timeout: float = 0.0  # 步骤超时(秒), 0=不限
    tags: list[str] = field(default_factory=list)


@dataclass
class TestScript:
    """解析后的测试脚本."""
    name: str = ""
    description: str = ""
    version: str = "1.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)

    # 配置
    role: str = "master"  # master / slave
    connection: dict = field(default_factory=dict)
    timers: dict = field(default_factory=dict)
    flow_control: dict = field(default_factory=dict)
    point_table: dict = field(default_factory=dict)
    timeout: float = 60.0  # 整体超时

    # 步骤
    steps: list[TestStep] = field(default_factory=list)

    # 元数据
    path: str = ""


class ScriptLoader:
    """YAML 测试脚本加载器."""

    @staticmethod
    def load(path: str | Path) -> TestScript:
        """从 YAML 文件加载测试脚本."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Script not found: {path}")

        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        return ScriptLoader._parse(data, str(path))

    @staticmethod
    def loads(yaml_str: str, name: str = "<inline>") -> TestScript:
        """从 YAML 字符串加载测试脚本."""
        data = yaml.safe_load(yaml_str) or {}
        return ScriptLoader._parse(data, name)

    @staticmethod
    def _parse(data: dict, path: str) -> TestScript:
        """解析 YAML 数据为 TestScript."""
        script = TestScript()
        script.path = path

        # 元数据
        script.name = data.get("name", Path(path).stem)
        script.description = data.get("description", "")
        script.version = data.get("version", "1.0")
        script.author = data.get("author", "")
        script.tags = data.get("tags", [])

        # 配置
        config = data.get("config", {})
        script.role = config.get("role", "master")
        script.connection = config.get("connection", {})
        script.timers = config.get("timers", {})
        script.flow_control = config.get("flow_control", {})
        script.point_table = config.get("point_table", {})
        script.timeout = config.get("timeout", 60.0)

        # 步骤
        raw_steps = data.get("steps", [])
        for i, step_data in enumerate(raw_steps):
            step = TestStep()
            step.index = i
            step.action = step_data.get("action", "")
            step.description = step_data.get("description", step.action)
            step.params = step_data.get("params", {})
            step.on_failure = step_data.get("on_failure", "continue")
            step.timeout = step_data.get("timeout", 0.0)
            step.tags = step_data.get("tags", [])

            # 解析断言
            raw_assertions = step_data.get("assert", [])
            if isinstance(raw_assertions, dict):
                raw_assertions = [raw_assertions]
            for a_data in raw_assertions:
                if isinstance(a_data, str):
                    # 简写: assert: "state:running"
                    a_type, _, a_params_str = a_data.partition(":")
                    a = Assertion(type=a_type, params={"expected": a_params_str} if a_params_str else {})
                elif isinstance(a_data, dict):
                    a = Assertion(
                        type=a_data.get("type", ""),
                        params=a_data.get("params", {}),
                        description=a_data.get("description", ""),
                    )
                else:
                    continue
                step.assertions.append(a)

            script.steps.append(step)

        logger.info(
            f"Loaded script '{script.name}': "
            f"{len(script.steps)} steps, role={script.role}"
        )

        return script

    @staticmethod
    def load_directory(directory: str | Path) -> list[TestScript]:
        """加载目录下所有测试脚本."""
        directory = Path(directory)
        scripts = []
        for path in sorted(directory.glob("*.yaml")):
            try:
                scripts.append(ScriptLoader.load(path))
            except Exception as e:
                logger.error(f"Failed to load {path}: {e}")
        for path in sorted(directory.glob("*.yml")):
            try:
                scripts.append(ScriptLoader.load(path))
            except Exception as e:
                logger.error(f"Failed to load {path}: {e}")
        return scripts
