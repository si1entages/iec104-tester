/**
 * T15 多站 e2e：增删/启停 → 聚合状态可见。
 * 使用独立 IEC 端口 15002，避免与单站引擎（2404）冲突；跑完停止并删除。
 */
import { expect, test } from '@playwright/test'

import { SLAVE, gotoApp } from './helpers'

const STATION_PORT = 15002

test('多站：增删/启停 → 聚合状态可见', async ({ page, request }) => {
  await gotoApp(page, SLAVE, '多站')
  // 页面自带 3 个默认站（station-1/2/3）：先删掉多余的，再把第一个改造成目标站
  for (const id of ['station-3', 'station-2']) {
    const del = page.getByRole('button', { name: `删除-${id}` })
    if ((await del.count()) > 0) await del.click()
  }
  const idInput = page.getByPlaceholder('station_id（唯一、必填）').first()
  await idInput.waitFor()
  await idInput.fill('e2e-a')
  // 独立端口，避开单站引擎（站卡片内第一个数字输入框即「端口」）
  const card = page.locator('[data-testid="multi-card"]').filter({ hasText: 'e2e-a' })
  const portInput = card.getByLabel('端口').first()
  await portInput.fill(String(STATION_PORT))
  // 若还有残留默认站，关掉其「参与本次启动」，保证只启动 e2e-a
  const page1 = page
  const partSwitches = page1.getByRole('checkbox', { name: /^参与本次启动-/ })
  const count = await partSwitches.count()
  for (let i = 0; i < count; i += 1) {
    const sw = partSwitches.nth(i)
    const name = (await sw.getAttribute('aria-label')) ?? ''
    if (!name.includes('e2e-a') && (await sw.getAttribute('aria-checked')) === 'true') {
      await sw.click()
    }
  }

  await page.getByRole('button', { name: '启动全部启用站' }).click()
  // 聚合状态/汇总里出现该站
  await expect(page.getByText('e2e-a', { exact: false }).first()).toBeVisible({ timeout: 20_000 })
  const status = (await (await request.get(`${SLAVE}/api/multi/status`)).json()) as {
    ok: boolean
    running: boolean
    stations: { station_id: string; port: number }[]
  }
  expect(status.ok).toBe(true)
  expect(status.running).toBe(true)
  expect(status.stations.map((s) => s.station_id)).toEqual(['e2e-a'])
  expect(status.stations[0]?.port).toBe(STATION_PORT)

  await page.getByRole('button', { name: '停止全部' }).click()
  await expect
    .poll(async () => (await (await request.get(`${SLAVE}/api/multi/status`)).json()).running, {
      timeout: 15_000,
    })
    .toBe(false)

  // 删除站卡片
  await page.getByRole('button', { name: '删除-e2e-a' }).click()
  await expect(page.getByRole('button', { name: '删除-e2e-a' })).toHaveCount(0)
})
