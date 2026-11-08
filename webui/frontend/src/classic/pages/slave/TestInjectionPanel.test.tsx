import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TestInjectionPanel } from './TestInjectionPanel'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <TestInjectionPanel />
      </AntdApp>
    </QueryClientProvider>,
  )
}

describe('TestInjectionPanel（测试报文注入，T19 补齐旧页能力④）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('继保事件 M_EP：/api/slave/ep 请求体正确', async () => {
    const posts: Array<{ path: string; body: Record<string, unknown> }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        if (url.startsWith('/api/slave/ep')) {
          posts.push({ path: '/api/slave/ep', body: JSON.parse(String(init?.body ?? '{}')) })
          return jsonResponse({ ok: true })
        }
        return jsonResponse({ ok: true })
      }),
    )
    setup()

    const spinbuttons = screen.getAllByRole('spinbutton')
    // 继保事件 IOA / 事件值 两个数字输入（带时标开关不改）
    fireEvent.click(screen.getByRole('button', { name: /上送 M_EP/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body.ioa).toBe(5001)
    expect(posts[0].body.event_value).toBe(1)
    expect(posts[0].body.with_time).toBe(true)
    void spinbuttons
  })

  it('成组单点 M_PS：状态位解析为 0/1 数组', async () => {
    const posts: Array<{ path: string; body: Record<string, unknown> }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        if (url.startsWith('/api/slave/ps')) {
          posts.push({ path: '/api/slave/ps', body: JSON.parse(String(init?.body ?? '{}')) })
          return jsonResponse({ ok: true })
        }
        return jsonResponse({ ok: true })
      }),
    )
    setup()

    const statesInput = screen.getByPlaceholderText('状态位 1,0,1')
    fireEvent.change(statesInput, { target: { value: '1, 0, 1' } })
    fireEvent.click(screen.getByRole('button', { name: /上送 M_PS/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body.ioa).toBe(5101)
    expect(posts[0].body.states).toEqual([1, 0, 1])
  })

  it('M_PS 非法状态位（无 0/1）不发请求', async () => {
    const post = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        if (String(input).startsWith('/api/slave/ps')) return post()
        return jsonResponse({ ok: true })
      }),
    )
    setup()
    const statesInput = screen.getByPlaceholderText('状态位 1,0,1')
    fireEvent.change(statesInput, { target: { value: 'x,y' } })
    fireEvent.click(screen.getByRole('button', { name: /上送 M_PS/ }))
    await waitFor(() => expect(screen.getByText(/状态位须为 0\/1/)).toBeInTheDocument())
    expect(post).not.toHaveBeenCalled()
  })
})
