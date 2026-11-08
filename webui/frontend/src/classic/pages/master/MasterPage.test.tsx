import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { queryKeys } from '../../api/queries'
import type { Point } from '../../api/types'
import { trendBuffer } from '../../lib/trendBuffer'
import MasterPage from './MasterPage'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

const POINTS: Point[] = [
  { ioa: 1001, type: 'YC', name: 'YC_0001', enabled: true, value: 0, subtype: 'short_float' },
  { ioa: 1008, type: 'YC', name: 'YC_0008', enabled: true, value: 12.5, subtype: 'short_float' },
  {
    ioa: 201,
    type: 'YK',
    name: 'YK_SBO_TRUE',
    enabled: true,
    value: '—',
    subtype: 'single',
    sbo: true,
  },
]

interface Post {
  path: string
  body: Record<string, unknown>
}

function stubFetch(posts?: Post[]): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown, init?: RequestInit) => {
      const url = String(input)
      if (url.startsWith('/api/status')) {
        return jsonResponse({ role: 'master', running: true, started: true, schemaVersion: 1 })
      }
      if (url.startsWith('/api/points')) {
        return jsonResponse({ points: POINTS })
      }
      if (init?.method === 'POST') {
        posts?.push({
          path: url,
          body: JSON.parse(String(init.body ?? '{}')) as Record<string, unknown>,
        })
      }
      return jsonResponse({ ok: true })
    }),
  )
}

const ROW = '.ant-table-tbody .ant-table-row'

describe('MasterPage（主站工作台）命令面板当前值实时刷新', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function setup(posts?: Post[]) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    stubFetch(posts)
    render(
      <QueryClientProvider client={client}>
        <AntdApp>
          <MasterPage />
        </AntdApp>
      </QueryClientProvider>,
    )
    return client
  }

  it('选中行后 WS 增量补丁更新缓存 → 命令面板「当前值」跟随刷新', async () => {
    const client = setup()
    await screen.findByText('YC_0008')

    // 选中 YC_0008 行
    const row = document.querySelector(ROW) as HTMLElement | null
    expect(row).toBeTruthy()
    fireEvent.click(screen.getByText('YC_0008'))

    // 面板出现「已选」标记与当前值（初始 12.5）——点表卡片与命令面板各有一个 Tag，取其一
    await waitFor(() => expect(screen.getAllByText(/已选 YC-1008/).length).toBeGreaterThan(0))
    await waitFor(() => expect(screen.getByText(/当前值 12\.5/)).toBeInTheDocument())

    // 模拟 WS 增量补丁落地：只更新点表缓存（useWsBridge 的 applyPatches 路径）
    const patched: Point[] = POINTS.map((p) =>
      p.ioa === 1008 ? { ...p, value: 66.6 } : p,
    )
    client.setQueryData(queryKeys.points(), patched)

    // 命令面板「当前值」必须跟随缓存变化（此前是选中瞬间的快照，永远不变）
    await waitFor(() => expect(screen.getByText(/当前值 66\.6/)).toBeInTheDocument())
  })

  it('点「加入趋势」即注册采样，无需先打开趋势图页签', { timeout: 120_000 }, async () => {
    setup()
    await screen.findByText('YC_0008')
    const setWatchedSpy = vi.spyOn(trendBuffer, 'setWatched')

    // 先选中行，「加入趋势」按钮才可用
    fireEvent.click(screen.getByText('YC_0008'))
    await waitFor(() => expect(screen.getAllByText(/已选 YC-1008/).length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: /加入趋势/ }))

    await waitFor(() => expect(setWatchedSpy).toHaveBeenCalledWith(['YC-1008']))
  })

  it('双击 YK 值单元格 → 确认弹窗 → 下发遥控命令并选中目标行', async () => {
    const posts: Post[] = []
    setup(posts)
    await screen.findByText('YC_0008')

    fireEvent.doubleClick(screen.getByTestId('point-value-YK-201'))
    await waitFor(() => expect(screen.getByText(/下发遥控命令/)).toBeInTheDocument())
    // 双击同时把该行带入右侧命令面板
    await waitFor(() => expect(screen.getAllByText(/已选 YK-201/).length).toBeGreaterThan(0))

    fireEvent.click(screen.getByRole('button', { name: /确\s*认\s*下\s*发/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].path).toBe('/api/master/yk')
    expect(posts[0].body).toMatchObject({ ioa: 201, state: 1, select: false, double: false })
  })
})
