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

/**
 * 端口整体平移（与 specs/helpers.ts 的 E2E_PORT_OFFSET 同源）：
 * 本机已有运行中的实例占用 8765~8768 时，用 `E2E_PORT_OFFSET=10` 错开，
 * 不必关掉正在使用的应用（两端必须使用同一个值）。
 */
const OFF = Number(process.env.E2E_PORT_OFFSET ?? 0)
const PORT = (base: number): number => base + OFF

// CI 的英文 Windows 默认控制台代码页是 cp1252：后端启动日志含中文时
// charmap 编码直接 UnicodeEncodeError 崩溃（webServer 启动失败）。
// 强制 Python 子进程走 UTF-8（本地/Linux 无副作用），stdio 与文件系统编码一并覆盖。
const SERVER_ENV = {
  ...process.env,
  PYTHONUTF8: '1',
  PYTHONIOENCODING: 'utf-8',
}

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
  // 视觉基线按平台分目录（字体渲染差异），Windows 基线在 __screenshots__/win32
  snapshotPathTemplate: '{testDir}/__screenshots__/{platform}/{arg}{ext}',
  use: {
    headless: true,
    channel: process.env.E2E_CHANNEL ?? 'msedge',
    viewport: { width: 1680, height: 950 },
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  webServer: [
    {
      command: `${PY} app.py --mode slave --no-browser --http-port ${PORT(8766)}`,
      url: `http://127.0.0.1:${PORT(8766)}/api/status`,
      cwd: ROOT,
      env: SERVER_ENV,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `${PY} app.py --mode master --no-browser --http-port ${PORT(8765)}`,
      url: `http://127.0.0.1:${PORT(8765)}/api/status`,
      cwd: ROOT,
      env: SERVER_ENV,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // 合并模式（单进程双角色、一个 HTTP 端口）：单页工作台用例
      command: `${PY} app.py --mode both --no-browser --no-history --http-port ${PORT(8767)}`,
      url: `http://127.0.0.1:${PORT(8767)}/api/status`,
      cwd: ROOT,
      env: SERVER_ENV,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // 桥模式（T74）：UI 上配置启停/观察；上游在用例内起 echo 服务
      command: `${PY} app.py --mode bridge --no-browser --http-port ${PORT(8769)}`,
      url: `http://127.0.0.1:${PORT(8769)}/api/status`,
      cwd: ROOT,
      env: SERVER_ENV,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // 视觉基线专用单角色服务：无引擎/无帧/无历史，页面内容可复现
      command: `${PY} app.py --mode master --no-browser --no-history --http-port ${PORT(8768)}`,
      url: `http://127.0.0.1:${PORT(8768)}/api/status`,
      cwd: ROOT,
      env: SERVER_ENV,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
