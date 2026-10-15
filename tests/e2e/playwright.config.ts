/**
 * T15 前端交互 e2e（Playwright，headless）。
 *
 * 与 `tests/e2e/qa_*.py` 的惯例保持一致：
 *  - 独立脚本范式（不进 pytest 收集）；
 *  - 由本配置自行拉起后端：主站(8765) / 子站(8766)，进程由 Playwright webServer 托管，
 *    跑完自动回收；`reuseExistingServer` 复用手动启动的服务（CI 上不复用）。
 *
 * 本地一条命令复现（在仓库根目录）：
 *   npx playwright test --config tests/e2e/playwright.config.ts
 *
 * 浏览器：默认用系统 Edge（channel=msedge，无需额外下载）；CI 上用
 * E2E_CHANNEL=chromium + `npx playwright install chromium`。
 */
import { defineConfig } from '@playwright/test'
import path from 'node:path'

// 关键：屏蔽系统代理（与 qa_*.py 的做法一致）——否则 Windows 下 Playwright 的
// 可用性探测会经代理发出，对未启动的端口误判 200，导致 webServer 不被拉起
for (const k of [
  'http_proxy',
  'https_proxy',
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'all_proxy',
  'ALL_PROXY',
  'no_proxy',
  'NO_PROXY',
]) {
  delete process.env[k]
}

// Windows 下 webServer 命令由 cmd.exe 执行：程序路径必须用反斜杠（正斜杠会被当参数吞掉）
const PY = process.env.E2E_PY ?? (process.platform === 'win32' ? 'venv\\Scripts\\python.exe' : 'venv/bin/python')
// webServer 的 cwd 默认是配置文件所在目录，这里显式指回仓库根（app.py 位置）
const ROOT = path.resolve(__dirname, '..', '..')

export default defineConfig({
  testDir: path.resolve(__dirname, 'specs'),
  outputDir: path.resolve(__dirname, '.playwright-artifacts'),
  timeout: 60_000,
  globalTimeout: 15 * 60_000,
  expect: { timeout: 15_000 },
  // 串行：主/子站引擎共用 IEC 2404，并行会互抢端口造成假失败
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    headless: true,
    channel: process.env.E2E_CHANNEL ?? 'msedge',
    viewport: { width: 1680, height: 950 },
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  webServer: [
    {
      command: `${PY} app.py --mode slave --no-browser`,
      url: 'http://127.0.0.1:8766/api/status',
      cwd: ROOT,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `${PY} app.py --mode master --no-browser`,
      url: 'http://127.0.0.1:8765/api/status',
      cwd: ROOT,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
