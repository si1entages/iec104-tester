/**
 * T74 桥接观察页 e2e：真实 bridge 角色服务（8769）+ 测试进程内 echo 上游。
 *
 * 流程：UI 启动桥（上游指向用例内 echo 服务）→ node:net 探针发 STARTDT_ACT
 * → 经桥回环收到原帧 → 页面出现实时帧与统计 → 停止桥。
 */
import net from 'node:net'

import { expect, test } from '@playwright/test'

import { BRIDGE } from './helpers'

const STARTDT_ACT = Buffer.from([0x68, 0x04, 0x07, 0x00, 0x00, 0x00])

test('桥接观察页：启动 → STARTDT 经桥回环 → 帧视图/统计 → 停止', async ({ page }) => {
  test.setTimeout(90_000)

  // 用例内 echo 上游（与协议无关，只验证透传与旁路观察链路）
  const upstream = net.createServer((socket) => {
    socket.pipe(socket)
  })
  const upPort = await new Promise<number>((resolve) => {
    upstream.listen(0, '127.0.0.1', () =>
      resolve((upstream.address() as net.AddressInfo).port))
  })
  // 监听端口也取 OS 空闲口（本机部分端口段被系统保留，固定口会 10048）
  const listenPort = await new Promise<number>((resolve) => {
    const srv = net.createServer()
    srv.listen(0, '127.0.0.1', () => {
      const p = (srv.address() as net.AddressInfo).port
      srv.close(() => resolve(p))
    })
  })
  try {
    await page.goto(`${BRIDGE}/app/?kit=pf#/bridge`, { waitUntil: 'domcontentloaded' })
    await expect(page.locator('#pf-br-uh')).toBeVisible({ timeout: 20_000 })

    // 启动桥（上游 = echo 服务）
    await page.locator('#pf-br-uh').fill('127.0.0.1')
    await page.locator('#pf-br-up').fill(String(upPort))
    await page.locator('#pf-br-lp').fill(String(listenPort))
    await page.getByRole('button', { name: '启动桥接' }).click()
    await expect(
      page.locator('.pf-v6-c-label').filter({ hasText: '已连接' }),
    ).toBeVisible({ timeout: 15_000 })

    // TCP 探针：STARTDT_ACT 经桥回环原样返回
    const echoed = await new Promise<Buffer>((resolve, reject) => {
      const sock = net.connect(listenPort, '127.0.0.1', () => {
        sock.write(STARTDT_ACT)
      })
      sock.on('data', (d) => resolve(d))
      sock.on('error', reject)
      setTimeout(() => {
        sock.destroy()
        reject(new Error('bridge relay timeout'))
      }, 10_000)
    })
    expect(echoed.subarray(0, STARTDT_ACT.length).equals(STARTDT_ACT)).toBe(true)

    // 页面实时帧（WS frame 事件 → FrameViewer）与统计刷新（bridge-stats 节流）
    await expect(page.locator('[data-testid="frame-row"]').first()).toBeVisible({
      timeout: 15_000,
    })
    await expect(
      page.locator('.pf-v6-c-description-list__description').filter({ hasText: /^[1-9]/ }).first(),
    ).toBeVisible({ timeout: 15_000 })

    // 停止桥
    await page.getByRole('button', { name: '停止桥接' }).click()
    await expect(
      page.locator('.pf-v6-c-label').filter({ hasText: '未连接' }),
    ).toBeVisible({ timeout: 15_000 })
  } finally {
    upstream.close()
  }
})
