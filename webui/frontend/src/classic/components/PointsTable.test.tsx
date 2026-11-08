import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

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

function renderTable(onValueDoubleClick?: (point: Point) => void): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse({ points: POINTS })),
  )
  render(
    <QueryClientProvider client={client}>
      <PointsTable
        selected={null}
        onSelect={() => undefined}
        onValueDoubleClick={onValueDoubleClick}
      />
    </QueryClientProvider>,
  )
}

function rowsText(): string {
  return Array.from(document.querySelectorAll('.ant-table-tbody .ant-table-row'))
    .map((r) => r.textContent ?? '')
    .join('\n')
}

describe('PointsTable（类型页签，第二批改造②）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('默认「全部」页签：显示所有点', async () => {
    renderTable()
    await waitFor(() => expect(screen.getAllByText('开关1').length).toBeGreaterThan(0))
    const text = rowsText()
    expect(text).toContain('开关1')
    expect(text).toContain('温度')
    expect(text).toContain('电度')
  })

  it('切到 YC 页签：只剩 YC 点，计数徽标同步', async () => {
    renderTable()
    await waitFor(() => expect(screen.getAllByText('开关1').length).toBeGreaterThan(0))

    fireEvent.click(screen.getByRole('radio', { name: 'YC' }))
    const text = rowsText()
    expect(text).toContain('温度')
    expect(text).not.toContain('开关1')
    expect(text).not.toContain('电度')
    expect(screen.getByText('1')).toBeInTheDocument() // 计数 Tag
  })

  it('切回「全部」：恢复全表', async () => {
    renderTable()
    await waitFor(() => expect(screen.getAllByText('温度').length).toBeGreaterThan(0))

    fireEvent.click(screen.getByRole('radio', { name: 'YX' }))
    expect(rowsText()).not.toContain('温度')
    fireEvent.click(screen.getByRole('radio', { name: '全部' }))
    expect(rowsText()).toContain('温度')
    expect(rowsText()).toContain('电度')
  })

  it('页签与关键字过滤叠加生效', async () => {
    renderTable()
    await waitFor(() => expect(screen.getAllByText('温度').length).toBeGreaterThan(0))

    fireEvent.click(screen.getByRole('radio', { name: 'YX' }))
    fireEvent.change(screen.getByPlaceholderText('按名称 / IOA 过滤'), { target: { value: '开关1' } })
    const text = rowsText()
    expect(text).toContain('开关1')
    expect(text).not.toContain('开关2') // 关键字只命中开关1
    expect(text).not.toContain('温度')
  })

  it('双击「值」单元格回调点位；双击名称列不触发', async () => {
    const onValueDoubleClick = vi.fn()
    renderTable(onValueDoubleClick)
    await waitFor(() => expect(screen.getAllByText('温度').length).toBeGreaterThan(0))

    fireEvent.doubleClick(screen.getByTestId('point-value-YC-101'))
    expect(onValueDoubleClick).toHaveBeenCalledTimes(1)
    expect(onValueDoubleClick).toHaveBeenCalledWith(POINTS[2])

    fireEvent.doubleClick(screen.getByText('温度'))
    expect(onValueDoubleClick).toHaveBeenCalledTimes(1)
  })
})
