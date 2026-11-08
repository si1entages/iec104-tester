/**
 * 报文查看器悬停翻译 e2e（回归：2026-11-07 悬停恒显示「翻译失败」）。
 *
 * 缺陷根因是前后端响应结构约定不一致：后端（契约 §2.9）返回扁平
 * `{ok, format, segments}`，前端却读取 `r.translation`，于是永远走失败分支。
 * 两侧单测各自按自己的假设 mock，只有「真实后端 + 真实浏览器操作」能发现。
 *
 * 本用例走完整链路：子站监听 → 主站连接产生真实报文 → 打开报文查看器 →
 * 悬停 HEX 单元格 → 断言 `/api/frames/decode` 返回扁平结构且 Popover 渲染分段。
 */
import { expect, test } from '@playwright/test'

import {
  IEC_PORT,
  MASTER,
  SLAVE,
  gotoApp,
  injectPoints,
  stopEngines,
  waitForStatus,
} from './helpers'

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  await stopEngines(request)
  await injectPoints(request, MASTER)
  await injectPoints(request, SLAVE)
  // 子站先监听，主站连接才有对端并产生 STARTDT / 总召唤等真实帧
  const slave = await request.post(`${SLAVE}/api/slave/start`, {
    data: { host: '0.0.0.0', port: IEC_PORT, addr: 1 },
  })
  expect((await slave.json()).ok).toBeTruthy()
  await waitForStatus(request, SLAVE, (s) => s.started === true)

  const master = await request.post(`${MASTER}/api/master/start`, {
    data: { host: '127.0.0.1', port: IEC_PORT, addr: 1 },
  })
  expect((await master.json()).ok).toBeTruthy()
  await waitForStatus(request, MASTER, (s) => s.running === true)
})

test.afterAll(async ({ request }) => {
  await stopEngines(request)
})

test('悬停报文 HEX → 真实后端逐段翻译（不再显示「翻译失败」）', async ({ page }) => {
  await gotoApp(page, MASTER, '主站工作台')

  const cell = page.locator('.hex-wrap').first()
  await expect(cell).toBeVisible({ timeout: 30_000 })

  // 悬停 300ms 后才发请求；先挂监听再 hover，避免竞态
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes('/api/frames/decode?hex=') && r.status() === 200,
      { timeout: 15_000 },
    ),
    cell.hover(),
  ])

  // 契约 §2.9：扁平结构，不是 {translation: {...}}
  const body = (await response.json()) as {
    ok: boolean
    format?: string
    segments?: { title: string; lines: string[] }[]
    translation?: unknown
  }
  expect(body.ok).toBe(true)
  expect(body.translation).toBeUndefined()
  expect(body.format).toMatch(/^[ISU?]$/)
  expect(body.segments?.length ?? 0).toBeGreaterThan(0)

  // UI 真实渲染：Popover 出现分段标题与帧类型行，且没有失败文案
  await expect(page.getByText('APCI（传输控制头）')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText(/帧/).first()).toBeVisible()
  await expect(page.getByText(/翻译失败/)).toHaveCount(0)
})
