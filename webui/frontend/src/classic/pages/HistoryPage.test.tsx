import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HistoryPage } from './HistoryPage'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function dataRow(i: number): Record<string, unknown> {
  return {
    id: i,
    ts: 1730000000 + i,
    point_type: 'yc',
    ioa: 200 + i,
    value: `v-${i}`,
    quality: '',
    source: 'spont',
  }
}

function frameRow(i: number): Record<string, unknown> {
  return {
    id: i,
    ts: 1730000000 + i,
    direction: 'rx',
    frame_type: 'I',
    hex: `DEADBEEF0${i}`,
    parsed: '',
    client: '1',
  }
}

const ENABLED_STATS = {
  ok: true,
  enabled: true,
  stats: {
    data_records: 2,
    frame_records: 1,
    buffered_data: 0,
    buffered_frames: 0,
    oldest_data: 1730000000,
    newest_data: 1730000002,
    db_size_bytes: 2048,
    dropped_records: 0,
  },
}

describe('HistoryPage（历史查询）', () => {
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
          <HistoryPage />
        </AntdApp>
      </QueryClientProvider>,
    )
  }

  it('渲染数据历史表格与统计标签', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.startsWith('/api/history/stats')) return jsonResponse(ENABLED_STATS)
        if (url.startsWith('/api/history/data')) {
          return jsonResponse({ ok: true, enabled: true, rows: [dataRow(1), dataRow(2)] })
        }
        return jsonResponse({ ok: true, enabled: true, rows: [] })
      }),
    )
    setup()
    await waitFor(() => expect(screen.getByText('v-2')).toBeInTheDocument())
    expect(screen.getByText('数据 2')).toBeInTheDocument()
    expect(screen.getByText('报文 1')).toBeInTheDocument()
    expect(screen.getByText('2.0 KB')).toBeInTheDocument()
  })

  it('切换报文页签后请求 /api/history/frames 并渲染 HEX', async () => {
    const fetchMock = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.startsWith('/api/history/stats')) return jsonResponse(ENABLED_STATS)
      if (url.startsWith('/api/history/frames')) {
        return jsonResponse({ ok: true, enabled: true, rows: [frameRow(9)] })
      }
      return jsonResponse({ ok: true, enabled: true, rows: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    setup()

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u]) => String(u).startsWith('/api/history/data')),
      ).toBe(true),
    )
    fireEvent.click(screen.getByText('报文'))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u]) => String(u).startsWith('/api/history/frames')),
      ).toBe(true),
    )
    await waitFor(() => expect(screen.getByText('DEADBEEF09')).toBeInTheDocument())
  })

  it('历史库未启用时显示提示并禁用导出', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          ok: true,
          enabled: false,
          // 契约：未启用时后端仍返回同形状的零值统计（字段全必填）
          stats: {
            data_records: 0,
            frame_records: 0,
            buffered_data: 0,
            buffered_frames: 0,
            oldest_data: 0,
            newest_data: 0,
            db_size_bytes: 0,
            dropped_records: 0,
          },
          rows: [],
        }),
      ),
    )
    setup()
    await waitFor(() => expect(screen.getByText('历史库未启用')).toBeInTheDocument())
    const exportBtn = screen.getByRole('button', { name: /导出 CSV/ })
    expect(exportBtn).toBeDisabled()
  })
})
