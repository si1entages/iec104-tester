---
feature: webui-refactor
status: delivered
updated: 2026-09-24
branch: feature/webui-refactor
commits: 11110b2..11110b2
---

# Web UI 架构优化（Bridge 拆分 · 点表同步 · 契约）

## Report

**What was built** — 将 `EngineBridge` 拆为 `EventBus`（订阅/环形缓冲/背压）、`PointService`（快照/批量/YAML/CSV + `sync_to_engine`/`rebuild_store`）、`EngineSession`（启停与命令门面）；`EngineBridge` 保持对外 API 形状。批量改点不再调用破坏性的 `init_from_point_table`，仅导入点表时 `rebuild_store`。新增 `webui/api_contract.md` 与 `static/js/api.js` 路径常量表。

**Verification** — `pytest tests/ -q` → **239 passed**（含 CSV 实时值、`set_response` 角色守卫、批量不重置实时值回归）。Review 后修复：CSV 丢实时值、master 调 `set_response` 崩溃、批量误重置 live DB、`ensure_demo_points`/stop 事件回归。

**Journey log**
1. `RealtimeDB.init_from_point_table` 是破坏性重建，不能当通用 sync。
2. 仅 `SlaveEngine` 有 `set_response_behavior`。
3. 拆分时「保持 HTTP 行为」要用回归测锁定（导出实时值、错误 JSON）。
4. `api.js` 需被页面加载才不算孤儿模块。

## [S1] Problem

`EngineBridge` 职责过重；点表隐式共享无显式同步；HTTP 契约无文档。

## [S2] Design

`webui/{events,points,session}.py` + 薄 `bridge.py`；`sync_to_engine` 不重置 live 值；`import_yaml` 才 `rebuild_store`；错误形状不变。

## [S3] Out of Scope

录制/多站 Web 化；TS 重写；OpenAPI 生成。

## Tasks

- [x] T1: 抽出 EventBus — acceptance: dropped 行为与测试一致 (covers: S2)
- [x] T2: 抽出 PointService + sync_to_engine — acceptance: 批量不重置 live 值 (covers: S2)
- [x] T3: 抽出 EngineSession 命令门面 — acceptance: bridge 变薄，HTTP 行为不变 (covers: S2)
- [x] T4: api_contract.md + app.js/api.js — acceptance: 契约文件与路由一致，页面加载 api.js (covers: S2)
- [x] T5: 测试与全量回归 — acceptance: 239 tests passed (covers: S2)
- [x] T6: review + finalize — acceptance: critical 已修 (covers: S2; depends: T5)
