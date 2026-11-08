import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { StatusPage } from './StatusPage'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <StatusPage />
      </AntdApp>
    </QueryClientProvider>,
  )
}

describe('StatusPage（对接真实 REST 契约）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('渲染 /api/status 与 /api/points 返回的数据', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.startsWith('/api/status')) {
          return jsonResponse({
            role: 'master',
            started: true,
            running: true,
            host: '127.0.0.1',
            port: 2404,
            addr: 1,
            points: 1,
            dropped: 0,
            schemaVersion: 1,
          })
        }
        if (url.startsWith('/api/points')) {
          return jsonResponse({
            points: [
              { ioa: 1, type: 'M_SP_NA_1', name: 'YX-遥信-1', enabled: true, value: true },
            ],
          })
        }
        return jsonResponse({ ok: true })
      }),
    )

    renderPage()

    // 点表数据落地 → 证明 REST 客户端 + React Query + 表格链路通畅
    await waitFor(() => expect(screen.getByText('YX-遥信-1')).toBeInTheDocument())
    expect(screen.getByText('连接与命令')).toBeInTheDocument()
    expect(screen.getByText('总召唤')).toBeInTheDocument()
  })

  it('后端不可用时只报错、不崩溃', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 500,
        headers: { get: () => 'application/json' },
        text: async () => JSON.stringify({ ok: false, error: 'boom' }),
      } as unknown as Response)),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText(/读取 \/api\/status 失败/)).toBeInTheDocument())
  })
})
