# Security Policy

## Supported versions

| Version | Supported |
|------|-----------|
| 1.12.x | ✅ |
| 1.11.x | ✅ (security fixes) |
| ≤ 1.10 | ❌ |

## Reporting a vulnerability

请**不要**在公开 issue 中披露可利用细节。优先使用 GitHub 的
[Private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities)
（仓库 → Security → Report a vulnerability），或联系维护者私下沟通。

请尽量包含：

- 受影响版本 / 部署方式（Web UI、CLI、打包 exe）；
- 复现步骤与最小报文/请求；
- 影响判断（读取、命令下发、拒绝服务等）；
- 如可能，附修复建议。

我们会在确认后 7 天内给出初步响应，并在修复发布后致谢（除非要求匿名）。

## Security model & boundaries

- 默认只监听 `127.0.0.1`。使用 `--http-host 0.0.0.0` 暴露到局域网时，
  **必须**同时设置 `--auth-token`（或环境变量 `IEC104_AUTH_TOKEN`）/
  `--auth-config`。自 v1.11.0 起这由代码强制：非回环且无认证时服务
  **拒绝启动**（退出码 2），不再只是告警。仅在物理隔离的测试网确需
  无认证暴露时，才显式加 `--allow-insecure`。
- Web API 令牌只从 `Authorization: Bearer` / `X-Auth-Token` 请求头读取；
  REST 端点不再接受 `?token=`，避免令牌落入浏览器历史、代理日志与 Referer。
  **残余风险**：WebSocket 握手无法自定义请求头，仍使用 `?token=`，且
  `/api/auth` 公开探测端点为保留 `/app/?token=` 首次导入流程也接受 query；
  请勿在不可信网络复用该令牌，并优先启用 HTTPS。
- 所有 `/api/*` 与 `/ws` 请求做 Origin 同源校验（带 Origin 头时），
  拒绝跨站 WebSocket 劫持（CSWSH）；认证失败/越权/跨源拒绝写入
  `security` 类别日志，可过滤但不包含令牌本身。
- Web UI 可选用 `--web-tls-cert/--web-tls-key` 启用 HTTPS；局域网/跨主机
  部署建议始终启用，避免令牌与遥控命令明文传输。
- 控制链路 TLS（`--tls*`）只覆盖 IEC 62351 的传输层部分，**不等于
  IEC 62351 合规**，边界见 [`docs/tls.md`](docs/tls.md)。
- 本工具用于协议测试与联调，不应直接作为生产 SCADA 网关部署。

## Dependency security

- 运行时依赖精确锁见 `requirements.lock`；`requirements.txt` / `pyproject.toml`
  只给最低下界用于跨 Python 版本兼容矩阵。
- CI 的 `dependency-audit` job 每次 push 跑 `pip-audit -r requirements.lock`
  （任何已知漏洞即失败）与 `npm audit --audit-level=high`（报告式，不因镜像
  未实现 advisory API 而阻断）。2026-11-12 首次接入时发现 `aiohttp 3.14.3`
  有 8 个已知 CVE，已升级到 `3.14.4` 并复验 0 漏洞。
- Dependabot 每周检查 pip / npm / GitHub Actions 依赖；发布包由
  `.github/workflows/release.yml` 在 Windows/Linux 构建并生成 SHA256SUMS。
