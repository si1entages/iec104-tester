/**
 * T15 主站交互 e2e：连接建立 → 点表虚拟滚动 → 选中行 → 命令面板下发。
 *
 * 含 T12 红线用例：**双击点表行不得产生任何 `/api/master/*` POST**
 * （历史回归：旧 UI 双击值直接发命令；T12 起改为「选中行 + 命令面板」）。
 */
import { expect, test } from '@playwright/test'

import {
  IEC_PORT,
  MASTER,
  SLAVE,
  capturePosts,
  gotoApp,
  injectPoints,
  stopEngines,
  waitForStatus,
} from './helpers'

test.describe.configure({ mode: 'serial' })

const ROW = '.ant-table-tbody .ant-table-row'

test.beforeAll(async ({ request }) => {
  await injectPoints(request, MASTER)
  await injectPoints(request, SLAVE)
  // 子站先监听，主站连接才有对端
  const res = await request.post(`${SLAVE}/api/slave/start`, {
    data: { host: '0.0.0.0', port: IEC_PORT, addr: 1 },
  })
  expect((await res.json()).ok).toBeTruthy()
})

test.afterAll(async ({ request }) => {
  await stopEngines(request)
})

test('主站 UI 连接建立（点「连接」→ 后端 running）', async ({ page }) => {
  await gotoApp(page, MASTER, '主站工作台')
  // antd 对两个汉字按钮自动插空格（accessible name 变成「连 接」），用正则匹配
  const connectBtn = page.getByRole('button', { name: /连\s*接/ })
  await expect(connectBtn).toBeEnabled()
  await connectBtn.click()
  const status = await waitForStatus(page.request, MASTER, (s) => s.running === true)
  expect(status.running).toBe(true)
  // 头部运行标记同步（WS 快照驱动）
  await expect(page.getByText('running', { exact: true })).toBeVisible()
})

test('点表虚拟滚动：DOM 行数远小于总行数（T12 核心验收）', async ({ page }) => {
  await gotoApp(page, MASTER, '主站工作台')
  await page.waitForSelector(ROW, { timeout: 30_000 })
  const total = 2004 // YAML: 2000 批量 YX + YX1/YC101/YK201/YK202（另有 YM/STEP）
  const domRows = await page.locator(ROW).count()
  expect(domRows).toBeGreaterThan(0)
  expect(domRows).toBeLessThan(200) // 远小于 2000+：虚拟滚动只渲染可视窗口
  // 滚动到底部后首屏内容更新（可视行确实随滚动变化）
  await page.evaluate(() => {
    const holder = document.querySelector('.ant-table-tbody-virtual-holder')
    if (holder) holder.scrollTop = (holder as HTMLElement).scrollHeight
  })
  await expect(page.locator(ROW).first()).toContainText('YX_BULK', { timeout: 15_000 })
  await page.evaluate(() => {
    const holder = document.querySelector('.ant-table-tbody-virtual-holder')
    if (holder) holder.scrollTop = 0
  })
})

test('选中行 → 命令面板下发（请求体断言）', async ({ page }) => {
  await gotoApp(page, MASTER, '主站工作台')
  // 过滤出 YK 点
  await page.getByPlaceholder('按名称 / IOA 过滤').fill('YK_SBO_TRUE')
  const ykRow = page.locator(ROW).filter({ hasText: 'YK_SBO_TRUE' }).first()
  await expect(ykRow).toBeVisible()
  await ykRow.click()
  // 命令面板出现「已选」标记（点表卡片与命令面板各有一个相同文本的 Tag，取其一即可）
  await expect(page.getByText('已选 YK-201').first()).toBeVisible()
  const posts = capturePosts(page)
  await page.getByRole('button', { name: /执\s*行/ }).click()
  await expect
    .poll(() => posts.filter((p) => p.path === '/api/master/yk'), { timeout: 10_000 })
    .toHaveLength(1)
  const body = posts.find((p) => p.path === '/api/master/yk')!.body!
  expect(body.ioa).toBe(201)
  expect(body.select).toBe(false) // 「执行」= 直接执行，不带选择
  expect(typeof body.state).toBe('number')
})

test('选中行 → SBO 选择 → 撤销选择（deactivate 请求体断言）', async ({ page }) => {
  await gotoApp(page, MASTER, '主站工作台')
  await page.getByPlaceholder('按名称 / IOA 过滤').fill('YK_SBO_TRUE')
  const ykRow = page.locator(ROW).filter({ hasText: 'YK_SBO_TRUE' }).first()
  await expect(ykRow).toBeVisible()
  await ykRow.click()
  await expect(page.getByText('已选 YK-201').first()).toBeVisible()
  const posts = capturePosts(page)

  // 未选择前「撤销选择」禁用
  const undoBtn = page.getByRole('button', { name: /撤\s*销\s*选\s*择/ })
  await expect(undoBtn).toBeDisabled()

  // 选择（SBO）→ 第一帧 select=true 且无 deactivate；成功后撤销解锁
  await page.getByRole('button', { name: /选\s*择\s*\(SBO\)/ }).click()
  await expect
    .poll(() => posts.filter((p) => p.path === '/api/master/yk'), { timeout: 10_000 })
    .toHaveLength(1)
  expect(posts[0].body!.select).toBe(true)
  expect(posts[0].body!.deactivate).toBeFalsy()
  await expect(undoBtn).toBeEnabled({ timeout: 10_000 })

  // 撤销选择 → 第二帧 select=true（与选择帧一致）+ deactivate=true；成功后复位禁用
  await undoBtn.click()
  await expect
    .poll(() => posts.filter((p) => p.path === '/api/master/yk'), { timeout: 10_000 })
    .toHaveLength(2)
  expect(posts[1].body!).toMatchObject({ ioa: 201, select: true, deactivate: true })
  await expect(undoBtn).toBeDisabled({ timeout: 10_000 })
})

test('红线：双击点表行不产生任何 /api/master/* POST', async ({ page }) => {
  await gotoApp(page, MASTER, '主站工作台')
  await page.getByPlaceholder('按名称 / IOA 过滤').fill('YK_SBO_TRUE')
  const ykRow = page.locator(ROW).filter({ hasText: 'YK_SBO_TRUE' }).first()
  await expect(ykRow).toBeVisible()
  const posts = capturePosts(page)
  await ykRow.dblclick()
  await page.waitForTimeout(1_500)
  const masterPosts = posts.filter((p) => p.path.startsWith('/api/master/'))
  expect(masterPosts, `双击触发了命令下发: ${JSON.stringify(masterPosts)}`).toHaveLength(0)
})
