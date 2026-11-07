/**
 * 中/英切换 e2e（D3）：导航文案切换、刷新后保持（localStorage）。
 */
import { expect, test } from '@playwright/test'

import { MASTER, gotoApp } from './helpers'

test('语言切换：中 → EN，刷新后仍为英文', async ({ page }) => {
  await gotoApp(page, MASTER, '状态总览')
  await expect(page.getByRole('menuitem', { name: '状态总览' })).toBeVisible()

  await page.locator('.ant-segmented-item').filter({ hasText: 'EN' }).click()
  await expect(page.getByRole('menuitem', { name: 'Status' })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'History' })).toBeVisible()

  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('menuitem', { name: 'Status' })).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('iec104_locale'))).toBe('en')
})
