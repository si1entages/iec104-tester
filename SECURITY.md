# Security Policy

## Supported versions

| Version | Supported |
|------|-----------|
| 1.2.x | ✅ |
| 1.1.x | ✅ (security fixes) |
| ≤ 1.0 | ❌ |

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
  必须同时设置 `--auth-token`（或环境变量 `IEC104_AUTH_TOKEN`）。
- Web UI 可选用 `--web-tls-cert/--web-tls-key` 启用 HTTPS；局域网/跨主机
  部署建议始终启用，避免令牌与遥控命令明文传输。
- 控制链路 TLS（`--tls*`）只覆盖 IEC 62351 的传输层部分，**不等于
  IEC 62351 合规**，边界见 [`docs/tls.md`](docs/tls.md)。
- 本工具用于协议测试与联调，不应直接作为生产 SCADA 网关部署。

## Dependency security

Dependabot 每周检查 pip / npm / GitHub Actions 依赖；发布包由
`.github/workflows/release.yml` 在 Windows/Linux 构建并生成 SHA256SUMS。
