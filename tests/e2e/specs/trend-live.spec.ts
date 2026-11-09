/**
 * 趋势图端到端（像素级）：选「真正在变化的点」→ 加入趋势 → 切趋势图页签，
 * 断言画布上出现曲线系列色像素（ECharts 默认 #5470c6）。
 *
 * 背景（2026-11-10 真机联调）：用户反馈「看不到趋势图」——根因是连接断开/选中了
 * 不变化的点时整条曲线只有加入瞬间的一个数据点标记。本用例锁死「数据流动 +
 * 选对点」时曲线必须真的画出来；单采样态由界面的 trend.waiting 提示自解释。
 */
import { expect, test } from '@playwright/test'

import { COMBINED } from './helpers'

test('趋势图：选点加入趋势后画布必须真的画东西', async ({ page, request }) => {
  test.setTimeout(150_000)

  // 前置：子站监听 + 主站连接（走 UI 同款 API，让 WS 有真实数据流动）
  await request.post(`${COMBINED}/api/master/stop`, { data: {} })
  await request.post(`${COMBINED}/slave/api/slave/stop`, { data: {} })
  const slaveStart = await request.post(`${COMBINED}/slave/api/slave/start`, {
    data: { host: '127.0.0.1', port: 24315, addr: 1 },
  })
  expect((await slaveStart.json()).ok).toBeTruthy()
  const masterStart = await request.post(`${COMBINED}/api/master/start`, {
    data: { host: '127.0.0.1', port: 24315, addr: 1 },
  })
  expect((await masterStart.json()).ok).toBeTruthy()
  await expect
    .poll(async () => (await (await request.get(`${COMBINED}/api/status`)).json()).state, { timeout: 15_000 })
    .toBe('Running')

  await page.goto(`${COMBINED}/app/?kit=carbon#/master`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 20_000 })

  // 真实用户流程：数据先流动（值变化 → 自动学习补点），再选中变化的点加入趋势
  for (const v of [11.5, 42.5, 7.25]) {
    await request.post(`${COMBINED}/slave/api/slave/yc`, { data: { ioa: 101, value: v } })
    await page.waitForTimeout(900)
  }
  const autoRow = page.locator('[data-testid="point-row"]').filter({ hasText: '遥测101' }).first()
  await autoRow.waitFor({ state: 'visible', timeout: 15_000 })
  await autoRow.click()
  await page.getByRole('button', { name: /加入趋势/ }).click()

  // 加入趋势之后再变化几次：曲线应有多个采样点（画出折线而非单点）
  for (const v of [30.75, 55.5, 3.25, 61.5, 18.75, 48.5]) {
    await request.post(`${COMBINED}/slave/api/slave/yc`, { data: { ioa: 101, value: v } })
    await page.waitForTimeout(900)
  }

  // 切到趋势图页签
  await page.locator('.cds--tabs__nav-link').filter({ hasText: /趋势图/ }).click()
  const canvas = page.locator('[role="tabpanel"]:not([hidden]) canvas')
  await expect(canvas).toBeVisible({ timeout: 15_000 })
  await page.waitForTimeout(800)

  const counts = await canvas.evaluate((c) => {
    const ctx = c.getContext('2d')
    if (!ctx) return { series: -1, any: -1 }
    const data = ctx.getImageData(0, 0, c.width, c.height).data
    let series = 0
    let line = 0
    let any = 0
    for (let i = 0; i < data.length; i += 16) {
      if (data[i + 3] === 0) continue
      any++
      const r = data[i]
      const g = data[i + 1]
      const b = data[i + 2]
      // ECharts 默认系列色 #5470c6（容差 ±24）
      if (Math.abs(r - 84) <= 24 && Math.abs(g - 112) <= 24 && Math.abs(b - 198) <= 24) {
        series++
        if (i / 4 / c.width > 0.15) line++ // 排除顶部图例区（前 15% 高度）
      }
    }
    return { series, line, any }
  })
  console.log(`[trend-live] 非透明样本=${counts.any} 曲线区像素样本=${counts.line}`)
  expect(counts.line, '趋势图绘图区没有曲线像素（曲线没画出来）').toBeGreaterThan(20)
})
