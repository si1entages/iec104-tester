"""前端 API 调用 ↔ 后端路由一致性（静态扫描）.

为什么需要这道门禁：运行时契约校验只保证「响应形状」，路径/方法写错时
（例如把 GET 写成 POST、路径少一段）只会在用户点按钮时才暴露。本测试直接
解析两端源码做双向检查：

- 前端每个 ``apiGet/apiGetText/apiPost/apiPostText``（含 URL 常量）必须在
  后端 ``webui/server.py`` 注册了同方法、同路径的路由；
- 后端注册了但前端未调用的 API 只记录（CLI/第三方可能使用），不作为失败。

路径参数（``{name}``/``{run_id}``）按原样比较；查询串不参与比较。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "webui" / "server.py"
ENDPOINTS = ROOT / "webui" / "frontend" / "src" / "api" / "endpoints.ts"

ROUTE_RE = re.compile(r'add_(get|post|put|delete)\(\s*"([^"]+)"')
CONST_RE = re.compile(r"^export const ([A-Z][A-Z0-9_]*) = '([^']+)'", re.MULTILINE)
CALL_RE = re.compile(r"api(GetText|PostText|Get|Post)\(\s*(?:'([^']+)'|([A-Z][A-Z0-9_]*))")


def _backend_routes() -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for method, path in ROUTE_RE.findall(SERVER.read_text(encoding="utf-8")):
        routes.add((method.upper(), path))
    return routes


def _frontend_calls() -> set[tuple[str, str]]:
    text = ENDPOINTS.read_text(encoding="utf-8")
    constants = dict(CONST_RE.findall(text))
    calls: set[tuple[str, str]] = set()
    for kind, literal, identifier in CALL_RE.findall(text):
        path = literal or constants.get(identifier, "")
        if not path.startswith("/api/"):
            continue
        method = "GET" if kind in ("Get", "GetText") else "POST"
        calls.add((method, path))
    # 下载链接走浏览器直开（GET），不是 apiGet 调用
    for constant in ("CAPTURE_DOWNLOAD_PATH", "TEST_REPORT_PATH"):
        path = constants.get(constant, "")
        if path:
            calls.add(("GET", path))
    return calls


def test_frontend_api_calls_have_backend_routes() -> None:
    missing = sorted(_frontend_calls() - _backend_routes())
    assert not missing, "前端调用了后端未注册的接口：\n" + "\n".join(
        f"  - {method} {path}" for method, path in missing
    )


def test_backend_api_routes_are_reachable_from_frontend_or_documented() -> None:
    """后端已注册但前端未调用的 API 仅作提示（不失败）。

    保留该用例是为了让「新加后端接口但前端没接」在测试输出里可见；
    真正的一致性门禁是上面的 frontend → backend 方向。
    """
    unused = sorted(
        route for route in _backend_routes() - _frontend_calls()
        if route[1].startswith("/api/")
    )
    print(f"后端有、前端未调用（{len(unused)}）："
          + ", ".join(f"{m} {p}" for m, p in unused))
