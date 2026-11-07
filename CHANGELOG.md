# Changelog

本文件记录对外可见的功能/修复；版本号与 `pyproject.toml`、
`core/version.py`、`webui/frontend/package.json` 保持一致。

## [1.2.0] — 2026-11-07 (unreleased)

### Added

- **Web 测试中心**：浏览器内选择 `tests/scripts/*.yaml`，子进程隔离运行，
  实时日志、通过/失败汇总，HTML/JSON/TXT 报告在线下载
  （`/api/tests/*` + “自动化测试”页）。
- **Web 报文录制/回放**：开始/暂停/停止录制；录制文件列表与下载；
  一键导出 pcap/pcapng（Wireshark 可打开）；离线回放（播放/暂停/单步/倍速）
  与帧表（`/api/capture/*` + “报文抓包”页）。
- **冗余双通道 Web 配置与状态**：主站连接面板可启用备用前置机并查看
  活动通道、主/备在线状态、切换次数（`redundancy` 请求字段 + 状态字段）。
- **Web UI HTTPS**：`--web-tls-cert/--web-tls-key`；所有响应增加
  CSP / X-Frame-Options / Referrer-Policy / Permissions-Policy 安全头。
- `--version`：打印 `iec104-tester <version>` 并退出。
- 文件传输 5 项开放问题已用第三方 **lib60870-C v2.4.1** 从站实测回填
  （NOF/SCQ/DEACT/多节/FRQ-SRQ），原始记录见
  `docs/file_transfer_third_party_probe_2026-11-07.md`；真机窗口仍需复测。
- 前端覆盖率门禁（`@vitest/coverage-v8`）与 WebUI 独立覆盖率门禁（≥85%）。
- e2e：历史查询、网络模拟、AuthGate、中英切换。
- CI：`concurrency` 取消旧 run、Python 3.14 矩阵、夜间性能基准、
  PR 阶段 Linux onefile 打包 dry-run、Dependabot。

### Changed

- 版本号统一由 `core/version.py` 提供；新增版本一致性测试。
- README 增补 Web 测试中心、录制回放、冗余 UI、HTTPS 截图与说明。

### Fixed

- **文件传输与第三方从站互操作**（lib60870-C v2.4.1 实测）：
  - 文件命令改为 `F_SC_NA_1(122)+COT=FILE(13)`（旧 `F_SC_NB_1(127)+COT=ACT(6)`
    被静默忽略）；
  - 收到 `F_SR` 自动发 `SCQ=6` 节请求；`F_LS` 按 LSQ 回
    `F_AF(肯定文件/肯定节)`；
  - 主站不再发送非标准 `F_FR_NB(128)/F_SR_NB(129)` 确认；
  - CHS 改为按本节段数据校验，支持多节（第三方 800B/2 节实测完成）。
- 文档中 “TLS/冗余未实现”“i18n 剩余 20 文件/535 行” 等历史快照表述已加注
  当前状态，避免与实现漂移。

## [1.1.0] — 2026-11-07

### Added

- Web 网络异常模拟卡片、访问令牌认证（`--auth-token` / `--http-host`）。
- 历史库查询页；分支覆盖率 92%；`qa_full_flow` 进 CI。
- 全站中/英双语（阶段一 + 阶段二，迁移清单归零）。

## [1.0.0] — 2026-11-06

### Added

- 历史库查询 Web UI、一键诊断包、双平台发布流水线、TLS 传输加密、
  冗余双通道、互操作语料库、性能/长稳基准。
