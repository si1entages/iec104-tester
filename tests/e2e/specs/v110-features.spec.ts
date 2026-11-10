/**
 * T95/T96/T97 v1.10 新特性 e2e（PF 套件；两套件 UI 健康由页级门禁看护）。
 *
 * - T95 Excel 点表导入 + 设计 vs 实测比对（合并模式单进程：子站页导入 → 主站页比对）
 * - T96 离线报文对比（桥服务 + echo 上游录两段 → 抓包页 diff：自 diff 空 / 改动可检出）
 * - T97 注入时间线 + 自动判定（步骤1 干净 → 步骤2 丢帧 100% → k 超窗自动判定 + 报告入段）
 */
import net from 'node:net'

import { expect, test, type Page } from '@playwright/test'

import { BRIDGE, COMBINED } from './helpers'

const STARTDT_ACT = Buffer.from([0x68, 0x04, 0x07, 0x00, 0x00, 0x00])
const STARTDT_CON = Buffer.from([0x68, 0x04, 0x0b, 0x00, 0x00, 0x00])

/** I 帧：APCI(N(S),N(R)) + 最小 ASDU（M_ME_NC_1 短浮点，ioa + float + QDS） */
function iFrame(ns: number, nr: number, ioa: number, value: number): Buffer {
  const asdu = Buffer.alloc(15)
  asdu.writeUInt8(13, 0)          // M_ME_NC_1
  asdu.writeUInt8(1, 1)           // VSQ: 1 个对象
  asdu.writeUInt8(3, 2)           // COT=3 自发
  asdu.writeUInt8(0, 3)           // OA
  asdu.writeUInt16LE(1, 4)        // CA=1
  asdu.writeUIntLE(ioa, 6, 3)     // IOA(3B)
  asdu.writeFloatLE(value, 9)
  asdu.writeUInt8(0, 13)          // QDS
  const head = Buffer.from([
    0x68, 4 + asdu.length,
    (ns << 1) & 0xff, ((ns << 1) >> 8) & 0xff,
    (nr << 1) & 0xff, ((nr << 1) >> 8) & 0xff,
  ])
  return Buffer.concat([head, asdu])
}

/** echo 上游（连接即回 STARTDT_CON，随后透传）——给监视器一个已完成 STARTDT 的会话 */
function smartUpstream(): { server: net.Server; port: Promise<number> } {
  const server = net.createServer((socket) => {
    // 客户端半开/急断会产生 ECONNRESET：吞掉错误并清理，避免未捕获异常炸掉用例
    socket.on('error', () => socket.destroy())
    socket.write(STARTDT_CON)
    socket.pipe(socket)
  })
  server.on('error', () => {})
  const port = new Promise<number>((resolve) => {
    server.listen(0, '127.0.0.1', () =>
      resolve((server.address() as net.AddressInfo).port))
  })
  return { server, port }
}

function osFreePort(): Promise<number> {
  return new Promise((resolve) => {
    const srv = net.createServer()
    srv.listen(0, '127.0.0.1', () => {
      const p = (srv.address() as net.AddressInfo).port
      srv.close(() => resolve(p))
    })
  })
}

/** 启动桥（UI 操作）指向 upstream */
async function startBridgeViaUi(page: Page, upstreamPort: number, listenPort: number): Promise<void> {
  await page.locator('#pf-br-uh').fill('127.0.0.1')
  await page.locator('#pf-br-up').fill(String(upstreamPort))
  await page.locator('#pf-br-lp').fill(String(listenPort))
  await page.getByRole('button', { name: '启动桥接' }).click()
  await expect(
    page.locator('.pf-v6-c-label').filter({ hasText: '已连接' }),
  ).toBeVisible({ timeout: 15_000 })
}

/** 104 迷你主站：STARTDT + 周期 I 帧（N(R) 随收到的 I 帧推进，双向确认） */
function miniMaster(port: number, ioa: number, value: number, count: number, intervalMs = 50): Promise<void> {
  return new Promise((resolve, reject) => {
    const sock = net.connect(port, '127.0.0.1')
    let ns = 0
    let ack = 0
    let buf = Buffer.alloc(0)
    const fail = (e: Error): void => {
      sock.destroy()
      reject(e)
    }
    sock.on('error', fail)
    let resolved = false
    sock.on('data', (chunk) => {
      buf = Buffer.concat([buf, chunk])
      // 逐帧解析（68 len ...），收到 I 帧推进 ack
      while (buf.length >= 2 && buf[0] === 0x68) {
        const len = buf[1] + 2
        if (buf.length < len) break
        const frame = buf.subarray(0, len)
        buf = buf.subarray(len)
        const c1 = frame[2]
        if ((c1 & 0x01) === 0) ack += 1  // 对端 I 帧 → 计入确认
      }
    })
    sock.write(STARTDT_ACT)
    let sent = 0
    sock.on('close', () => {
      if (sent < count && !resolved) {
        resolved = true
        clearInterval(timer)
        reject(new Error('miniMaster socket closed early'))
      }
    })
    const timer = setInterval(() => {
      sock.write(iFrame(ns++, ack, ioa, value))
      sent += 1
      if (sent >= count && !resolved) {
        resolved = true
        clearInterval(timer)
        sock.end()
        setTimeout(() => sock.destroy(), 100)  // 留 FIN 处理时间，避免 RST 打崩上游 pipe
        resolve()
      }
    }, intervalMs)
  })
}


/** S 帧（确认）：APCI(N(R)) 无信息体 */
function sFrame(nr: number): Buffer {
  return Buffer.from([
    0x68, 0x04, 0x01, 0x00,
    (nr << 1) & 0xff, ((nr << 1) >> 8) & 0xff,
  ])
}

/**
 * 数据源上游（T97）：连接即回 STARTDT_CON，随后周期发送 M_ME_NC_1 I 帧
 * （N(S) 递增、值逐帧变化避免 spont-duplicate；N(R) 随客户端确认推进）。
 * 监视器视角：rx（子站→主站）= 监视方向数据，方向合法。
 */
function dataUpstream(ioa: number, intervalMs = 50): { server: net.Server; port: Promise<number>; stop: () => void } {
  let timer: NodeJS.Timeout | null = null
  const server = net.createServer((socket) => {
    socket.on('error', () => socket.destroy())
    socket.write(STARTDT_CON)
    let ns = 0
    let ack = 0
    let buf = Buffer.alloc(0)
    socket.on('data', (chunk) => {
      buf = Buffer.concat([buf, chunk])
      while (buf.length >= 2 && buf[0] === 0x68) {
        const len = buf[1] + 2
        if (buf.length < len) break
        const frame = buf.subarray(0, len)
        buf = buf.subarray(len)
        if ((frame[2] & 0x03) === 0x01) {
          // 客户端 S 帧 → 推进 N(R)
          ack = Math.max(ack, ((frame[4] >> 1) | (frame[5] << 7)))
        }
      }
    })
    timer = setInterval(() => {
      socket.write(iFrame(ns++, ack, ioa, 40 + ns))
    }, intervalMs)
  })
  const port = new Promise<number>((resolve) => {
    server.listen(0, '127.0.0.1', () =>
      resolve((server.address() as net.AddressInfo).port))
  })
  return { server, port, stop: () => { if (timer) clearInterval(timer); server.close() } }
}

/** 确认客户端（T97）：STARTDT_ACT 后只回 S 帧（每收到 1 个 I 帧确认 1 个）。
 *  干净步：确认及时 → 双方未确认 I 帧不积压；丢包步：收不到 I 帧 → N(R) 停滞 →
 *  监视器 slave 侧未确认 I 帧越窗 → k-exceed。 */
function ackClient(port: number, durationMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const sock = net.connect(port, '127.0.0.1')
    let ack = 0
    let buf = Buffer.alloc(0)
    const done = setTimeout(() => {
      sock.destroy()
      resolve()
    }, durationMs)
    sock.on('error', (e) => {
      clearTimeout(done)
      sock.destroy()
      reject(e)
    })
    sock.on('data', (chunk) => {
      buf = Buffer.concat([buf, chunk])
      while (buf.length >= 2 && buf[0] === 0x68) {
        const len = buf[1] + 2
        if (buf.length < len) break
        const frame = buf.subarray(0, len)
        buf = buf.subarray(len)
        if ((frame[2] & 0x01) === 0) {
          ack += 1
          sock.write(sFrame(ack))
        }
      }
    })
    sock.write(STARTDT_ACT)
  })
}

// ── T95：Excel 点表导入 + 设计 vs 实测比对 ─────────────────────────────

test('T95 xlsx 点表导入 → 设计基准建立 → 主站页比对卡可用', async ({ page }) => {
  test.setTimeout(90_000)
  await page.goto(`${COMBINED}/app/?kit=pf#/slave`, { waitUntil: 'domcontentloaded' })

  const importInput = page.locator('[data-testid="points-import-file"]')
  await importInput.setInputFiles('tests/e2e/fixtures/points.xlsx')
  await expect(page.locator('[data-testid="xlsx-preview-rows"]')).toBeVisible({ timeout: 20_000 })
  await page.locator('[data-testid="xlsx-apply"]').click()

  // 导入完成：模态关闭、点表出现设计 IOA
  await expect(page.locator('[data-testid="xlsx-preview-rows"]')).toBeHidden({ timeout: 20_000 })
  await expect(page.locator('text=设计母线电压').first()).toBeVisible({ timeout: 20_000 })

  // 主站页设计比对卡：基准已随导入建立；当前表与设计一致 → 无差异
  await page.goto(`${COMBINED}/app/?kit=pf#/master`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-testid="design-set"]')).toBeVisible({ timeout: 20_000 })
  await page.locator('[data-testid="design-set"]').click()
  await expect(page.locator('text=与实测一致').first()).toBeVisible({ timeout: 20_000 })
})

// ── T96：离线报文对比（自 diff 空 / 改动可检出） ────────────────────────

async function recordSegment(page: Page, name: string, listenPort: number,
  ioa: number, value: number): Promise<string> {
  // 显式文件名：默认名按秒生成，两段在同秒内录制会撞名覆盖
  const started = await page.request.post(`${BRIDGE}/api/capture/start`,
    { data: { name } })
  const startBody = await started.json()
  expect(startBody.ok).toBe(true)
  await miniMaster(listenPort, ioa, value, 6)
  await page.waitForTimeout(300)
  const stopped = await page.request.post(`${BRIDGE}/api/capture/stop`, { data: {} })
  const stopBody = await stopped.json()
  expect(stopBody.ok).toBe(true)
  return stopBody.file as string
}

test('T96 报文对比：同录制自 diff 为空，改值可检出', async ({ page }) => {
  test.setTimeout(120_000)
  const up = smartUpstream()
  const upstreamPort = await up.port
  const listenPort = await osFreePort()
  try {
    await page.goto(`${BRIDGE}/app/?kit=pf#/bridge`, { waitUntil: 'domcontentloaded' })
    await expect(page.locator('#pf-br-uh')).toBeVisible({ timeout: 20_000 })
    await startBridgeViaUi(page, upstreamPort, listenPort)

    const fileA = await recordSegment(page, 'diff_a.i104', listenPort, 1001, 11.5)
    const fileB = await recordSegment(page, 'diff_b.i104', listenPort, 1001, 22.5)  // 改值

    // 抓包页对比卡：A vs A → identical；A vs B → 差异
    await page.goto(`${BRIDGE}/app/?kit=pf#/capture`, { waitUntil: 'domcontentloaded' })
    const selA = page.locator('[data-testid="pf-cap-diff-a"]')
    const selB = page.locator('[data-testid="pf-cap-diff-b"]')
    await expect(selA).toBeVisible({ timeout: 20_000 })
    await selA.selectOption(fileA)
    await selB.selectOption(fileA)
    await page.locator('[data-testid="capture-diff-run"]').click()
    await expect(page.locator('[data-testid="capture-diff-verdict"]')).toContainText(
      '两段一致', { timeout: 20_000 })

    await selB.selectOption(fileB)
    await page.locator('[data-testid="capture-diff-run"]').click()
    await expect(page.locator('[data-testid="capture-diff-verdict"]')).toContainText(
      '签名差异', { timeout: 20_000 })
    await expect(page.locator('[data-testid="capture-diff-table"]').locator('td')).not.toHaveCount(0)
  } finally {
    await page.request.post(`${BRIDGE}/api/bridge/stop`, { data: {} }).catch(() => {})
    up.server.close()
  }
})

// ── T97：注入时间线 + 自动判定 ─────────────────────────────────────────

test('T97 时间线：干净步过 → 丢帧步自动判定 k 超窗 → 判定入报告', async ({ page }) => {
  test.setTimeout(150_000)
  const up = dataUpstream(1001)
  const upstreamPort = await up.port
  const listenPort = await osFreePort()
  try {
    await page.goto(`${BRIDGE}/app/?kit=pf#/bridge`, { waitUntil: 'domcontentloaded' })
    await expect(page.locator('#pf-br-uh')).toBeVisible({ timeout: 20_000 })
    await startBridgeViaUi(page, upstreamPort, listenPort)

    // 编排：① 干净 1.5s（无扰动）② 丢帧 100% 2s（应见 k 超窗）
    const cfg = await page.request.post(`${BRIDGE}/api/bridge/timeline`, { data: { steps: [
      { label: '基线', duration_s: 1.5, condition: {}, expect: 'none' },
      { label: '注入丢包', duration_s: 2, condition: { loss_rate: 1 }, expect: 'k-exceed' },
    ] } })
    expect((await cfg.json()).ok).toBe(true)
    // 时间线卡在挂载时一次性同步服务端编排；API 配置后 reload 让卡片拿到步骤
    // （goto 同一 URL 会被当作同文档导航，不会真正刷新）
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.locator('#pf-br-uh')).toBeVisible({ timeout: 20_000 })

    // 合规的确认客户端持续在场（丢包步 N(R) 停滞 → 未确认 I 帧越窗）
    const client = ackClient(listenPort, 9_000)

    // UI 运行时间线（桥接页时间线卡）
    await page.locator('[data-testid="timeline-run"]').click()
    await expect(page.locator('[data-testid="timeline-result"]')).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('[data-testid="timeline-step-ok"]').first()).toBeVisible({ timeout: 60_000 })
    const okCount = await page.locator('[data-testid="timeline-step-ok"]').count()
    expect(okCount).toBe(2)  // ① 干净 ② k 超窗都符合预期

    // 判定入报告
    const report = await page.request.get(`${BRIDGE}/api/export/report.html`)
    const html = await report.text()
    expect(html).toContain('11. 注入时间线')
    expect(html).toContain('符合预期')
    await client
  } finally {
    await page.request.post(`${BRIDGE}/api/bridge/stop`, { data: {} }).catch(() => {})
    up.stop()
  }
})
