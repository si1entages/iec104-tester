import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SimulationPanel } from './SimulationPanel'
import type { Point } from '../../api/types'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

/** /api/status 必须可用（面板会读 status.simulation 做对账） */
function stubFetch(simulation = false): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (input: unknown) => {
    const url = String(input)
    if (url.startsWith('/api/status')) {
      return jsonResponse({ role: 'slave', running: true, simulation, schemaVersion: 1 })
    }
    return jsonResponse({ ok: true })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPanel(disabled = false, selected: Point | null = null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <SimulationPanel disabled={disabled} selected={selected} />
      </AntdApp>
    </QueryClientProvider>,
  )
}

function lastSimPost(fetchMock: ReturnType<typeof vi.fn>): Record<string, unknown> {
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][]
  for (let i = calls.length - 1; i >= 0; i -= 1) {
    const [url, init] = calls[i]
    if (url === '/api/slave/sim') {
      return JSON.parse(String(init.body)) as Record<string, unknown>
    }
  }
  throw new Error('没有捕获到 /api/slave/sim 调用')
}

describe('SimulationPanel（子站模拟控制，第二批改造⑤）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('默认（全部点/全部点）：启动请求带 scope=all', async () => {
    const fetchMock = stubFetch(false)
    renderPanel()

    await waitFor(() => expect(screen.getByRole('button', { name: '启动模拟' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '启动模拟' }))

    await waitFor(() =>
      expect(lastSimPost(fetchMock)).toEqual({
        enabled: true,
        yx_interval: 5,
        yc_interval: 2,
        yx_change_rate: 0.1,
        yc_change_range: 0.05,
        yx_scope: 'all',
        yc_scope: 'all',
      }),
    )
  })

  it('文案改名：YX 为「每周期翻转概率」，YC 为「无量程点浮动比例」', async () => {
    stubFetch(false)
    renderPanel()

    await waitFor(() => expect(screen.getByText('每周期翻转概率')).toBeInTheDocument())
    expect(screen.getByText('无量程点浮动比例')).toBeInTheDocument()
    // 旧文案不再出现
    expect(screen.queryByText('YX 变化率')).toBeNull()
    expect(screen.queryByText('YC 变化幅度')).toBeNull()
  })

  it('YX scope=selected：带 yx_ioas=[选中 IOA]；YC 仍为 all', async () => {
    const fetchMock = stubFetch(false)
    renderPanel(false, { ioa: 1, type: 'YX', name: '开关1', enabled: true })

    await waitFor(() => expect(screen.getByRole('button', { name: '启动模拟' })).toBeEnabled())
    // 两个范围 Segmented：第一个是 YX
    const segmenteds = screen.getAllByRole('radiogroup')
    fireEvent.click(within(segmenteds[0]).getByText('选中点'))
    fireEvent.click(screen.getByRole('button', { name: '启动模拟' }))

    await waitFor(() => {
      const body = lastSimPost(fetchMock)
      expect(body.yx_scope).toBe('selected')
      expect(body.yx_ioas).toEqual([1])
      expect(body.yc_scope).toBe('all')
    })
  })

  it('scope=selected 但选中点类型不匹配 → 阻止下发并提示', async () => {
    const fetchMock = stubFetch(false)
    renderPanel(false, { ioa: 101, type: 'YC', name: '温度', enabled: true })

    await waitFor(() => expect(screen.getByRole('button', { name: '启动模拟' })).toBeEnabled())
    const segmenteds = screen.getAllByRole('radiogroup')
    fireEvent.click(within(segmenteds[0]).getByText('选中点')) // YX 范围=选中点，但选中的是 YC
    fireEvent.click(screen.getByRole('button', { name: '启动模拟' }))

    await waitFor(() => expect(screen.getByText(/请先在点表选中一个 YX 点/)).toBeInTheDocument())
    const calls = (fetchMock.mock.calls as unknown as [string][]).filter(([u]) => u === '/api/slave/sim')
    expect(calls).toHaveLength(0)
  })

  it('后端正在模拟 → 按钮变「停止模拟」，下发 enabled=false（不带变化参数）', async () => {
    const fetchMock = stubFetch(true)
    renderPanel()

    await waitFor(() => expect(screen.getByRole('button', { name: '停止模拟' })).toBeEnabled(), {
      timeout: 10000,
    })
    fireEvent.click(screen.getByRole('button', { name: '停止模拟' }))

    await waitFor(() => expect(lastSimPost(fetchMock)).toEqual({ enabled: false }))
  })

  it('子站未启动时不可下发', () => {
    stubFetch(false)
    renderPanel(true)

    expect(screen.getByRole('button', { name: /模拟/ })).toBeDisabled()
    expect(screen.getByText('子站未启动，模拟不可用')).toBeInTheDocument()
  })
})
