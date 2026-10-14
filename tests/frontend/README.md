# tests/frontend — 前端脚本沙箱验证

本目录存放**受版本控制**的前端验证脚本，供 `tests/test_webui.py` 调用。

## `qa_webui_dom.mjs`

在 Node 的 `vm` 沙箱里用最小 DOM 桩**真实执行** `webui/static/master.html` /
`slave.html` 的内联脚本，断言：

- A. 内联脚本能执行到底（无 `ReferenceError`）
- B. 关键按钮都挂上了 `onclick`，点击后发出预期的 HTTP 请求
- C. 收到 WS `frame`/`event` 后会回发 `refresh`（节流后）
- D. 收到刷新快照后表格单元格就地更新（无需刷新页面）

这类「脚本能跑起来 + 按钮真的绑上了」的缺陷对 Python 端 HTML 字符串断言完全不可见，
必须真跑一次脚本才能发现（历史缺陷：`app.js` 未把 `$` 暴露到 `window`，两页内联脚本
首句即 `ReferenceError`，所有按钮静默失效）。

### 运行方式

```bash
# 需 PATH 中可用 node（Node.js 18+）
node tests/frontend/qa_webui_dom.mjs
```

也可以经 pytest 运行（`tests/test_webui.py::test_frontend_inline_scripts_wire_buttons_and_live_refresh`）：

```bash
./venv/Scripts/python.exe -m pytest tests/test_webui.py -q -k frontend_inline
```

仓库根通过**向上查找 `pyproject.toml`** 得到（见脚本内 `findRepoRoot`），因此脚本
被移动目录后依然可用，不依赖硬编码的相对层级。

### 边界与约定

- **不要**把本脚本放回被 `.gitignore` 忽略的目录（历史上它位于 `qa_verify/`，
  导致干净克隆 / CI 中脚本缺失、用例必然失败，且被 `pytest.mark.skipif` 掩盖为「跳过」）。
- 调用方（`tests/test_webui.py`）对「脚本存在」与「node 可用」使用**硬断言而非
  `pytest.skip`**：静默跳过会让前端行为长期无人验证。
- CI 的 test job 需提供 Node.js（见 `.github/workflows/ci.yml`）。

## 其它 ad-hoc 探针（未纳入版本控制，保持忽略）

以下脚本属于**临时探针**，不被任何受跟踪的测试 / 脚本 / 文档引用，故仍留在
`qa_verify/`（整体被 `.gitignore` 忽略），无需纳入本目录：

| 脚本 | 用途 | 处置 |
| --- | --- | --- |
| `qa_browser_realdom.mjs` | 真实浏览器 DOM 探针（依赖本机浏览器） | 保留 ignore；计划由 T15 Playwright 无头端到端取代 |
| `qa_ws_probe.mjs` / `qa_ws_probe2.mjs` | WebSocket 报文探针 | 同上 |

> 注：`qa_verify/qa_joint_debug.py`（Python 端到端调试脚本）被 `docs/` 与
> `tests/e2e/README.md` 以「本地调试工具」形式提及，属有意保留的 ad-hoc 脚本；
> 其可复用部分已提升为受跟踪的 `tests/e2e/qa_common.py`。
