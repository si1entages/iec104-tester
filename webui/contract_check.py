"""契约自检（T18）：保证 `webui/api_contract.md` 与后端实现不漂移.

用法：
    python -m webui.contract_check          # 独立运行；发现漂移时退出码非 0
    pytest tests/test_api_contract.py -q    # 同一套断言接入 CI

检查项：
  1. 常量一致：webui/events.py::SCHEMA_VERSION == 前端 src/api/schema.ts::SCHEMA_VERSION
  2. 端点不漂移：create_app() 实际注册的 /api/* 路由 ↔ 文档 §2 表格，双向一致
  3. 信封带版本：EventBus.publish() 产出的消息含 schemaVersion；
     且 server.py 中所有带 "kind" 的 send_json 载荷同样含 schemaVersion
  4. 版本策略章节存在

只依赖标准库 + aiohttp（项目已有依赖），可被 pytest 直接调用。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

WEBUI = Path(__file__).resolve().parent
ROOT = WEBUI.parent
DOC = WEBUI / "api_contract.md"
SERVER_PY = WEBUI / "server.py"
EVENTS_PY = WEBUI / "events.py"
FRONTEND_SCHEMA_TS = WEBUI / "frontend" / "src" / "api" / "schema.ts"

# 文档 §2 表格行：| GET | `/api/status` | ... |
_ENDPOINT_ROW = re.compile(r"^\|\s*(GET|POST)\s*\|\s*`(/api/[^`\s]+)`\s*\|", re.MULTILINE)


def _documented_endpoints(text: str) -> set[tuple[str, str]]:
    return {(m.group(1), m.group(2)) for m in _ENDPOINT_ROW.finditer(text)}


def _registered_endpoints() -> set[tuple[str, str]]:
    """构造真实 app，枚举其注册的 /api/* 路由（过滤 /api 前缀之外的静态/WS 路由）."""
    from webui.bridge import EngineBridge
    from webui.server import create_app

    bridge = EngineBridge("master")
    try:
        app = create_app(bridge)
        found: set[tuple[str, str]] = set()
        for route in app.router.routes():
            method = getattr(route, "method", "")
            if method not in ("GET", "POST"):
                continue
            path = route.resource.canonical
            if path.startswith("/api/"):
                found.add((method, path))
        return found
    finally:
        _close_bridge(bridge)


def _close_bridge(bridge) -> None:
    """关闭 bridge 的事件循环资源；构造过程未启动引擎，只需尽力回收."""
    try:
        import asyncio

        asyncio.run(bridge.shutdown())
    except Exception:
        # 未启动引擎时 shutdown 无副作用；失败不应影响自检结论
        pass


def _backend_schema_version() -> int:
    from webui.events import SCHEMA_VERSION

    return int(SCHEMA_VERSION)


def _frontend_schema_version() -> int | None:
    if not FRONTEND_SCHEMA_TS.is_file():
        return None
    text = FRONTEND_SCHEMA_TS.read_text(encoding="utf-8")
    m = re.search(r"export\s+const\s+SCHEMA_VERSION\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def _publish_envelope_has_version() -> bool:
    from webui.events import EventBus

    msg = EventBus().publish("probe", {})
    return "schemaVersion" in msg


def _send_json_payloads_have_version() -> list[str]:
    """server.py 中所有带 "kind" 的 send_json 载荷都必须含 "schemaVersion"."""
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "send_json"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Dict):
            continue
        keys = {k.value for k in node.args[0].keys if isinstance(k, ast.Constant)}
        if "kind" in keys and "schemaVersion" not in keys:
            problems.append(f"server.py:{node.lineno} send_json 缺少 schemaVersion")
    return problems


def run_checks() -> list[str]:
    """执行全部自检，返回问题列表（空列表 = 全部通过）."""
    problems: list[str] = []

    # 1. 常量一致
    backend = _backend_schema_version()
    frontend = _frontend_schema_version()
    if frontend is None:
        problems.append(f"未能从 {FRONTEND_SCHEMA_TS} 解析 SCHEMA_VERSION")
    elif frontend != backend:
        problems.append(f"schemaVersion 不一致：后端={backend} 前端={frontend}")

    # 2. 端点双向一致
    doc_text = DOC.read_text(encoding="utf-8")
    documented = _documented_endpoints(doc_text)
    registered = _registered_endpoints()
    for method, path in sorted(registered - documented):
        problems.append(f"实现有、文档缺：{method} {path}")
    for method, path in sorted(documented - registered):
        problems.append(f"文档有、实现缺：{method} {path}")

    # 3. 信封带版本
    if not _publish_envelope_has_version():
        problems.append("EventBus.publish() 信封缺少 schemaVersion")
    problems.extend(_send_json_payloads_have_version())

    # 4. 版本策略章节
    if "版本策略" not in doc_text or "schemaVersion" not in doc_text:
        problems.append("api_contract.md 缺少「版本策略」章节或 schemaVersion 说明")

    return problems


def main() -> int:
    problems = run_checks()
    if problems:
        print("契约自检失败：")
        for p in problems:
            print("  -", p)
        return 1
    print(f"契约自检通过（schemaVersion={_backend_schema_version()}，"
          f"REST 端点 {len(_registered_endpoints())} 个，双向一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
