/**
 * T15 子站交互 e2e：手动置数（YX/YC/YM/STEP，STEP 夹紧 -64..63）→ 应答行为配置下发。
 */
import path from 'node:path'

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

/** 活动页签容器（PF Tabs 同样使用 role=tabpanel） */
function activePane(page: Page) {
  return page.getByRole('tabpanel')
}

/** 手动置数面板内的输入框（PF FormGroup 的 label 绑定 fieldId） */
function panelInput(page: Page, label: string) {
  return page.getByLabel(label, { exact: true })
}

/** 置数类型：PF 用原生 select */
async function pickKind(page: Page, kind: string): Promise<void> {
  await page.locator('#pf-msp-kind').selectOption(kind)
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
  await pickKind(page, 'YX')
  await panelInput(page, '目标 IOA').fill('1')
  // 切到 OFF，断言 value=false
  await page.locator('#pf-msp-yx').selectOption('off')
  await page.getByRole('button', { name: '下发置数' }).click()
  const body = findPost(posts, '/api/slave/yx').body!
  expect(body.ioa).toBe(1)
  expect(body.value).toBe(false)
})

test('YC 置数：浮点值透传', async ({ page }) => {
  await openSlave(page)
  const posts = capturePosts(page)
  await pickKind(page, 'YC')
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
  await pickKind(page, 'YM')
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
  await pickKind(page, 'STEP')
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
  await wrongCot.click({ force: true })
  // 丢帧比例 drop_rate：错误注入分组（默认展开）
  const dropRate = page.locator('#pf-rp-droprate')
  await dropRate.fill('0.5')
  await page.getByRole('button', { name: '应用配置' }).click()
  const body = findPost(posts, '/api/slave/response').body!
  const errors = body.errors as Record<string, unknown>
  expect(errors.wrong_cot).toBe(true)
  expect(Number(errors.drop_rate)).toBeCloseTo(0.5, 5)
})

test('点表提示文案完整可见（不被标题栏裁掉）', async ({ page }) => {
  await openSlave(page)
  const hint = page.getByTestId('points-hint')
  await expect(hint).toBeVisible()
  await expect(hint).toHaveText('单击行以选中并手动置数')
  // 文本没有被容器裁切：内容宽度不超过可视宽度
  expect(await hint.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
})

test('模拟控制：YX/YC 可独立开启（只开 YX 时请求 yc_enabled=false）', async ({ page }) => {
  await openSlave(page)
  const posts = capturePosts(page)
  await page.getByRole('tab', { name: '模拟控制' }).click()

  const yx = page.locator('#pf-sim-yx')
  const yc = page.locator('#pf-sim-yc')
  await yx.waitFor()
  await expect(yx).toBeChecked()
  await expect(yc).toBeChecked()
  await yc.click({ force: true })
  await expect(yc).not.toBeChecked()

  await page.getByRole('button', { name: '启动模拟' }).click()
  await expect.poll(() => posts.filter((p) => p.path === '/api/slave/sim')).toHaveLength(1)
  const startPost = posts.filter((p) => p.path === '/api/slave/sim')[0]
  expect(startPost.body!.yx_enabled).toBe(true)
  expect(startPost.body!.yc_enabled).toBe(false)

  // 收尾：停止模拟，避免影响后续用例
  await expect(page.getByRole('button', { name: '停止模拟' })).toBeEnabled()
  await page.getByRole('button', { name: '停止模拟' }).click()
})

test('SCD 点表导入：80-1 预览（告警+计数）→ 应用生效', async ({ page }) => {
  const scdPath = path.resolve(__dirname, '../../fixtures/sample_104.scd')
  await gotoApp(page, SLAVE, '子站工作台')

  // 选择 .scd 文件 → 预览弹窗（统计 + 告警 + 可编辑 YAML）
  await page.getByTestId('points-import-file').setInputFiles(scdPath)
  const modal = page.locator('.pf-v6-c-modal-box')
  await expect(modal).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('[data-testid="scd-preview-yaml"]')).toBeVisible()
  await expect(modal).toContainText('IOA 冲突')
  await expect(modal).toContainText('yx: 3')

  // 应用导入 → 弹窗关闭 → 点表刷新出现 SCD 里的点位名
  await page.getByTestId('scd-apply').click()
  await expect(modal).toBeHidden({ timeout: 15_000 })
  await expect(
    page.locator('[data-testid="point-row"]').filter({ hasText: '断路器位置' }).first(),
  ).toBeVisible({ timeout: 20_000 })
})
