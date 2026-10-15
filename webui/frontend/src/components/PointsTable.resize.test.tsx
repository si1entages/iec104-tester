import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { PointsTable } from './PointsTable'
import type { Point } from '../api/types'

const POINTS: Point[] = [
  { ioa: 1, type: 'YX', name: '开关1', enabled: true, value: 'ON' },
  { ioa: 2, type: 'YX', name: '开关2', enabled: false, value: 'OFF' },
  { ioa: 101, type: 'YC', name: '温度', enabled: true, value: 25.5 },
  { ioa: 301, type: 'YM', name: '电度', enabled: true, value: 0 },
]

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function renderTable(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse({ points: POINTS })),
  )
  render(
    <QueryClientProvider client={client}>
      <PointsTable selected={null} onSelect={() => undefined} />
    </QueryClientProvider>,
  )
}

function colWidths(): number[] {
  return Array.from(document.querySelectorAll('.ant-table col')).map(
    (c) => Number((c as HTMLElement).style.width.replace('px', '')) || 0,
  )
}

describe('PointsTable（列宽拖拽，第二批改造③）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('每个表头都有拖拽热区（.col-resizer）', async () => {
    renderTable()
    await waitFor(() => expect(screen.getAllByText('开关1').length).toBeGreaterThan(0))
    // 7 个业务列 + rowSelection 列
    const handles = document.querySelectorAll('.col-resizer')
    expect(handles.length).toBeGreaterThanOrEqual(7)
  })

  it('拖拽热区向右移动 80px → 对应列变宽（会话内记忆）', async () => {
    renderTable()
    await waitFor(() => expect(screen.getAllByText('开关1').length).toBeGreaterThan(0))

    const before = colWidths()
    const handles = document.querySelectorAll('.col-resizer')
    // 拖第三个业务列（名称列）。jsdom 的 PointerEvent 不带 clientX，
    // 用 MouseEvent + pointer* 事件名派发（React/原生监听都按类型名匹配）。
    const target = handles[2] as HTMLElement
    fireEvent(target, new MouseEvent('pointerdown', { bubbles: true, clientX: 100 }))
    fireEvent(window, new MouseEvent('pointermove', { clientX: 180 }))
    fireEvent(window, new MouseEvent('pointerup', { clientX: 180 }))

    const after = colWidths()
    const grew = after.some((w, i) => before[i] > 0 && w === before[i] + 80)
    expect(grew).toBe(true)
  })
})
