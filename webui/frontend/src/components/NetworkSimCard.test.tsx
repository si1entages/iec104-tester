import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NetworkSimCard } from './NetworkSimCard'

const CONDITION = {
  delay_ms: 30,
  delay_variance_ms: 20,
  loss_rate: 0.05,
  duplicate_rate: 0,
  corrupt_rate: 0,
  corrupt_bits: 1,
  reorder_rate: 0.02,
  reorder_window: 5,
  disconnect_rate: 0,
  disconnect_duration_s: 3,
  bandwidth_bps: 0,
  direction: 'both',
  active: false,
}

function statusBody(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ok: true,
    enabled: false,
    installed: false,
    active: false,
    describe: '(none)',
    condition: CONDITION,
    stats: {},
    presets: ['clean', 'poor_wifi', 'congested', 'satellite', 'unreliable', 'intermittent', 'slow_link', 'stress'],
    ...over,
  }
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

describe('NetworkSimCard（网络异常模拟）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function setup() {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    return render(
      <QueryClientProvider client={client}>
        <AntdApp>
          <NetworkSimCard />
        </AntdApp>
      </QueryClientProvider>,
    )
  }

  it('渲染状态标签与未安装提示', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(statusBody())))
    setup()
    await waitFor(() => expect(screen.getByText('引擎未启动')).toBeInTheDocument())
    expect(screen.getByText('已停用')).toBeInTheDocument()
    expect(screen.getByText(/未安装到引擎/)).toBeInTheDocument()
  })

  it('切换开关向后端发送 enabled=true', async () => {
    const fetchMock = vi.fn(async (input: unknown, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/simulation' && init?.method === 'POST') {
        return jsonResponse({ ok: true, status: statusBody({ enabled: true }) })
      }
      return jsonResponse(statusBody())
    })
    vi.stubGlobal('fetch', fetchMock)
    setup()
    await waitFor(() => expect(screen.getByRole('switch')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([u, init]) => String(u) === '/api/simulation' && (init as RequestInit)?.method === 'POST',
      )
      expect(post).toBeTruthy()
      expect(JSON.parse(String((post?.[1] as RequestInit).body))).toEqual({ enabled: true })
    })
  })

  it('已安装时展示 RX/TX 统计', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          statusBody({
            enabled: true,
            installed: true,
            active: true,
            describe: 'delay=30.0ms±20.0ms, loss=5%',
            stats: {
              rx_total: 10,
              tx_total: 8,
              rx_dropped: 1,
              tx_dropped: 0,
              rx_corrupted: 0,
              tx_corrupted: 0,
              rx_duplicated: 0,
              tx_duplicated: 0,
              rx_reordered: 0,
              tx_reordered: 0,
              disconnects: 2,
            },
          }),
        ),
      ),
    )
    setup()
    await waitFor(() => expect(screen.getByText('已安装')).toBeInTheDocument())
    expect(screen.getByText(/RX 总 10 · 丢 1/)).toBeInTheDocument()
    expect(screen.getByText(/断线 2/)).toBeInTheDocument()
  })
})
