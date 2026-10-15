"""`core/testing/script.py` YAML 测试脚本加载器单元测试。

覆盖文件/字符串加载、默认值填充、步骤与断言的多种写法（简写字符串、字典、
字典列表、非法项跳过）、目录批量加载（含坏文件只记日志不中断）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import yaml

from core.testing.script import Assertion, ScriptLoader
from core.testing.script import TestScript as YamlTestScript
from core.testing.script import TestStep as YamlTestStep

SAMPLE_YAML = """
name: 主站基础流程
description: 连接 → 总召唤 → 校验
version: "2.1"
author: qa
tags: [smoke, master]
config:
  role: master
  connection:
    host: 127.0.0.1
    port: 2404
  timers:
    t1: 15
  flow_control:
    k: 12
  point_table:
    path: configs/demo_points.yaml
  timeout: 30
steps:
  - action: connect
    description: 建立连接
    params: {timeout: 5}
    on_failure: abort
    timeout: 10
    tags: [net]
    assert:
      - "state:running"
      - type: frame_count
        params:
          direction: rx
          min: 1
        description: 至少一帧
  - action: general_interrogation
    assert:
      type: asdu_received
      params: {type_id: 100}
  - action: log
"""


def _write(tmp_path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ── 数据模型默认值 ───────────────────────────────────────────────

def test_dataclass_defaults():
    a = Assertion()
    assert (a.type, a.params, a.description) == ("", {}, "")

    step = YamlTestStep()
    assert step.index == 0
    assert step.on_failure == "continue"
    assert step.timeout == 0.0
    assert step.assertions == [] and step.tags == []

    script = YamlTestScript()
    assert script.version == "1.0"
    assert script.role == "master"
    assert script.timeout == 60.0
    assert script.steps == [] and script.path == ""


# ── 文件 / 字符串加载 ────────────────────────────────────────────

def test_load_parses_metadata_config_and_steps(tmp_path):
    script = ScriptLoader.load(_write(tmp_path, "flow.yaml", SAMPLE_YAML))

    assert script.name == "主站基础流程"
    assert script.description == "连接 → 总召唤 → 校验"
    assert script.version == "2.1"
    assert script.author == "qa"
    assert script.tags == ["smoke", "master"]
    assert script.role == "master"
    assert script.connection == {"host": "127.0.0.1", "port": 2404}
    assert script.timers == {"t1": 15}
    assert script.flow_control == {"k": 12}
    assert script.point_table == {"path": "configs/demo_points.yaml"}
    assert script.timeout == 30
    assert script.path.endswith("flow.yaml")
    assert len(script.steps) == 3


def test_load_parses_step_fields_and_assertion_forms(tmp_path):
    script = ScriptLoader.load(_write(tmp_path, "flow.yaml", SAMPLE_YAML))

    first = script.steps[0]
    assert first.index == 0
    assert first.action == "connect"
    assert first.description == "建立连接"
    assert first.params == {"timeout": 5}
    assert first.on_failure == "abort"
    assert first.timeout == 10
    assert first.tags == ["net"]

    # 简写字符串断言 → {"expected": ...}
    shorthand, detailed = first.assertions
    assert shorthand.type == "state"
    assert shorthand.params == {"expected": "running"}

    # 完整字典断言
    assert detailed.type == "frame_count"
    assert detailed.params == {"direction": "rx", "min": 1}
    assert detailed.description == "至少一帧"

    # 单条字典断言（非列表）也应被接受
    second = script.steps[1]
    assert len(second.assertions) == 1
    assert second.assertions[0].type == "asdu_received"
    assert second.assertions[0].params == {"type_id": 100}

    # 无断言与无描述 → description 回落为 action 名
    third = script.steps[2]
    assert third.assertions == []
    assert third.description == "log"


def test_load_shorthand_assertion_without_value_has_empty_params(tmp_path):
    yaml_text = "steps:\n  - action: log\n    assert: ['always_pass']\n"
    script = ScriptLoader.load(_write(tmp_path, "s.yaml", yaml_text))

    assert script.steps[0].assertions[0].type == "always_pass"
    assert script.steps[0].assertions[0].params == {}


def test_load_skips_non_str_non_dict_assertion_items(tmp_path):
    """断言列表中的非法项（如数字）被跳过，不抛异常."""
    yaml_text = "steps:\n  - action: log\n    assert: [123, 'state:running']\n"
    script = ScriptLoader.load(_write(tmp_path, "s.yaml", yaml_text))

    assert len(script.steps[0].assertions) == 1
    assert script.steps[0].assertions[0].type == "state"


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Script not found"):
        ScriptLoader.load(tmp_path / "nope.yaml")


def test_load_defaults_when_minimal(tmp_path):
    script = ScriptLoader.load(_write(tmp_path, "min.yaml", "steps: []\n"))

    assert script.name == "min"                 # 回落为文件名
    assert script.version == "1.0"
    assert script.role == "master"
    assert script.timeout == 60.0
    assert script.steps == []


def test_load_empty_file_yields_default_script(tmp_path):
    script = ScriptLoader.load(_write(tmp_path, "empty.yaml", ""))
    assert isinstance(script, YamlTestScript)
    assert script.steps == []


def test_loads_from_string():
    script = ScriptLoader.loads(SAMPLE_YAML, name="inline-script")

    assert script.path == "inline-script"
    assert len(script.steps) == 3


def test_loads_empty_string_yields_default():
    script = ScriptLoader.loads("")
    assert script.name == "<inline>"
    assert script.steps == []


# ── 目录批量加载 ─────────────────────────────────────────────────

def test_load_directory_reads_yaml_and_yml(tmp_path):
    _write(tmp_path, "a.yaml", "name: A\nsteps: []\n")
    _write(tmp_path, "b.yml", "name: B\nsteps: []\n")
    (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    _write(tmp_path / "sub", "c.yaml", "name: C\nsteps: []\n")

    scripts = ScriptLoader.load_directory(tmp_path)

    assert [s.name for s in scripts] == ["A", "B"]   # 非递归、仅 yaml/yml


def test_load_directory_skips_broken_files(tmp_path):
    """损坏的 .yaml 与 .yml 都只记日志、不中断整体加载."""
    _write(tmp_path, "ok.yaml", "name: OK\nsteps: []\n")
    _write(tmp_path, "bad.yaml", "name: [unclosed\n")
    _write(tmp_path, "ok.yml", "name: OKYML\nsteps: []\n")
    _write(tmp_path, "bad.yml", "name: [unclosed\n")

    scripts = ScriptLoader.load_directory(tmp_path)

    assert [s.name for s in scripts] == ["OK", "OKYML"]


def test_load_directory_on_empty_dir_returns_empty(tmp_path):
    assert ScriptLoader.load_directory(tmp_path) == []


def test_parse_is_reachable_via_loader_staticmethod(tmp_path):
    """直接调用 _parse 也应正确解析（覆盖内部入口）."""
    data = yaml.safe_load("name: X\nsteps:\n  - action: log\n")
    script = ScriptLoader._parse(data, "inline")

    assert script.name == "X"
    assert script.path == "inline"
    assert script.steps[0].action == "log"
