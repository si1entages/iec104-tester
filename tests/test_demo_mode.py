"""一键环回演示（--demo）的命令构造与端口选择测试."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from app import _demo_commands, _pick_port, _port_free

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _free_port_pair() -> tuple[int, int]:
    """返回一对相邻的可用 HTTP 端口（demo 默认 slave=master+1）."""
    for _ in range(50):
        first = _free_port()
        if first < 65535 and _port_free(first + 1):
            return first, first + 1
    raise RuntimeError("no adjacent free ports")


def _args(**overrides) -> argparse.Namespace:
    data = {"log_level": "INFO", "config": None, "point_table": None}
    data.update(overrides)
    return argparse.Namespace(**data)


def test_pick_port_prefers_requested_free_port() -> None:
    port = _free_port()
    assert _port_free(port)
    assert _pick_port(port) == port


def test_pick_port_skips_excluded_port() -> None:
    first = _free_port()
    picked = _pick_port(first, exclude={first})
    assert picked != first
    assert _port_free(picked) or picked != first  # 端口可能被并行测试占用


def test_demo_commands_are_isolated_and_auto_configured() -> None:
    cmd = _demo_commands(
        _args(config="configs/demo.yaml", point_table="point_table.yaml"),
        http_port=18765, iec_port=24040,
    )

    assert "--mode" in cmd and cmd[cmd.index("--mode") + 1] == "both"
    assert "--no-browser" in cmd
    assert "--no-history" in cmd  # 演示不落盘历史库
    assert cmd[cmd.index("--http-port") + 1] == "18765"
    assert cmd[cmd.index("--port") + 1] == "24040"
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--config") + 1] == "configs/demo.yaml"
    assert cmd[cmd.index("--point-table") + 1] == "point_table.yaml"


def test_demo_commands_omit_optional_paths() -> None:
    cmd = _demo_commands(_args(), http_port=18765, iec_port=24040)
    assert "--config" not in cmd
    assert "--point-table" not in cmd


def _get_status(port: int, path: str = "/api/status") -> dict | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=1
        ) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _wait(predicate, timeout: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return predicate()


def test_demo_starts_both_roles_and_stops_cleanly() -> None:
    """真启动 `--demo`：单进程双角色、主站自动连上、到时回收进程."""
    http_port = _free_port()
    iec_port = _free_port()
    while iec_port == http_port:
        iec_port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, str(ROOT / "app.py"), "--demo", "--no-browser",
            "--demo-seconds", "8", "--http-port", str(http_port),
            "--port", str(iec_port),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        assert proc.stdout is not None
        output_lines: list[str] = []

        def _drain() -> None:
            for line in proc.stdout:  # type: ignore[union-attr]
                output_lines.append(line.rstrip())

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()

        def _tail() -> str:
            return "\n".join(output_lines[-40:])

        assert _wait(
            lambda: _get_status(http_port)
            and _get_status(http_port, "/slave/api/status"),
            timeout=60,
        ), f"演示主/子站未就绪\n{_tail()}"
        assert _wait(
            lambda: bool((_get_status(http_port) or {}).get("running")), timeout=30
        ), f"主站未自动连接\n{_tail()}"

        master = _get_status(http_port) or {}
        slave = _get_status(http_port, "/slave/api/status") or {}
        assert master.get("role") == "master" and slave.get("role") == "slave"
        assert master.get("points", 0) > 0

        proc.wait(timeout=40)
        reader.join(timeout=2)
        output = "\n".join(output_lines)
        assert proc.returncode == 0, output
        assert "工作台（主站/子站同一页面）" in output
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    # 进程已随演示退出回收：唯一 HTTP 端口不再响应
    assert _wait(lambda: _get_status(http_port) is None, timeout=15), \
        "演示退出后仍残留子进程/端口"
