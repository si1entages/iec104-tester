"""QA 探针 — 关停路径耗时与 transport 泄漏回归验证（无 mock，真 socket）.

背景：`TCPServer.stop()` 曾固定阻塞 2.0s 并打印 "Server wait_closed timeout"。
根因是 `TCPConnection._read_loop` 在对端断开（EOF）退出时不关闭 transport，
连接已从 `TCPServer._connections` 移除 → `stop()` 不会再关闭它 →
Python 3.13+ 的 `Server.wait_closed()` 一直等待该连接关闭，直到超时；
同时 socket 文件描述符泄漏。

断言：
  1. 传输层：对端先断开后 `server.stop()` < 1.0s
  2. 传输层：服务端先 stop（连接活跃）后 `server.stop()` < 1.0s
  3. 引擎层：`master.stop()` + `slave.stop()` 总耗时 < 1.5s 且无 wait_closed 告警

用法: python tests/e2e/qa_shutdown.py
"""
from __future__ import annotations

import asyncio
import logging
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.engine.master import MasterEngine  # noqa: E402
from core.engine.slave import SlaveEngine  # noqa: E402
from core.transport.connection import TCPServer  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    _results.append((name, PASS if ok else FAIL, detail))
    print(f"[{PASS if ok else FAIL}] {name}\n      {detail}")


class _CollectHandler(logging.Handler):
    """收集 transport 日志中的 wait_closed 告警."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if "wait_closed" in record.getMessage():
            self.records.append(record.getMessage())


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def sc1_transport_peer_first() -> None:
    port = _free_port()
    server = TCPServer(host="127.0.0.1", port=port)
    await server.start()
    try:
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await _wait_until(lambda: server.connection_count == 1)
        writer.close()
        await writer.wait_closed()
        tracked = await _wait_until(lambda: server.connection_count == 0)

        start = time.monotonic()
        await asyncio.wait_for(server.stop(), timeout=10)
        elapsed = time.monotonic() - start
        record("1. 传输层/对端先断开 -> server.stop() 立即返回",
               tracked and elapsed < 1.0,
               f"跟踪连接数={server.connection_count}, stop()={elapsed:.3f}s (期望 < 1.0s)")
    finally:
        await asyncio.wait_for(server.stop(), timeout=10)


async def sc2_transport_server_first() -> None:
    port = _free_port()
    server = TCPServer(host="127.0.0.1", port=port)
    await server.start()
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await _wait_until(lambda: server.connection_count == 1)
    start = time.monotonic()
    await asyncio.wait_for(server.stop(), timeout=10)
    elapsed = time.monotonic() - start
    writer.close()
    record("2. 传输层/服务端先停止（连接活跃） -> server.stop() 立即返回",
           elapsed < 1.0, f"stop()={elapsed:.3f}s (期望 < 1.0s)")


async def sc3_engine_pair_shutdown(handler: _CollectHandler) -> None:
    port = _free_port()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1)
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False)
    await slave.start()
    await master.start()
    assert await _wait_until(lambda: slave.client_count > 0)

    handler.records.clear()
    start = time.monotonic()
    await asyncio.wait_for(master.stop(), timeout=10)
    await asyncio.wait_for(slave.stop(), timeout=10)
    elapsed = time.monotonic() - start
    record("3. 引擎层/主站+子站关停 -> 无 wait_closed 阻塞与告警",
           elapsed < 1.5 and not handler.records,
           f"master.stop()+slave.stop()={elapsed:.3f}s, wait_closed 告警={handler.records}")


async def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    handler = _CollectHandler()
    logging.getLogger("iec104.transport").addHandler(handler)

    await sc1_transport_peer_first()
    await sc2_transport_server_first()
    await sc3_engine_pair_shutdown(handler)

    print("\n===== 汇总 =====")
    passed = sum(1 for _, s, _ in _results if s == PASS)
    for name, status, _ in _results:
        print(f"  {status}  {name}")
    print(f"共 {len(_results)} 项，通过 {passed}，失败 {len(_results) - passed}")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
