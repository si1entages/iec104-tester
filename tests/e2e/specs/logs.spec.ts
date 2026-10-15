/**
 * T15 日志面板 e2e：级别过滤生效、暂停后恢复不丢缓冲、导出可下载。
 */
import { expect, test } from '@playwright/test'

import { MASTER, gotoApp } from './helpers'

test('级别过滤生效（拦截 /api/logs 注入确定性数据）', async ({ page }) => {
  await page.route('**/api/logs?*', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        stats: { total: 3 },
        logs: [
          { ts: 1730000001, level: 'ERROR', source: 'e2e', category: 'system', message: 'e2e-error-row' },
          { ts: 1730000002, level: 'INFO', source: 'e2e', category: 'system', message: 'e2e-info-row' },
          { ts: 1730000003, level: 'DEBUG', source: 'e2e', category: 'system', message: 'e2e-debug-row' },
        ],
      }),
    }),
  )
  await gotoApp(page, MASTER, '日志')
  await expect(page.getByText('e2e-error-row')).toBeVisible()
  await expect(page.getByText('e2e-info-row')).toBeVisible()
  await expect(page.getByText('e2e-debug-row')).toBeVisible()

  // 取消勾选 INFO → INFO 行消失，其余保留
  await page.locator('.ant-select .ant-select-selector').first().click()
  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="INFO"]').click()
  await expect(page.getByText('e2e-info-row')).toHaveCount(0)
  await expect(page.getByText('e2e-error-row')).toBeVisible()
  await expect(page.getByText('e2e-debug-row')).toBeVisible()
})

test('暂停后恢复不丢缓冲（真实后端日志流）', async ({ page, request }) => {
  await gotoApp(page, MASTER, '日志')
  await page.waitForSelector('.ant-table-row', { timeout: 15_000 })

  const bufferTagText = () =>
    page
      .locator('.ant-tag')
      .filter({ hasText: /^缓冲 \d+$/ })
      .first()
      .innerText()
  const viewRows = () => page.locator('.ant-table-row').count()
  const parseBuffer = (t: string) => Number(t.replace(/\D+/g, '')) || 0

  const bufferBefore = parseBuffer(await bufferTagText())
  const rowsBefore = await viewRows()

  // 暂停 → 触发新日志（master start/stop 会产生 INFO 日志）→ 视图冻结
  await page.getByRole('button', { name: '暂停实时' }).click()
  await expect(page.getByText('已暂停')).toBeVisible()
  const rowsPaused = await viewRows()
  expect(rowsPaused).toBe(rowsBefore)
  await request.post(`${MASTER}/api/master/start`, { data: { host: '127.0.0.1', port: 2404 } })
  await page.waitForTimeout(1_200)
  await request.post(`${MASTER}/api/master/stop`).catch(() => {})
  await page.waitForTimeout(1_200)
  // 缓冲在暂停期间继续累积
  const bufferPaused = parseBuffer(await bufferTagText())
  expect(bufferPaused).toBeGreaterThanOrEqual(bufferBefore)
  expect(await viewRows()).toBe(rowsBefore) // 视图仍冻结

  // 恢复 → 缓冲合入视图，不丢失
  await page.getByRole('button', { name: '恢复实时' }).click()
  await expect(page.getByText('已暂停')).toHaveCount(0)
  await expect
    .poll(async () => parseBuffer(await bufferTagText()), { timeout: 10_000 })
    .toBeGreaterThanOrEqual(bufferPaused)
})

test('导出可下载（GET /api/logs/export 带附件头且非空）', async ({ page, request }) => {
  await gotoApp(page, MASTER, '日志')
  const res = await request.get(`${MASTER}/api/logs/export`)
  expect(res.ok()).toBeTruthy()
  const disposition = res.headers()['content-disposition'] ?? ''
  expect(disposition).toContain('attachment')
  const body = await res.text()
  expect(body.length).toBeGreaterThan(0)
  // UI 入口存在且可点击（window.open 下载，不阻塞断言）
  await expect(page.getByRole('button', { name: '导出 JSONL' })).toBeVisible()
  await page.getByRole('button', { name: '导出 JSONL' }).click()
})
