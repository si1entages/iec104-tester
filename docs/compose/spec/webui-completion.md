---
feature: webui-completion
status: delivered
updated: 2026-09-24
branch: feature/webui-completion
commits: 23eede7..23eede7
---

# Web UI 功能补齐 · 自动化测试 · 优化

## Report

**What was built** — 扩展 Web 后端与界面：主站增加时钟同步/累计量召 API 与按钮；子站增加 ResponseBehavior 注入、自动模拟开关、点表批量启用/禁用/改组。`EngineBridge` 在启动子站时应用此前暂存的响应配置；`status()` 用缓存点数并统计 WS 背压丢弃次数。前端为这些能力提供精简表单。

**Verification** — `pytest tests/ -q` → **235 passed**（含 11 项 `tests/test_webui.py`）。Review 后修复：`batch_points` 非法 action/缺 group 假成功、YC 断言过弱、硬编码端口改为 `_free_port()`、去掉私有 `_publish` 与双重事件广播。

**Journey log**
1. pytest-asyncio STRICT 需 `@pytest_mark.asyncio` + `pytest_asyncio.fixture`。
2. TestClient.post 需 `json=` 关键字，不能传位置 dict。
3. 真连 e2e 在 Web 层同样要用临时端口并等待 slave `is_running`。
4. 批量改点依赖 `PointTable` 与 `SlaveEngine` 同一实例，无独立同步 API。
5. Review 假成功路径（group=None）比 happy path 更值得先测。

## [S1] Problem

Web UI 可启动主站/子站，但引擎能力未充分暴露、无 Web 层自动化测试、热路径状态计算偏重。

## [S2] Design

| Method | Path | 行为 |
|--------|------|------|
| POST | `/api/master/clock` | 主站时钟同步 |
| POST | `/api/master/ci` | 累计量召唤 |
| POST | `/api/slave/response` | ResponseBehavior 字典（未启动可暂存） |
| POST | `/api/slave/sim` | 自动模拟启停 |
| POST | `/api/points/batch` | enable/disable/group；非法入参 `ok:false` |

优化：`_publish` 队列满丢最旧并计 `dropped`；`status().points` 用 `_point_count` 缓存。

测试：`tests/test_webui.py` 覆盖静态资源、schema、子站生命周期、主站错误路径、真连 GI/clock/ci、批量、WS 快照、暂存响应、模拟开关、背压 dropped。

## [S3] Out of Scope

录制回放、多站、趋势、鉴权、协议层改动。

## Tasks

- [x] T1: bridge 扩展 clock/ci/response/sim/batch — acceptance: 对应方法可调用并返回 ok (covers: S2)
- [x] T2: server 路由接上扩展 API — acceptance: HTTP 可调通 (covers: S2; depends: T1)
- [x] T3: 前端子站响应注入 + 主站时钟/CI + 批量条 — acceptance: 控件调用 API (covers: S2; depends: T2)
- [x] T4: tests/test_webui.py 自动化 — acceptance: pytest tests/test_webui.py 全绿 (covers: S2)
- [x] T5: dropped 计数、status 缓存 — acceptance: 有注释且测试不回归 (covers: S2)
- [x] T6: 全量回归 + review 修复 — acceptance: 235 tests passed (covers: S2; depends: T4)
