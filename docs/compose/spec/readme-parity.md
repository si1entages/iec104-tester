---
feature: readme-parity
status: delivered
updated: 2026-09-24
branch: feature/readme-parity
commits: 684af0c..684af0c
---

# README 功能对齐 · Web 能力补齐 · 文档更新

## Report

**What was built** — 对照 README 补齐 Web 主站能力：组召唤 QOI、复位/测试/读/参数/文件 API 与界面控件；点表 YAML 导入导出、CSV（RFC 转义）、会话 JSON 导出；报文行 U/S/I + TypeID 摘要。重写 README/README_eng/requirements 以匹配 Web UI 现实（去掉 Qt/PySide6/legacy-ui）；修正 PROJECT、user_guide、api_reference 中的过时 GUI 描述。

**Verification** — `pytest tests/ -q` → **237 passed**。Review 后修复：参数/文件 UI 未接齐、QOI 文案错误（0→20）、CSV 未转义、PROJECT/docs 残留。

**Journey log**
1. README 功能盘点应先对「已删除 UI」与「CLI-only」能力分类，再决定 Web 化范围。
2. `file_name` 在引擎侧是 int，UI/API 契约需数值字段。
3. 总召唤 QOI=20，组召 1–23；UI 标注错误会导致脚本误用。

## [S1] Problem

README 描述已删除的 Qt GUI，且 Web 相对文档中的主站功能缺组召唤、复位、参数、文件、点表导入导出等。

## [S2] Design

新增 `/api/master/reset|test|read|param|file`、`/api/points/yaml`、`/api/export/*`；`gi` 支持 `qoi`。前端补文件目录/选择/召唤与参数下发。文档与 `requirements.txt` 对齐。

## [S3] Out of Scope

多站 Web 台、网络异常 Web 面板（保留 CLI）；完整报文解析。

## Tasks

- [x] T1: bridge+server 补 master 命令与点表/导出 API — acceptance: 新路由可调 (covers: S2)
- [x] T2: 前端主站命令栏/导入导出/报文摘要 — acceptance: 页面控件调用 API (covers: S2; depends: T1)
- [x] T3: tests 补新 API — acceptance: 新断言通过 (covers: S2; depends: T1)
- [x] T4: README/README_eng/requirements/pyproject 对齐现状 — acceptance: 无 Qt/PySide6/legacy-ui 残留 (covers: S2)
- [x] T5: 全量回归 + review + finalize — acceptance: 237 tests passed (covers: S2; depends: T3)
