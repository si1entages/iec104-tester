/**
 * 历史查询页 e2e（D3）：统计标签、数据过滤请求、报文页签与导出可用性。
 *
 * 通过路由拦截注入确定性数据，避免依赖历史库中既有记录；筛选请求的
 * query 参数在此断言，确保「表单 → API」接线没有断。
 */
import { expect, test } from '@playwright/test'

import { MASTER, gotoApp } from './helpers'

const STATS = {
  ok: true,
  enabled: true,
  stats: {
    data_records: 12,
    frame_records: 3,
    buffered_data: 0,
    buffered_frames: 0,
    dropped_records: 0,
    db_size_bytes: 4096,
    oldest_data: 1_700_000_000,
    newest_data: 1_700_000_100,
  },
}

const DATA_ROWS = [
  {
    id: 1,
    ts: 1_700_000_000,
    point_type: 'yx',
    ioa: 100,
    value: '1',
    quality: 'good',
    source: 'spont',
  },
  {
    id: 2,
    ts: 1_700_000_050,
    point_type: 'yc',
    ioa: 200,
    value: '220.5',
    quality: 'good',
    source: 'gi',
  },
]

const FRAME_ROWS = [
  {
    id: 1,
    ts: 1_700_000_001,
    direction: 'rx',
    frame_type: 'I',
    hex: '680E0400030064010600010000000014',
    parsed: 'C_IC_NA_1',
    client: 'e2e',
  },
]

test('历史页：统计标签、IOA 过滤、报文页签与导出可用', async ({ page }) => {
  const dataUrls: string[] = []
  const frameUrls: string[] = []

  await page.route('**/api/history/stats', (route) => route.fulfill({ json: STATS }))
  await page.route(/\/api\/history\/data(?:\?.*)?$/, (route) => {
    dataUrls.push(route.request().url())
    return route.fulfill({ json: { ok: true, enabled: true, rows: DATA_ROWS } })
  })
  await page.route(/\/api\/history\/frames(?:\?.*)?$/, (route) => {
    frameUrls.push(route.request().url())
    return route.fulfill({ json: { ok: true, enabled: true, rows: FRAME_ROWS } })
  })

  await gotoApp(page, MASTER, '历史')

  // 统计标签（数据/报文条数）
  await expect(page.getByText('数据 12')).toBeVisible()
  await expect(page.getByText('报文 3')).toBeVisible()
  await expect(page.getByText('220.5')).toBeVisible()

  // IOA 过滤 → 查询请求带 ioa=200
  await page.getByPlaceholder('IOA').fill('200')
  await page.getByRole('button', { name: '查询' }).click()
  await expect.poll(() => dataUrls.some((u) => u.includes('ioa=200'))).toBe(true)

  // 导出按钮可用（历史库已启用）
  const exportBtn = page.getByRole('button', { name: '导出 CSV' })
  await expect(exportBtn).toBeEnabled()

  // 切到报文页签 → 请求 frames 并显示 HEX
  await page.getByRole('button', { name: '报文', exact: true }).click()
  await expect.poll(() => frameUrls.length).toBeGreaterThan(0)
  await expect(page.getByText('680E0400030064010600010000000014')).toBeVisible()
})

test('历史页曲线页签：添加序列 → 历史曲线绘制（T77）', async ({ page }) => {
  // 拦截曲线数据请求：ioa=100 返回确定性 YX 序列，其余返回空
  await page.route('**/api/history/data*', (route) => {
    const url = route.request().url()
    if (url.includes('ioa=100')) {
      return route.fulfill({ json: { ok: true, enabled: true, rows: DATA_ROWS.filter((r) => r.ioa === 100) } })
    }
    return route.fulfill({ json: { ok: true, enabled: true, rows: [] } })
  })
  await gotoApp(page, MASTER, '历史')

  await page.getByRole('button', { name: '曲线' }).click()
  await expect(page.getByText(/添加 1~8 个点位序列|Add 1-8 point series/)).toBeVisible()

  // 添加 yx-100 序列（曲线页签默认类型 yc → 切 yx）
  await page.locator('#pf-hc-type').selectOption('yx')
  await page.locator('#pf-hc-ioa').fill('100')
  await page.getByRole('button', { name: '添加序列' }).click()

  // 曲线画布出现（有数据行 → 渲染 ECharts）
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 10_000 })
})
