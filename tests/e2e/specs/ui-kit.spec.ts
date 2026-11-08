/**
 * 界面套件共存 e2e：同一个地址内即时切换 Carbon（默认）/ PatternFly / 经典版（antd）。
 *
 * 断言重点：
 *  - 切换不刷新页面、不改 URL（hash 保持）、页面状态保持；
 *  - 同一时刻 `<head>` 只保留当前套件的全局样式表（无跨套件污染）；
 *  - 另一套件的 DOM 完全卸载；
 *  - 深浅主题在三套 UI 之间跟随；
 *  - 选择持久化（localStorage），`?kit=` 可直接定位。
 */
import { expect, test } from '@playwright/test'

import { COMBINED } from './helpers'

const kitCss = async (page: import('@playwright/test').Page): Promise<string[]> =>
  page.evaluate(() =>
    [...document.querySelectorAll('link[data-kit-css]')].map(
      (l) => new URL((l as HTMLLinkElement).href).pathname.split('/').pop() ?? '',
    ),
  )

test('默认打开即 Carbon，壳渲染、深浅主题跟随', async ({ page }) => {
  await page.goto(`${COMBINED}/app/#/master`, { waitUntil: 'domcontentloaded' })

  // 默认 Carbon：header + side nav + 虚拟点表
  await expect(page.locator('.cds--side-nav__link').filter({ hasText: /主站工作台/ })).toBeVisible({
    timeout: 20_000,
  })
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 15_000 })
  expect(await page.evaluate(() => document.documentElement.dataset.kit)).toBe('carbon')
  expect((await kitCss(page)).some((f) => f.startsWith('styles-'))).toBe(true)
  expect(await page.evaluate(() => document.documentElement.classList.contains('cds--g10'))).toBe(true)
  expect(await page.locator('[class*="pf-v6-"]').count()).toBe(0)
  expect(await page.locator('[class*="ant-"]').count()).toBe(0)

  // 切深色：Carbon 主题类挂 <html>
  await page.getByTestId('theme-toggle').click()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.classList.contains('cds--g100')))
    .toBe(true)

  // 切回浅色，确认可逆
  await page.getByTestId('theme-toggle').click()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.classList.contains('cds--g10')))
    .toBe(true)
})

test('Carbon ↔ PatternFly 互切：主题跟随、无残留', async ({ page }) => {
  await page.goto(`${COMBINED}/app/?kit=carbon#/master`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 20_000 })

  // 切深色后换 PF：主题跟随（pf-v6-theme-dark）、g100 类被移除
  await page.getByTestId('theme-toggle').click()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
    .toBe('dark')

  await page.locator('[data-testid="kit-switcher-toggle"]').click()
  await page.locator('[data-testid="kit-switcher"] [data-kit="pf"]').click()
  // dataset.kit 在新套件样式就绪并挂载后才翻转（防白屏设计）；PF 与 Carbon 的
  // point-row 同名，不能用它判断「已切走」，先等完成信号
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.kit), { timeout: 20_000 })
    .toBe('pf')
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: /主站工作台/ })).toBeVisible({
    timeout: 20_000,
  })
  expect(await page.evaluate(() => document.documentElement.classList.contains('pf-v6-theme-dark'))).toBe(
    true,
  )
  expect(await page.evaluate(() => document.documentElement.classList.contains('cds--g100'))).toBe(false)
  expect(await page.locator('[class*="cds--"]').count()).toBe(0)
  expect((await kitCss(page)).some((f) => f.startsWith('patternfly-'))).toBe(true)
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible()

  // 切回 Carbon：hash/页面保持，PF DOM 卸载（同上，先等 dataset.kit 完成信号）
  await page.locator('[data-testid="kit-switcher-toggle"]').click()
  await page.locator('[data-testid="kit-switcher"] [data-kit="carbon"]').click()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.kit), { timeout: 20_000 })
    .toBe('carbon')
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 20_000 })
  expect(await page.evaluate(() => window.location.hash)).toBe('#/master')
  expect(await page.evaluate(() => document.documentElement.classList.contains('cds--g100'))).toBe(true)
  expect(await page.locator('[class*="pf-v6-"]').count()).toBe(0)
})

test('PatternFly ↔ 经典版（antd）互切：无残留、持久化', async ({ page }) => {
  await page.goto(`${COMBINED}/app/?kit=pf#/master`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: /主站工作台/ })).toBeVisible({
    timeout: 20_000,
  })
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 15_000 })
  expect(await page.evaluate(() => document.documentElement.dataset.kit)).toBe('pf')
  expect(await page.locator('[class*="ant-"]').count()).toBe(0)

  // 切经典版：不刷新、不改 hash、PF DOM 卸载、样式表互换
  await page.locator('[data-testid="kit-switcher-toggle"]').click()
  const switcher = page.locator('[data-testid="kit-switcher"]')
  await expect(switcher).toBeVisible()
  await switcher.locator('[data-kit="classic"]').click()
  await expect(page.locator('.ant-table-row').first()).toBeVisible({ timeout: 20_000 })
  expect(await page.evaluate(() => document.documentElement.dataset.kit)).toBe('classic')
  expect(await page.evaluate(() => window.location.hash)).toBe('#/master')
  expect(await page.locator('[class*="pf-v6-"]').count()).toBe(0)
  const classicCss = await kitCss(page)
  expect(classicCss.some((f) => f.startsWith('patternfly-'))).toBe(false)
  expect(classicCss.some((f) => f.startsWith('reset-'))).toBe(true)
  expect(await page.evaluate(() => localStorage.getItem('iec104.ui.kit'))).toBe('classic')

  // 在经典版切深色：主题写入共享状态
  await page.getByTestId('theme-toggle').click()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
    .toBe('dark')

  // 切回 PatternFly：主题跟随、页面仍是主站工作台
  await page.locator('[data-testid="kit-switcher-toggle"]').click()
  await page.locator('[data-testid="kit-switcher"] [data-kit="pf"]').click()
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: /主站工作台/ })).toBeVisible({
    timeout: 20_000,
  })
  expect(await page.evaluate(() => document.documentElement.classList.contains('pf-v6-theme-dark'))).toBe(
    true,
  )
  expect(await page.evaluate(() => window.location.hash)).toBe('#/master')
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible()
  expect(await page.locator('[class*="ant-"]').count()).toBe(0)
})

test('?kit=classic 直接打开经典版，切回后刷新仍记住选择', async ({ page }) => {
  await page.goto(`${COMBINED}/app/?kit=classic#/master`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.ant-table-row').first()).toBeVisible({ timeout: 20_000 })
  expect(await page.evaluate(() => document.documentElement.dataset.kit)).toBe('classic')

  // 切回 Carbon 会持久化选择；再刷新（不带 ?kit）应停在 Carbon
  await page.locator('[data-testid="kit-switcher-toggle"]').click()
  await page.locator('[data-testid="kit-switcher"] [data-kit="carbon"]').click()
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 20_000 })

  await page.goto(`${COMBINED}/app/#/master`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 20_000 })
  expect(await page.evaluate(() => document.documentElement.dataset.kit)).toBe('carbon')
})

test('Carbon 主站：加入趋势后切页返回，选中与曲线保留', async ({ page }) => {
  await page.goto(`${COMBINED}/app/#/master`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 20_000 })

  // 选中第一行并加入趋势
  await page.locator('[data-testid="point-row"]').first().click()
  await page.getByRole('button', { name: /加入趋势/ }).click()
  const trendTag = page.locator('.cds--tag').filter({ hasText: /-\d+$/ }).first()
  await expect(trendTag).toBeVisible()

  // 切到日志页再返回主站：选中行与趋势 watch 都应保留
  await page.locator('.cds--side-nav__link').filter({ hasText: /日志/ }).click()
  await expect(page.locator('#cb-log-search')).toBeVisible({ timeout: 20_000 })
  await page.locator('.cds--side-nav__link').filter({ hasText: /主站工作台/ }).click()
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('[data-testid="point-row"][aria-selected="true"]').first()).toBeVisible()
  await expect(trendTag).toBeVisible()

  // 打开趋势图页签：canvas 已在可见面板中初始化（修复条件容器一次性 effect 永久 bail、
  // 隐藏面板 0×0 画布）。选中面板用语义选择器：@carbon/react 1.120 无 `--selected` 修饰类
  await page.locator('.cds--tabs__nav-link').filter({ hasText: /趋势图/ }).click()
  const canvas = page.locator('[role="tabpanel"]:not([hidden]) canvas')
  await expect(canvas).toBeVisible({ timeout: 15_000 })
  const box = await canvas.boundingBox()
  expect(box?.width).toBeGreaterThan(200)
})
