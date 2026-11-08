/**
 * 网络异常模拟卡片 e2e（D3）：状态展示、启停开关、预设应用请求体。
 *
 * GET/POST 全部走路由拦截，保证不依赖真实引擎状态；断言点是「UI 控件 →
 * /api/simulation 请求体」，与后端单测（simulation endpoints）互补。
 */
import { expect, test } from '@playwright/test'

import { MASTER, gotoApp } from './helpers'

const CONDITION = {
  delay_ms: 0,
  delay_variance_ms: 0,
  loss_rate: 0,
  duplicate_rate: 0,
  corrupt_rate: 0,
  corrupt_bits: 1,
  reorder_rate: 0,
  reorder_window: 5,
  disconnect_rate: 0,
  disconnect_duration_s: 3,
  bandwidth_bps: 0,
  direction: 'both',
  active: false,
}

const STATUS = {
  ok: true,
  enabled: false,
  installed: false,
  active: false,
  describe: '(none)',
  condition: CONDITION,
  stats: {},
  presets: ['clean', 'poor_wifi', 'congested'],
}

test('网络模拟卡片：启停与预设请求体正确', async ({ page }) => {
  const posts: Record<string, unknown>[] = []

  await page.route('**/api/simulation', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: STATUS })
      return
    }
    posts.push(route.request().postDataJSON() as Record<string, unknown>)
    await route.fulfill({ json: { ok: true, status: STATUS } })
  })

  await gotoApp(page, MASTER, '状态总览')
  const card = page.locator('.pf-v6-c-card').filter({ hasText: '网络异常模拟' }).first()
  await expect(card).toBeVisible()
  await expect(card.getByText('已停用')).toBeVisible()
  await expect(card.getByText('引擎未启动')).toBeVisible()

  // 开关：启用 → {enabled: true}
  const switchReq = page.waitForRequest(
    (req) => req.url().endsWith('/api/simulation') && req.method() === 'POST',
  )
  await card.locator('#pf-sim-enable').click({ force: true })
  await switchReq
  await expect.poll(() => posts.some((p) => p.enabled === true)).toBe(true)

  // 预设：选择「网络拥塞」→ 应用 → {enabled: false, preset: 'congested'}
  await card.locator('select').first().selectOption('congested')
  const presetReq = page.waitForRequest(
    (req) =>
      req.url().endsWith('/api/simulation') &&
      req.method() === 'POST' &&
      (req.postDataJSON() as Record<string, unknown>)?.preset === 'congested',
  )
  await card.getByRole('button', { name: '应用预设' }).click()
  await presetReq
  expect(posts.some((p) => p.enabled === false && p.preset === 'congested')).toBe(true)
})
