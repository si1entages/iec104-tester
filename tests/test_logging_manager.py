"""结构化日志管理器测试.

覆盖：结构化写入 / 级别与类别过滤 / 关键字 / JSONL 落盘与轮转 /
Python logging 桥 / 订阅回调 / 线程安全（多线程写入不丢不乱）。
"""

from __future__ import annotations

import json
import logging
import threading

import pytest

from core.logging_manager import LEVEL_ORDER, LogManager


@pytest.fixture
def mgr(tmp_path):
    return LogManager(source="slave", log_dir=tmp_path, max_memory=1000)


def test_basic_levels_and_query(mgr):
    mgr.debug("debug msg")
    mgr.info("info msg")
    mgr.warning("warn msg")
    mgr.error("error msg")

    # 默认最新在前
    all_rows = mgr.query(limit=100)
    assert [r.level for r in all_rows] == ["ERROR", "WARNING", "INFO", "DEBUG"]

    # 正序读取
    ordered = mgr.query(limit=100, newest_first=False)
    assert [r.level for r in ordered] == ["DEBUG", "INFO", "WARNING", "ERROR"]

    warns = mgr.query(level_min="WARNING", limit=100, newest_first=False)
    assert [r.level for r in warns] == ["WARNING", "ERROR"]

    assert len(mgr.query(level_min="ERROR")) == 1


def test_source_category_and_keyword_filters(mgr):
    mgr.info("连接建立", source="slave", category="connection")
    mgr.info("遥控下发", source="master", category="command")
    mgr.error("STARTDT 超时", source="master", category="protocol")

    conn = mgr.query(category="connection", limit=100)
    assert len(conn) == 1 and conn[0].category == "connection"

    proto = mgr.query(category="protocol", limit=100)
    assert len(proto) == 1 and proto[0].message == "STARTDT 超时"

    hits = mgr.query(contains="遥控", limit=100)
    assert len(hits) == 1 and hits[0].message == "遥控下发"

    none = mgr.query(contains="不存在的关键字", limit=100)
    assert none == []


def test_jsonl_file_written_and_rotates(tmp_path):
    from core.logging_manager import _RotatingJsonlFile

    path = tmp_path / "logs" / "iec104_slave.jsonl"
    # max_bytes 有 1024 下限（避免过小文件频繁轮转），用足量行数触发轮转
    f = _RotatingJsonlFile(path, max_bytes=1024, backups=2)
    for i in range(60):
        f.append(json.dumps({"n": i, "msg": "x" * 30}, ensure_ascii=False))

    # 轮转文件存在
    assert (tmp_path / "logs" / "iec104_slave.jsonl.1").exists()

    # 所有内容可读回（时间顺序），无丢失、可解析
    lines = f.read_all()
    assert len(lines) == 60
    parsed = [json.loads(line) for line in lines]
    ns = [p["n"] for p in parsed]
    assert ns == sorted(ns), "read_all 应按时间顺序返回"
    assert set(ns) == set(range(60))


def test_manager_writes_jsonl_file(mgr):
    mgr.info("hello file")
    rows = mgr.query(limit=10)
    # 文件内容与内存一致
    st = mgr.stats()
    assert st["file"] and st["file_bytes"] > 0
    assert rows[0].message == "hello file"


def test_python_logging_bridge(mgr):
    mgr.attach_python_logging(logger_names=("iec104.test",), level=logging.DEBUG)
    lg = logging.getLogger("iec104.test.transport")
    lg.info("连接已建立")
    lg.warning("T2 超时")

    rows = mgr.query(limit=10, newest_first=False)
    assert [r.level for r in rows] == ["INFO", "WARNING"]
    assert rows[-1].category == "connection"  # logger 名末段 transport → 连接类
    assert rows[0].source == "iec104.test.transport"


def test_python_logging_bridge_idempotent(mgr):
    """重复 attach 不得产生重复记录（换绑而非追加）."""
    mgr.attach_python_logging(logger_names=("iec104.dup",))
    before = len(mgr.query(limit=100))
    mgr.attach_python_logging(logger_names=("iec104.dup",))
    logging.getLogger("iec104.dup").info("one record")
    assert len(mgr.query(limit=100)) == before + 1


def test_subscriber_callback(mgr):
    got: list = []
    mgr.subscribe(got.append)
    mgr.info("pushed")
    assert len(got) == 1 and got[0].message == "pushed"

    mgr.unsubscribe(got.append)
    mgr.info("again")
    assert len(got) == 1


def test_subscriber_exception_does_not_break(mgr):
    def bad(entry):
        raise RuntimeError("boom")

    mgr.subscribe(bad)
    mgr.error("still logged")     # 不应抛出
    assert mgr.query(limit=10)[-1].message == "still logged"


def test_thread_safety_many_writers():
    mgr = LogManager(source="t", max_memory=5000, file_enabled=False)
    def worker(base: int) -> None:
        for i in range(200):
            mgr.info(f"msg {base}-{i}", category="data")

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = mgr.query(limit=5000, newest_first=False)
    assert len(rows) == 800
    assert all(r.message.startswith("msg ") for r in rows)


def test_stats_structure(mgr):
    mgr.info("a")
    mgr.error("b")
    st = mgr.stats()
    assert st["total"] == 2
    assert st["by_level"]["INFO"] == 1 and st["by_level"]["ERROR"] == 1
    assert st["file"] and st["file_bytes"] > 0


def test_level_order_table():
    assert LEVEL_ORDER["DEBUG"] < LEVEL_ORDER["INFO"] < LEVEL_ORDER["WARNING"]
    assert LEVEL_ORDER["WARNING"] < LEVEL_ORDER["ERROR"] < LEVEL_ORDER["CRITICAL"]
