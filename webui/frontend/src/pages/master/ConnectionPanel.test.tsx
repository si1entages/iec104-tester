import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

    // label 与输入框分离后：周期总召在 Form.Item 内，label 不再挤占输入框宽度
    const giInput = screen
      .getAllByRole('spinbutton')
      .find((el) => el.closest('.ant-form-item')?.textContent?.includes('周期总召(秒)'))
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

  it('冗余开关 + 备用地址随 start 请求体下发（E3）', async () => {
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

    const label = screen.getByText('冗余双通道')
    const group = label.closest('.ant-space') as HTMLElement
    const redSwitch = within(group).getByRole('switch')
    fireEvent.click(redSwitch)

    fireEvent.change(screen.getByLabelText('备用地址'), { target: { value: '10.0.0.2' } })
    fireEvent.change(screen.getByLabelText('备用端口'), { target: { value: '2406' } })
    fireEvent.change(screen.getByLabelText('切换超时(s)'), { target: { value: '3' } })

    fireEvent.click(screen.getByRole('button', { name: /连\s*接/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body.redundancy).toEqual({
      enabled: true,
      standby_host: '10.0.0.2',
      standby_port: 2406,
      switch_timeout: 3,
    })
  })
})
