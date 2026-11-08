/**
 * T15 契约告警 e2e：伪造 schemaVersion 不匹配 → 降级告警横幅出现、外壳不崩溃。
 *
 * 手段：拦截 HTTP（/api/schema、/api/status 返回 99），并用 routeWebSocket 吞掉
 * 服务端 WS 快照（否则真实 snapshot 会把告警清掉，横幅一闪而过无法断言）。
 */
import { expect, test } from '@playwright/test'

import { MASTER , appUrl } from './helpers'

test('契约版本不匹配 → 横幅告警 + 外壳存活不崩溃', async ({ page }) => {
  await page.route('**/api/schema', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        schemaVersion: 99,
        wsKinds: ['snapshot', 'frame', 'event', 'log'],
        wsSchemaKey: 'e2e-fake',
      }),
    }),
  )
  await page.route('**/api/status', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        role: 'master',
        running: false,
        dropped: 0,
        schemaVersion: 99,
      }),
    }),
  )
  // 吞掉 WS 服务端消息：快照不落地，降级告警保持可见
  await page.routeWebSocket('**/ws', () => {})

  await page.goto(appUrl(MASTER), { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('契约版本不匹配（降级运行）')).toBeVisible({ timeout: 15_000 })
  // 外壳存活：侧边菜单仍在，可正常切换页面（不白屏）
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: '日志' })).toBeVisible()
  await page.locator('.pf-v6-c-nav__link').filter({ hasText: '日志' }).click()
  await expect(page.getByText('日志', { exact: true }).first()).toBeVisible()
})

test('正常后端无告警横幅（对照）', async ({ page }) => {
  await page.goto(appUrl(MASTER), { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: '主站工作台' })).toBeVisible()
  await expect(page.getByText('契约版本不匹配（降级运行）')).toHaveCount(0)
})
