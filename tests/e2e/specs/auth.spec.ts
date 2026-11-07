/**
 * 访问令牌闸门 e2e（D3）：无令牌停留输入框，输入后加载主界面。
 *
 * 后端未启用 --auth-token；这里用路由拦截模拟「服务端已启用认证」，
 * 验证 AuthGate 的探测、输入、localStorage 记忆与请求头携带。
 */
import { expect, test } from '@playwright/test'

import { MASTER } from './helpers'

test('AuthGate：令牌探测、输入与持久化', async ({ page }) => {
  await page.route('**/api/auth', async (route) => {
    const req = route.request()
    const headerToken = req.headers()['x-auth-token'] ?? ''
    const urlToken = new URL(req.url()).searchParams.get('token') ?? ''
    const valid = headerToken === 'e2e-token' || urlToken === 'e2e-token'
    await route.fulfill({ json: { ok: true, required: true, valid } })
  })

  await page.goto(`${MASTER}/app/`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('需要访问令牌')).toBeVisible()
  await expect(page.getByPlaceholder('访问令牌')).toBeVisible()

  await page.getByPlaceholder('访问令牌').fill('e2e-token')
  await page.getByRole('button', { name: /进\s*入/ }).click()

  // 页面会 reload；reload 后 /api/auth 带 X-Auth-Token 头 → valid=true
  await expect(page.getByRole('menuitem', { name: '主站工作台' })).toBeVisible({
    timeout: 20_000,
  })
  const stored = await page.evaluate(() => localStorage.getItem('iec104_token'))
  expect(stored).toBe('e2e-token')
})
