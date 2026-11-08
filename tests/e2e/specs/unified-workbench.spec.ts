/**
 * 单页工作台 e2e：主站/子站分别作为侧边菜单，在同一个 SPA 页面内切换。
 *
 * 合并模式（单进程双角色、一个 8767 端口）：
 *  - 两个工作台菜单都可用；
 *  - 子站页面**原生渲染**，不再有 iframe / iframe 滚动条；
 *  - 始终只有一个浏览器页。
 */
import { expect, test } from '@playwright/test'

import { COMBINED , appUrl } from './helpers'

test('主站/子站分别作为菜单，在同一个页面切换（无 iframe）', async ({ page }) => {
  const pointRequests: string[] = []
  page.on('request', (req) => {
    if (req.url().includes('/api/points')) {
      pointRequests.push(new URL(req.url()).pathname)
    }
  })

  await page.goto(appUrl(COMBINED), { waitUntil: 'domcontentloaded' })

  // 侧边栏两个工作台入口（不是一个菜单 + 页内页签）
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: /主站工作台/ })).toBeVisible()
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: /子站工作台/ })).toBeVisible()

  // 默认显示主站工作台
  await expect(page.getByText('连接与命令').first()).toBeVisible({ timeout: 15_000 })
  const masterTable = await page
    .locator('.pf-v6-c-card')
    .filter({ has: page.locator('[data-testid="points-scroll"]') })
    .first()
    .boundingBox()
  const masterSide = await page.locator('.pf-v6-c-card').filter({ hasText: '命令面板' }).first().boundingBox()
  expect(masterTable && masterSide).toBeTruthy()
  // 与子站工作台一致的排布：命令面板整行放在点表下方
  expect(masterSide!.y).toBeGreaterThanOrEqual(masterTable!.y + masterTable!.height - 1)
  expect(masterSide!.width).toBeGreaterThanOrEqual(masterTable!.width - 1)
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 15_000 })
  const masterPointLoads = pointRequests.filter((p) => p === '/api/points').length

  // 点「子站工作台」菜单：同一页面内原生渲染子站工作台（无 iframe）
  await page.locator('.pf-v6-c-nav__link').filter({ hasText: /子站工作台/ }).click()
  await expect(page.getByText('子站启动与状态')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('tab', { name: '手动置数' })).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(0)

  // 子站页在 PF 版为「点表 + 下方页签面板」布局：断言点表与页签都可见
  await expect(page.locator('[data-testid="points-scroll"]')).toBeVisible()
  await expect(page.getByRole('tab', { name: '应答行为' })).toBeVisible()

  // 仍是一个浏览器页
  expect(page.context().pages()).toHaveLength(1)

  // 切回主站工作台：点表应命中缓存，不再重新请求 /api/points
  await page.locator('.pf-v6-c-nav__link').filter({ hasText: /主站工作台/ }).click()
  await expect(page.getByText('连接与命令').first()).toBeVisible()
  await page.waitForTimeout(600)
  expect(pointRequests.filter((p) => p === '/api/points').length).toBe(masterPointLoads)
})
