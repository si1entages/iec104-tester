/**
 * 视觉回归基线（像素级）。
 *
 * 默认行为：**当前平台有基线就跑**（Windows 基线已入库，CI 的 windows-build job
 * 会执行）；没有基线的平台自动 skip（避免 Linux CI 因字体/平台差异误报）。
 *
 * 新增平台基线：在该平台执行
 *   VISUAL_UPDATE=1 ... playwright test ... visual.spec.ts --update-snapshots
 * 人工 review diff 后提交 `specs/__screenshots__/<platform>/`。
 *
 * 复现条件：专用单角色服务 8768（无引擎、无历史、无帧），页面内容稳定。
 * 截“浅色/深色主站工作台 + 状态总览 + 对点传动 + 操作审计”五张整页基线。
 */
import { existsSync } from 'node:fs'
import path from 'node:path'

import { expect, test } from '@playwright/test'

import { VISUAL } from './helpers'

const BASELINE_DIR = path.resolve('tests/e2e/specs/__screenshots__', process.platform)
const HAS_BASELINE = existsSync(path.join(BASELINE_DIR, 'master-light.png'))
const FORCE_UPDATE = process.env.VISUAL_UPDATE === '1'

test.skip(
  !HAS_BASELINE && !FORCE_UPDATE,
  `当前平台 ${process.platform} 没有视觉基线（${BASELINE_DIR}）；` +
    '用 VISUAL_UPDATE=1 --update-snapshots 生成后提交',
)

async function clickNav(page: import('@playwright/test').Page, text: string | RegExp): Promise<void> {
  // 当前默认套件是 Carbon；保留 PF 选择器作为显式 ?kit=pf 时的回退
  const carbon = page.locator('.cds--side-nav__link').filter({ hasText: text })
  if ((await carbon.count()) > 0) {
    await carbon.first().click()
    return
  }
  await page.locator('.pf-v6-c-nav__link').filter({ hasText: text }).first().click()
}

async function openWorkbench(page: import('@playwright/test').Page, mode: 'light' | 'dark') {
  await page.addInitScript((m: string) => {
    window.localStorage.setItem('iec104.theme', m)
  }, mode)
  await page.goto(`${VISUAL}/app/`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('连接与命令')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 20_000 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
    .toBe(mode)
  await page.waitForTimeout(800) // 等 WS 快照与首屏图表/表格稳定
}

test('视觉基线：主站工作台（浅色）', async ({ page }) => {
  test.setTimeout(120_000)
  await openWorkbench(page, 'light')
  await expect(page).toHaveScreenshot('master-light.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    maxDiffPixelRatio: 0.01,
  })
})

test('视觉基线：主站工作台（深色）', async ({ page }) => {
  test.setTimeout(120_000)
  await openWorkbench(page, 'dark')
  await expect(page).toHaveScreenshot('master-dark.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    maxDiffPixelRatio: 0.01,
  })
})

test('视觉基线：状态总览（浅色）', async ({ page }) => {
  test.setTimeout(120_000)
  await openWorkbench(page, 'light')
  await clickNav(page, /状态总览/)
  await expect(page.getByText('运行状态')).toBeVisible({ timeout: 15_000 })
  await page.waitForTimeout(700)
  await expect(page).toHaveScreenshot('status-light.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    maxDiffPixelRatio: 0.01,
  })
})

test('视觉基线：对点传动（浅色）', async ({ page }) => {
  test.setTimeout(120_000)
  await openWorkbench(page, 'light')
  await clickNav(page, /对点传动/)
  await expect(page.getByText('对点 / 传动验收')).toBeVisible({ timeout: 15_000 })
  await page.waitForTimeout(700)
  await expect(page).toHaveScreenshot('commission-light.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    maxDiffPixelRatio: 0.01,
  })
})

test('视觉基线：操作审计（浅色）', async ({ page }) => {
  test.setTimeout(120_000)
  await openWorkbench(page, 'light')
  await clickNav(page, /操作审计/)
  await expect(page.getByText('自动追加到 SHA-256 哈希链')).toBeVisible({ timeout: 15_000 })
  await page.waitForTimeout(700)
  await expect(page).toHaveScreenshot('audit-light.png', {
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
    maxDiffPixelRatio: 0.01,
  })
})
