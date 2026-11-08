import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ResponsePanel } from './ResponsePanel'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function renderPanel(disabled = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <ResponsePanel disabled={disabled} />
      </AntdApp>
    </QueryClientProvider>,
  )
}

function lastPost(fetchMock: ReturnType<typeof vi.fn>): { path: string; body: Record<string, unknown> } {
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][]
  for (let i = calls.length - 1; i >= 0; i -= 1) {
    const [url, init] = calls[i]
    if (init?.method === 'POST') {
      return { path: url, body: JSON.parse(String(init.body)) as Record<string, unknown> }
    }
  }
  throw new Error('没有捕获到 POST 调用')
}

describe('ResponsePanel（子站应答行为配置）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('默认「正常应答」：应用后下发全默认配置', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    renderPanel()
    expect(screen.getByText('正常应答')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '应用配置' }))

    await waitFor(() => expect(lastPost(fetchMock).path).toBe('/api/slave/response'))
    expect(lastPost(fetchMock).body).toEqual({
      delays: { gi: 0, command: 0, data: 0 },
      errors: {
        drop_frames: false,
        drop_rate: 0,
        corrupt: false,
        no_response: false,
        wrong_cot: false,
      },
      quality: {
        invalid: false,
        blocked: false,
        substituted: false,
        not_topical: false,
        overflow: false,
      },
      connection: {
        reject_startdt: false,
        auto_stopdt: false,
        send_testfr: false,
        testfr_interval: 20,
      },
    })
  })

  it('打开「返回错误 COT」并设置丢帧比例后，body 携带 wrong_cot / drop_rate', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    renderPanel()

    // 错误注入面板默认展开
    const wrongCot = screen.getByRole('switch', { name: '返回错误 COT（wrong_cot）' })
    fireEvent.click(wrongCot)
    await waitFor(() => expect(wrongCot).toHaveAttribute('aria-checked', 'true'))

    const label = screen.getByText('丢帧比例 drop_rate')
    const rateInput = label.closest('.ant-space-item')?.parentElement?.querySelector('input')
    expect(rateInput).toBeTruthy()
    fireEvent.change(rateInput as HTMLInputElement, { target: { value: '0.3' } })
    fireEvent.blur(rateInput as HTMLInputElement)

    // 顶部 Tag 立即反映已激活的注入项（丢帧率一起出现）
    await waitFor(() => expect(screen.getByText(/^错误 COT \/ 丢帧率 0\.3$/)).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '应用配置' }))

    await waitFor(() => expect(lastPost(fetchMock).path).toBe('/api/slave/response'))
    const errors = lastPost(fetchMock).body.errors as Record<string, unknown>
    expect(errors.wrong_cot).toBe(true)
    expect(errors.drop_rate).toBeCloseTo(0.3, 5)
  })

  it('「恢复默认并应用」把配置复位后下发', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    renderPanel()
    const wrongCot = screen.getByRole('switch', { name: '返回错误 COT（wrong_cot）' })
    fireEvent.click(wrongCot) // wrong_cot = true
    await waitFor(() => expect(wrongCot).toHaveAttribute('aria-checked', 'true'))

    fireEvent.click(screen.getByRole('button', { name: '恢复默认并应用' }))

    await waitFor(() => {
      const errors = lastPost(fetchMock).body.errors as Record<string, unknown>
      expect(errors.wrong_cot).toBe(false)
    })
    expect(screen.getByText('正常应答')).toBeInTheDocument()
  })
})
