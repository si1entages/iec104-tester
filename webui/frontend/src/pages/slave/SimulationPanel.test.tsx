import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SimulationPanel } from './SimulationPanel'

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

function renderPanel(disabled = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <SimulationPanel disabled={disabled} />
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

describe('SimulationPanel（子站模拟控制）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('选择随机变化并应用 → 下发 enabled=true 与变化参数', async () => {
    const fetchMock = stubFetch(false)
    renderPanel()

    // 后端未模拟 → 默认跟随后端为「手动」；切到随机变化后才需要下发
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: '手动置数（不自动变化）' })).toBeChecked(),
    )
    fireEvent.click(screen.getByRole('radio', { name: '随机变化（自动模拟）' }))
    fireEvent.click(screen.getByRole('button', { name: '启动模拟' }))

    await waitFor(() =>
      expect(lastSimPost(fetchMock)).toEqual({
        enabled: true,
        yx_interval: 5,
        yc_interval: 2,
        yx_change_rate: 0.1,
        yc_change_range: 0.05,
      }),
    )
  })

  it('后端正在模拟时切回手动 → 下发 enabled=false（不带变化参数）', async () => {
    const fetchMock = stubFetch(true)
    renderPanel()

    await waitFor(() =>
      expect(screen.getByRole('radio', { name: '随机变化（自动模拟）' })).toBeChecked(),
    )
    fireEvent.click(screen.getByRole('radio', { name: '手动置数（不自动变化）' }))
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
