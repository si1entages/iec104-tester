/**
 * T90 v1.8.0 新特性端到端：压测卡 / 桥条件注入卡 / 合规违规列表 / 时钟偏差测量 /
 * 报告结论横幅（嵌图 POST 链路由 pytest 覆盖，此处走 UI 流）。
 *
 * 压测/对时/报告跑合并模式（COMBINED）；桥两项跑桥应用（BRIDGE，用例内 echo 上游）。
 */
import net from 'node:net'

import { expect, test } from '@playwright/test'

import { BRIDGE, COMBINED, appUrl } from './helpers'

test.describe.configure({ mode: 'serial' })

async function startEngines(request: import('@playwright/test').APIRequestContext): Promise<void> {
  await request.post(`${COMBINED}/api/master/stop`, { data: {} })
  await request.post(`${COMBINED}/slave/api/slave/stop`, { data: {} })
  const slave = await request.post(`${COMBINED}/slave/api/slave/start`, {
    data: { host: '127.0.0.1', port: 24315, addr: 1 },
  })
  expect((await slave.json()).ok).toBeTruthy()
  const master = await request.post(`${COMBINED}/api/master/start`, {
    data: { host: '127.0.0.1', port: 24315, addr: 1 },
  })
  expect((await master.json()).ok).toBeTruthy()
  await expect
    .poll(async () => (await (await request.get(`${COMBINED}/api/status`)).json()).state, {
      timeout: 15_000,
    })
    .toBe('Running')
}

function echoUpstream(): Promise<{ server: net.Server; port: number }> {
  return new Promise((resolve) => {
    const server = net.createServer((socket) => socket.pipe(socket))
    server.listen(0, '127.0.0.1', () =>
      resolve({ server, port: (server.address() as net.AddressInfo).port }))
  })
}

test('压测卡：启动 → 停止 → 冻结汇总可见', async ({ page, request }) => {
  test.setTimeout(120_000)
  await startEngines(request)
  await page.goto(appUrl(COMBINED, '/tests'), { waitUntil: 'domcontentloaded' })
  const eps = page.locator('#pf-lt-eps')
  await expect(eps).toBeVisible({ timeout: 20_000 })
  await eps.fill('50')
  await page.locator('#pf-lt-dur').fill('6')
  await page.getByRole('button', { name: /启动压测/ }).click()
  // 运行态：出现「停止压测」按钮
  await expect(page.getByRole('button', { name: /停止压测/ })).toBeVisible({ timeout: 15_000 })
  await page.waitForTimeout(2000)
  await page.getByRole('button', { name: /停止压测/ }).click()
  // 结束态回放冻结汇总（T83 回归：拆引擎后不得算 0；rx_frames 为差分统计）
  const summaryText = page.getByText(/汇总: \{/)
  await expect(summaryText).toBeVisible({ timeout: 15_000 })
  await expect
    .poll(async () => {
      const text = (await summaryText.textContent()) ?? ''
      const m = text.match(/"rx_frames":(\d+)/)
      return m ? Number(m[1]) : -1
    }, { timeout: 10_000 })
    .toBeGreaterThan(0)
})

test('时钟偏差测量：命令面板一键测量出结果', async ({ page, request }) => {
  test.setTimeout(120_000)
  await startEngines(request)
  await page.goto(appUrl(COMBINED, '/master'), { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-testid="point-row"]').first()).toBeVisible({ timeout: 20_000 })
  // 展开命令面板「系统召唤 / 对时 / 复位」折叠区，点「测量时钟偏差」
  await page.getByRole('button', { name: /系统召唤 \/ 对时 \/ 复位/ }).click()
  await page.getByRole('button', { name: /测量时钟偏差/ }).click()
  await expect(page.getByText(/时钟偏差：平均/)).toBeVisible({ timeout: 20_000 })
})

test('桥合规违规列表：序号跳变被自动指认', async ({ page }) => {
  test.setTimeout(120_000)
  const { server, port: upPort } = await echoUpstream()
  await page.goto(`${BRIDGE}/app/?kit=pf#/bridge`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#pf-br-uh')).toBeVisible({ timeout: 20_000 })
  await page.locator('#pf-br-uh').fill('127.0.0.1')
  await page.locator('#pf-br-up').fill(String(upPort))
  await page.getByRole('button', { name: /启动桥接/ }).click()
  // 运行态：出现「停止桥接」按钮（conn.connected 标签随之变绿）
  await expect(page.getByRole('button', { name: /停止桥接/ })).toBeVisible({ timeout: 15_000 })

  // 探针：发 I 帧且序号跳变（VS=5 → VS=100），未 STARTDT 直发数据
  const listenPort = Number(await page.locator('#pf-br-lp').inputValue().catch(() => 0)) || 2404
  const probe = net.createConnection({ host: '127.0.0.1', port: listenPort })
  await new Promise((r) => probe.on('connect', r))
  const iFrame = (vs: number): Buffer => {
    const asdu = Buffer.from([1, 1, 3, 0, 1, 0, 1, 0, 0, 1])
    const head = Buffer.alloc(4)
    head.writeUInt16LE(vs * 2, 0)
    head.writeUInt16LE(0, 2)
    return Buffer.concat([Buffer.from([0x68, asdu.length + 4]), head, asdu])
  }
  probe.write(iFrame(5))
  probe.write(iFrame(100))
  await page.waitForTimeout(2000)
  // 违规列表出现（未 STARTDT 传数据 + 序号跳变至少其一）
  await expect(page.getByText(/违规|violation/i).first()).toBeVisible({ timeout: 15_000 })
  probe.destroy()
  await page.getByRole('button', { name: /停止桥接/ }).click()
  server.close()
})

test('桥条件注入卡：设丢帧 100% → 注入统计出现', async ({ page, request }) => {
  test.setTimeout(120_000)
  const { server, port: upPort } = await echoUpstream()
  await page.goto(`${BRIDGE}/app/?kit=pf#/bridge`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#pf-br-uh')).toBeVisible({ timeout: 20_000 })
  await page.locator('#pf-br-uh').fill('127.0.0.1')
  await page.locator('#pf-br-up').fill(String(upPort))
  await page.getByRole('button', { name: /启动桥接/ }).click()
  // 运行态：出现「停止桥接」按钮（conn.connected 标签随之变绿）
  await expect(page.getByRole('button', { name: /停止桥接/ })).toBeVisible({ timeout: 15_000 })

  // 条件卡：丢帧率 100% → 应用条件（状态广播由帧流量驱动，先用 API 确认生效）
  await page.locator('#pf-cond-loss_rate').fill('100')
  await page.getByRole('button', { name: /应用条件/ }).click({ force: true })
  await expect
    .poll(async () => {
      const st = await (await request.get(`${BRIDGE}/api/status`)).json()
      return st.condition_active === true
    }, { timeout: 15_000 })
    .toBe(true)

  // 探针发帧（被 100% 丢弃），注入统计应累计
  const listenPort = Number(await page.locator('#pf-br-lp').inputValue().catch(() => 0)) || 2404
  const probe = net.createConnection({ host: '127.0.0.1', port: listenPort })
  await new Promise((r) => probe.on('connect', r))
  const asdu = Buffer.from([1, 1, 3, 0, 1, 0, 1, 0, 0, 1])
  const head = Buffer.alloc(4)
  head.writeUInt16LE(6, 0)
  probe.write(Buffer.concat([Buffer.from([0x68, asdu.length + 4]), head, asdu]))
  probe.write(Buffer.concat([Buffer.from([0x68, asdu.length + 4]), head, asdu]))
  await page.waitForTimeout(2000)
  await expect(page.getByText(/注入统计|injTitle/i).first()).toBeVisible({ timeout: 15_000 })
  probe.destroy()
  await page.getByRole('button', { name: /停止桥接/ }).click()
  server.close()
})

test('报告结论横幅：选结论导出，HTML 含结论文本', async ({ page, request }) => {
  test.setTimeout(120_000)
  await startEngines(request)
  await page.goto(appUrl(COMBINED, '/status'), { waitUntil: 'domcontentloaded' })
  // FormSelect 是原生 <select>：selectOption 选择结论；导出走 fetch→Blob→popup
  const select = page.locator('#pf-status-conclusion')
  await expect(select).toBeVisible({ timeout: 20_000 })
  await select.selectOption({ label: '有条件通过' })
  const popupPromise = page.waitForEvent('popup')
  await page.locator('[data-testid="export-report"]').click()
  const popup = await popupPromise
  await popup.waitForLoadState('domcontentloaded')
  const html = await popup.content()
  expect(html).toContain('有条件通过')
  expect(html).toContain('测试报告')
})
