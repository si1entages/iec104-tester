import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ConnectionPanel } from './ConnectionPanel'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

describe('ConnectionPanel（连接参数）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function setup() {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    render(
      <QueryClientProvider client={client}>
        <AntdApp>
          <ConnectionPanel />
        </AntdApp>
      </QueryClientProvider>,
    )
  }

  it('周期总召（gi_interval）随 start 请求体下发（T19 补齐旧页能力）', async () => {
    const posts: Array<{ path: string; body: Record<string, unknown> }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        if (url.startsWith('/api/master/start')) {
          posts.push({ path: '/api/master/start', body: JSON.parse(String(init?.body ?? '{}')) })
          return jsonResponse({ ok: true })
        }
        return jsonResponse({ role: 'master', running: false, started: false })
      }),
    )
    setup()

    const giInput = screen
      .getAllByRole('spinbutton')
      .find((el) => el.closest('.ant-input-number-affix-wrapper')?.textContent?.includes('周期总召(秒)'))
    expect(giInput).toBeTruthy()
    // 默认 0 = 关闭；填 30 后点「连接」，请求体应携带 gi_interval: 30
    fireEvent.change(giInput!, { target: { value: '30' } })
    // antd 两字按钮自动插空格（「连 接」）
    fireEvent.click(screen.getByRole('button', { name: /连\s*接/ }))

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body.gi_interval).toBe(30)
    expect(posts[0].body.host).toBe('127.0.0.1')
    expect(posts[0].body.port).toBe(2404)
  })
})
