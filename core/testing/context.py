"""测试上下文 — 管理测试运行时状态."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class TestStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


@dataclass
class StepResult:
    """单步执行结果."""
    step_index: int = 0
    action: str = ""
    description: str = ""
    status: StepStatus = StepStatus.PENDING
    duration_ms: float = 0.0
    message: str = ""
    details: dict = field(default_factory=dict)
    assertions: list[dict] = field(default_factory=list)
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class TestResult:
    """测试脚本整体结果."""
    script_name: str = ""
    script_path: str = ""
    status: TestStatus = TestStatus.PENDING
    start_time: float = 0.0
    end_time: float = 0.0
    steps: list[StepResult] = field(default_factory=list)
    error_message: str = ""
    description: str = ""  # 脚本描述（来自 TestScript.description），供报告副标题展示

    @property
    def duration_s(self) -> float:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0

    @property
    def total(self) -> int:
        return len(self.steps)

    @property
    def passed(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.FAILED)

    @property
    def errors(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.ERROR)

    @property
    def skipped(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.SKIPPED)

    def summary(self) -> str:
        status_icon = "✅" if self.status == TestStatus.PASSED else "❌"
        lines = [
            f"{status_icon} {self.script_name}",
            f"   Status: {self.status.value.upper()}",
            f"   Duration: {self.duration_s:.2f}s",
            f"   Steps: {self.total} total, "
            f"{self.passed} passed, {self.failed} failed, "
            f"{self.errors} errors, {self.skipped} skipped",
        ]
        if self.error_message:
            lines.append(f"   Error: {self.error_message}")
        return "\n".join(lines)


class TestContext:
    """测试运行上下文 — 跨步骤共享状态.

    存储:
    - 连接状态
    - 收到的帧
    - 引擎实例
    - 用户变量
    """

    def __init__(self):
        self._lock = threading.Lock()

        # 连接状态
        self.connected: bool = False
        self.running: bool = False  # STARTDT 已完成
        self.client_count: int = 0

        # 帧缓冲
        self.rx_frames: list[tuple[float, bytes]] = []
        self.tx_frames: list[tuple[float, bytes]] = []

        # ASDU 缓冲（解析后的）
        self.received_asdus: list[dict] = []

        # 数据存储快照
        self.yx_data: dict[int, Any] = {}
        self.yc_data: dict[int, Any] = {}
        self.ym_data: dict[int, Any] = {}

        # 事件日志
        self.events: list[tuple[float, str, dict]] = []

        # 用户变量（脚本中 set_variable 设置）
        self.variables: dict[str, Any] = {}

        # 引擎引用
        self.engine: Any = None

        # 配置
        self.role: str = "master"  # master / slave

    def reset(self) -> None:
        """重置上下文."""
        with self._lock:
            self.connected = False
            self.running = False
            self.client_count = 0
            self.rx_frames.clear()
            self.tx_frames.clear()
            self.received_asdus.clear()
            self.yx_data.clear()
            self.yc_data.clear()
            self.ym_data.clear()
            self.events.clear()
            # 不清除 variables 和 engine

    def add_rx_frame(self, data: bytes) -> None:
        with self._lock:
            self.rx_frames.append((time.time(), data))

    def add_tx_frame(self, data: bytes) -> None:
        with self._lock:
            self.tx_frames.append((time.time(), data))

    def add_event(self, event_type: str, data: dict) -> None:
        with self._lock:
            self.events.append((time.time(), event_type, data))

    def get_variable(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)

    def set_variable(self, name: str, value: Any) -> None:
        self.variables[name] = value

    def get_rx_frame_count(self, frame_type: str = None) -> int:
        """获取接收帧数. frame_type: 'I'/'S'/'U'/None(全部)."""
        if frame_type is None:
            return len(self.rx_frames)
        count = 0
        for _, data in self.rx_frames:
            if len(data) >= 6:
                cf = data[2]
                if frame_type == "I" and (cf & 0x01) == 0 or frame_type == "S" and (cf & 0x03) == 0x01 or frame_type == "U" and (cf & 0x03) == 0x03:
                    count += 1
        return count

    def get_tx_frame_count(self, frame_type: str = None) -> int:
        if frame_type is None:
            return len(self.tx_frames)
        count = 0
        for _, data in self.tx_frames:
            if len(data) >= 6:
                cf = data[2]
                if frame_type == "I" and (cf & 0x01) == 0 or frame_type == "S" and (cf & 0x03) == 0x01 or frame_type == "U" and (cf & 0x03) == 0x03:
                    count += 1
        return count
