import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PointsTools } from './PointsTools'

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
  const { container } = render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <PointsTools />
      </AntdApp>
    </QueryClientProvider>,
  )
  return { container, client }
}

describe('PointsTools（点表工具，T19 补齐旧页能力②③）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('导入：按扩展名选 format，POST /api/points/import?format=csv', async () => {
    const posts: Array<{ path: string; body: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        if (url.startsWith('/api/points/import')) {
          posts.push({ path: url, body: String(init?.body ?? '') })
          return jsonResponse({ ok: true, points: 5 })
        }
        return jsonResponse({ ok: true })
      }),
    )
    const { container } = setup()

    fireEvent.click(screen.getByRole('button', { name: /导入/ }))
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    expect(input).toBeTruthy()
    const file = new File(['type,ioa,name,group,enabled\nYX,1,演示,1,true'], 'points.csv', { type: 'text/csv' })
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    fireEvent.change(input)

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].path).toContain('format=csv')
    expect(posts[0].body).toContain('YX,1,演示,1,true')
    await waitFor(() => expect(screen.getByText(/已导入 5 点/)).toBeInTheDocument())
  })

  it('批量启用：POST /api/points/batch 请求体正确', async () => {
    const posts: Array<{ path: string; body: Record<string, unknown> }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        if (url.startsWith('/api/points/batch')) {
          posts.push({ path: url, body: JSON.parse(String(init?.body ?? '{}')) })
          return jsonResponse({ ok: true, changed: 3 })
        }
        return jsonResponse({ ok: true })
      }),
    )
    setup()

    fireEvent.click(screen.getByRole('button', { name: /批量/ }))
    const ioaInput = await screen.findByPlaceholderText(/IOA 逗号分隔/)
    fireEvent.change(ioaInput, { target: { value: '1, 2, 3' } })
    // antd 两字按钮自动插空格（「启 用」）
    fireEvent.click(screen.getByRole('button', { name: /启\s*用/ }))

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toEqual({ type: 'YX', ioas: [1, 2, 3], action: 'enable', group: null })
  })

  it('批量改组：action=group 且带 group 字段', async () => {
    const posts: Array<{ path: string; body: Record<string, unknown> }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        if (url.startsWith('/api/points/batch')) {
          posts.push({ path: url, body: JSON.parse(String(init?.body ?? '{}')) })
          return jsonResponse({ ok: true, changed: 2 })
        }
        return jsonResponse({ ok: true })
      }),
    )
    setup()
    fireEvent.click(screen.getByRole('button', { name: /批量/ }))
    const ioaInput = await screen.findByPlaceholderText(/IOA 逗号分隔/)
    fireEvent.change(ioaInput, { target: { value: '7,8' } })
    fireEvent.click(screen.getByRole('button', { name: /改\s*组/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toEqual({ type: 'YX', ioas: [7, 8], action: 'group', group: 1 })
  })

  it('批量 IOA 留空且缓存为空 → 不发请求', async () => {
    const post = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        if (String(input).startsWith('/api/points/batch')) return post()
        return jsonResponse({ ok: true })
      }),
    )
    setup()
    fireEvent.click(screen.getByRole('button', { name: /批量/ }))
    fireEvent.click(await screen.findByRole('button', { name: /启\s*用/ }))
    // 守卫拦截：等待一段确认窗口，POST 不得发出
    // （antd message 提示依赖 raf，jsdom 下不落 DOM，故只断言网络不变量）
    await new Promise((r) => setTimeout(r, 800))
    expect(post).not.toHaveBeenCalled()
  })

  it('导出菜单：点击「导出 YAML」开新窗指向 /api/points/yaml', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    setup()
    const btn = screen.getByRole('button', { name: /导出/ })
    // antd Dropdown 在 jsdom 下需要完整触发序列
    fireEvent.mouseEnter(btn)
    fireEvent.mouseDown(btn)
    fireEvent.click(btn)
    const yaml = await screen.findByText('导出 YAML', {}, { timeout: 5000 })
    fireEvent.click(yaml)
    expect(openSpy).toHaveBeenCalledWith('/api/points/yaml', '_blank')
  })
})
