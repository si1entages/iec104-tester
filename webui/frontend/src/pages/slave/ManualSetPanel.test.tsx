import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Point } from '../../api/types'
import { ManualSetPanel } from './ManualSetPanel'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function renderPanel(point: Point | null, disabled = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <ManualSetPanel point={point} disabled={disabled} />
      </AntdApp>
    </QueryClientProvider>,
  )
}

/** 取出最近一次 POST 的 {path, body} */
function lastPost(fetchMock: ReturnType<typeof vi.fn>): { path: string; body: unknown } {
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][]
  for (let i = calls.length - 1; i >= 0; i -= 1) {
    const [url, init] = calls[i]
    if (init?.method === 'POST') {
      return { path: url, body: JSON.parse(String(init.body)) }
    }
  }
  throw new Error('没有捕获到 POST 调用')
}

describe('ManualSetPanel（子站手动置数）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('选中 YX 点位后按遥信下发 /api/slave/yx', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    renderPanel({ ioa: 100, type: 'YX', name: 'YX_0100', enabled: true, value: 'OFF' })

    // 点表选中行 → IOA 自动带入（Tag 文本被拆成多节点，故断言 body 文本）
    await waitFor(() => expect(screen.getByDisplayValue('100')).toBeInTheDocument())
    expect(document.body.textContent).toContain('已选 YX-100')

    fireEvent.click(screen.getByRole('button', { name: '下发置数' }))

    await waitFor(() => expect(lastPost(fetchMock).path).toBe('/api/slave/yx'))
    // 默认合闸 ON → value: true
    expect(lastPost(fetchMock).body).toEqual({ ioa: 100, value: true })
  })

  it('选中 STEP 点位后按步位置下发，且取值夹紧到 -64..63', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    renderPanel({ ioa: 4101, type: 'STEP', name: 'STEP_0001', enabled: true, value: 0 })

    // 选中 STEP 点 → 类别自动切到步位置，展示区间提示
    await waitFor(() => expect(screen.getByText(/取值 -64\.\.63/)).toBeInTheDocument())

    // IOA 已带入 4101；另一个取 '0' 的 spinbutton 就是步位置值
    const valueInput = screen.getByDisplayValue('0')
    fireEvent.change(valueInput, { target: { value: '999' } })
    fireEvent.blur(valueInput)
    // 越界值被夹到上限 63
    await waitFor(() => expect(screen.getByDisplayValue('63')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '下发置数' }))

    await waitFor(() => expect(lastPost(fetchMock).path).toBe('/api/slave/step'))
    expect(lastPost(fetchMock).body).toEqual({ ioa: 4101, value: 63 })
  })

  it('子站未启动时禁用下发', () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ ok: true })))
    renderPanel({ ioa: 1, type: 'YX', name: 'YX_0001', enabled: true, value: 'OFF' }, true)

    expect(screen.getByRole('button', { name: '下发置数' })).toBeDisabled()
    expect(screen.getByText('子站未启动，置数不可下发')).toBeInTheDocument()
  })
})
