/**
 * T15 子站交互 e2e：手动置数（YX/YC/YM/STEP，STEP 夹紧 -64..63）→ 应答行为配置下发。
 */
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import {
  IEC_PORT,
  SLAVE,
  capturePosts,
  gotoApp,
  injectPoints,
  stopEngines,
  type CapturedRequest,
} from './helpers'

test.describe.configure({ mode: 'serial' })

async function openSlave(page: Page): Promise<void> {
  await gotoApp(page, SLAVE, '子站工作台')
  // 手动置数面板在 Tabs 内，先切到该页签
  await page.getByRole('tab', { name: '手动置数' }).click()
  await panelInput(page, '目标 IOA').waitFor()
}

/** 活动页签内的开关（非激活 Tabs 面板也在 DOM 里，必须限定活动面板） */
function activePane(page: Page) {
  return page.locator('.ant-tabs-tabpane-active')
}

/** 手动置数面板内的带前缀输入框 */
function panelInput(page: Page, prefix: string) {
  return page
    .locator('.ant-input-number-affix-wrapper')
    .filter({ hasText: prefix })
    .locator('input')
}

function findPost(posts: CapturedRequest[], path: string): CapturedRequest {
  const hit = posts.filter((p) => p.path === path)
  expect(hit, `未捕获到 POST ${path}，实际: ${JSON.stringify(posts.map((p) => p.path))}`).toHaveLength(1)
  return hit[0]
}

test.beforeAll(async ({ request }) => {
  await injectPoints(request, SLAVE)
  const res = await request.post(`${SLAVE}/api/slave/start`, {
    data: { host: '0.0.0.0', port: IEC_PORT, addr: 1 },
  })
  expect((await res.json()).ok).toBeTruthy()
})

test.afterAll(async ({ request }) => {
  await stopEngines(request)
})

test('YX 置数：请求体 {ioa, value} 正确', async ({ page }) => {
  await openSlave(page)
  const posts = capturePosts(page)
  await page.getByText('遥信 YX', { exact: true }).click()
  await panelInput(page, '目标 IOA').fill('1')
  // 默认 ON → 点一次切到 OFF，断言 value=false（活动页签内唯一的开关）
  await activePane(page).locator('.ant-switch').first().click()
  await page.getByRole('button', { name: '下发置数' }).click()
  const body = findPost(posts, '/api/slave/yx').body!
  expect(body.ioa).toBe(1)
  expect(body.value).toBe(false)
})

test('YC 置数：浮点值透传', async ({ page }) => {
  await openSlave(page)
  const posts = capturePosts(page)
  await page.getByText('遥测 YC', { exact: true }).click()
  await panelInput(page, '目标 IOA').fill('101')
  await panelInput(page, '值').fill('12.34')
  await page.getByRole('button', { name: '下发置数' }).click()
  const body = findPost(posts, '/api/slave/yc').body!
  expect(body.ioa).toBe(101)
  expect(Number(body.value)).toBeCloseTo(12.34, 3)
})

test('YM 置数：整数值', async ({ page }) => {
  await openSlave(page)
  const posts = capturePosts(page)
  await page.getByText('电度 YM', { exact: true }).click()
  await panelInput(page, '目标 IOA').fill('301')
  await panelInput(page, '值').fill('7')
  await page.getByRole('button', { name: '下发置数' }).click()
  const body = findPost(posts, '/api/slave/ym').body!
  expect(body.ioa).toBe(301)
  expect(body.value).toBe(7)
})

test('STEP 置数：输入 200 被夹紧到 63（-64..63 红线）', async ({ page }) => {
  await openSlave(page)
  const posts = capturePosts(page)
  await page.getByText('步位置 STEP', { exact: true }).click()
  await panelInput(page, '目标 IOA').fill('401')
  const valueInput = panelInput(page, '值')
  await valueInput.fill('200')
  await page.getByRole('button', { name: '下发置数' }).click()
  const body = findPost(posts, '/api/slave/step').body!
  expect(body.ioa).toBe(401)
  expect(body.value).toBe(63) // UI 夹紧到上界
})

test('应答行为配置：wrong_cot + drop_rate 请求体正确', async ({ page }) => {
  await openSlave(page)
  const posts = capturePosts(page)
  // 应答行为面板在另一个页签里
  await page.getByRole('tab', { name: '应答行为' }).click()
  const wrongCot = page.getByRole('switch', { name: '返回错误 COT（wrong_cot）' })
  await wrongCot.waitFor()
  await wrongCot.click()
  // 丢帧比例 drop_rate：错误注入分组里的第一个数字输入框
  const dropRate = activePane(page).locator('.ant-input-number input').first()
  await dropRate.fill('0.5')
  await page.getByRole('button', { name: '应用配置' }).click()
  const body = findPost(posts, '/api/slave/response').body!
  const errors = body.errors as Record<string, unknown>
  expect(errors.wrong_cot).toBe(true)
  expect(Number(errors.drop_rate)).toBeCloseTo(0.5, 5)
})
