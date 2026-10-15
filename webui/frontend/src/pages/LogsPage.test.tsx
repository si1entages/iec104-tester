import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { appendLiveLogs, replaceLiveLogs } from '../api/queries'
import type { LogRow } from '../api/types'
import { LogsPage } from './LogsPage'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function logRow(i: number, over: Partial<LogRow> = {}): LogRow {
  return {
    ts: 1730000000 + i,
    level: 'INFO',
    source: 'engine',
    category: 'protocol',
    message: `log-${i}`,
    ...over,
  }
}

describe('LogsPage（日志面板）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function setup() {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    const utils = render(
      <QueryClientProvider client={client}>
        <AntdApp>
          <LogsPage />
        </AntdApp>
      </QueryClientProvider>,
    )
    return { client, ...utils }
  }

  it('渲染 /api/logs 历史日志与统计', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.startsWith('/api/logs')) {
          return jsonResponse({
            ok: true,
            logs: [logRow(1, { level: 'ERROR', message: 'boom-error' }), logRow(2)],
            stats: { total: 42 },
          })
        }
        return jsonResponse({ ok: true })
      }),
    )
    setup()
    await waitFor(() => expect(screen.getByText('boom-error')).toBeInTheDocument())
    expect(screen.getByText('log-2')).toBeInTheDocument()
    expect(screen.getByText('后端累计 42')).toBeInTheDocument()
  })

  it('级别多选过滤：取消 INFO 后实时流里的 INFO 行消失', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ok: true, logs: [], stats: {} })),
    )
    const { client, container } = setup()

    act(() => {
      replaceLiveLogs(client, [
        logRow(1, { level: 'INFO', message: 'info-row' }),
        logRow(2, { level: 'ERROR', message: 'error-row' }),
      ])
    })

    await waitFor(() => expect(screen.getByText('info-row')).toBeInTheDocument())
    expect(screen.getByText('error-row')).toBeInTheDocument()

    // 打开级别下拉并取消勾选 INFO（maxTagCount=responsive 在 jsdom 里不渲染选中标签，
    // 直接用容器定位第一个 Select——级别多选是过滤行里的第一个）
    const levelSelect = container.querySelector('.ant-select .ant-select-selector')
    expect(levelSelect).not.toBeNull()
    fireEvent.mouseDown(levelSelect as Element, { button: 0 })
    // 可视选项在打开的 dropdown 里（role="listbox" 是 rc-select 的隐藏无障碍列表，别用它）
    const infoOption = await waitFor(() => {
      const el =
        document.querySelector<HTMLElement>(
          '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="INFO"]',
        ) ??
        Array.from(
          document.querySelectorAll<HTMLElement>(
            '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option',
          ),
        ).find((el) => el.textContent === 'INFO')
      expect(el).not.toBeNull()
      return el as HTMLElement
    })
    fireEvent.click(infoOption)

    await waitFor(() => expect(screen.queryByText('info-row')).not.toBeInTheDocument())
    expect(screen.getByText('error-row')).toBeInTheDocument()
  })

  it('关键字搜索过滤实时流', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ok: true, logs: [], stats: {} })),
    )
    const { client } = setup()
    act(() => {
      replaceLiveLogs(client, [
        logRow(1, { message: 'connection established' }),
        logRow(2, { message: 'gi finished' }),
      ])
    })
    await waitFor(() => expect(screen.getByText('connection established')).toBeInTheDocument())

    const input = screen.getByPlaceholderText('关键字搜索')
    fireEvent.change(input, { target: { value: 'gi' } })
    // antd Input.Search 回车触发 onSearch
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13 })

    await waitFor(() => expect(screen.queryByText('connection established')).not.toBeInTheDocument())
    expect(screen.getByText('gi finished')).toBeInTheDocument()
  })

  it('暂停冻结视图、缓冲继续；恢复后新日志合入（不丢失）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ok: true, logs: [], stats: {} })),
    )
    const { client } = setup()
    act(() => {
      replaceLiveLogs(client, [logRow(1, { message: 'before-pause' })])
    })
    await waitFor(() => expect(screen.getByText('before-pause')).toBeInTheDocument())

    // 暂停
    fireEvent.click(screen.getByRole('button', { name: /暂停实时/ }))
    act(() => {
      appendLiveLogs(client, [logRow(2, { message: 'while-paused' })])
    })
    // 视图被冻结：新日志不出现，但缓冲计数上升
    expect(screen.queryByText('while-paused')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/新缓冲 1 条/)).toBeInTheDocument())

    // 恢复 → 合入，不丢
    fireEvent.click(screen.getByRole('button', { name: /恢复实时/ }))
    await waitFor(() => expect(screen.getByText('while-paused')).toBeInTheDocument())
    expect(screen.queryByText(/新缓冲/)).not.toBeInTheDocument()
  })

  it('清空视图只清实时缓冲，历史查询与导出不受影响', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        if (String(input).startsWith('/api/logs')) {
          return jsonResponse({ ok: true, logs: [logRow(9, { message: 'history-row' })], stats: {} })
        }
        return jsonResponse({ ok: true })
      }),
    )
    const { client } = setup()
    act(() => {
      replaceLiveLogs(client, [logRow(1, { message: 'live-row' })])
    })
    await waitFor(() => expect(screen.getByText('live-row')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('history-row')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /清空视图/ }))
    await waitFor(() => expect(screen.queryByText('live-row')).not.toBeInTheDocument())
    // 历史仍在（清空仅作用于视图缓冲）
    expect(screen.getByText('history-row')).toBeInTheDocument()
    // 缓冲标签归零
    expect(screen.getByText('缓冲 0')).toBeInTheDocument()
  })

  it('合并结果达到视图上限时截断并明示', async () => {
    // 实时缓冲上限 500，历史补 600 → 合并 1100 → 视图截到 1000
    const live = Array.from({ length: 500 }, (_, i) => logRow(100000 + i, { message: `bulk-live-${i}` }))
    const historyRows = Array.from({ length: 600 }, (_, i) => logRow(i, { message: `bulk-hist-${i}` }))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        if (String(input).startsWith('/api/logs')) {
          return jsonResponse({ ok: true, logs: historyRows, stats: {} })
        }
        return jsonResponse({ ok: true })
      }),
    )
    const { client } = setup()
    act(() => {
      replaceLiveLogs(client, live)
    })
    // 触达截断线：合并 1100 → 视图 1000（注意：antd Table 分页下仅当前页在 DOM）
    await waitFor(() => expect(screen.getByText(/已截断（上限 1000）/)).toBeInTheDocument())
    expect(screen.getByText('视图 1000')).toBeInTheDocument()
    expect(screen.getByText('共 1000 条')).toBeInTheDocument()
    // 第 1 页显示最新的实时行；被截掉的是列表尾部最旧的历史行
    expect(screen.getByText('bulk-live-499')).toBeInTheDocument()
    expect(screen.queryByText('bulk-hist-0')).not.toBeInTheDocument()
  })

  it('高频日志批量合并：多次追加只有最后一次视图结果生效（无中间态丢失）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ok: true, logs: [], stats: {} })),
    )
    const { client } = setup()
    act(() => {
      for (let i = 0; i < 100; i += 1) {
        appendLiveLogs(client, [logRow(i, { message: `burst-${i}` })])
      }
    })
    await waitFor(() => expect(screen.getByText('burst-99')).toBeInTheDocument())
    // 全部落地（缓冲 100）
    expect(screen.getByText('缓冲 100')).toBeInTheDocument()
  })
})
