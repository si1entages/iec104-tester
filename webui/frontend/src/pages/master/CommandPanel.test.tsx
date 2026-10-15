import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CommandPanel } from './CommandPanel'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

describe('CommandPanel（命令面板）YK 撤销选择', () => {
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
          <CommandPanel point={null} />
        </AntdApp>
      </QueryClientProvider>,
    )
  }

  function ykPosts(posts: Array<Record<string, unknown>>): void {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        if (String(input).startsWith('/api/master/yk')) {
          posts.push(JSON.parse(String(init?.body ?? '{}')))
          return jsonResponse({ ok: true })
        }
        return jsonResponse({ ok: true })
      }),
    )
  }

  async function fillIoa(value: string): Promise<void> {
    const ioaInput = screen
      .getAllByRole('spinbutton')
      .find((el) => el.closest('.ant-input-number-affix-wrapper')?.textContent?.includes('IOA'))
    expect(ioaInput).toBeTruthy()
    fireEvent.change(ioaInput!, { target: { value } })
  }

  it('选择成功后解锁「撤销选择」，撤销请求携带 deactivate=true 并复位按钮', async () => {
    const posts: Array<Record<string, unknown>> = []
    ykPosts(posts)
    setup()
    await fillIoa('100')

    const undoBtn = screen.getByRole('button', { name: /撤\s*销\s*选\s*择/ })
    expect(undoBtn).toBeDisabled() // 未选择前不可撤销

    // 选择（SBO）→ 请求 select=true，无 deactivate
    fireEvent.click(screen.getByRole('button', { name: /选\s*择\s*\(SBO\)/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toMatchObject({ ioa: 100, select: true })
    expect(posts[0].deactivate).toBeFalsy()

    // 选择成功 → 撤销可用
    await waitFor(() => expect(undoBtn).not.toBeDisabled())

    // 撤销 → select 与选择帧一致 + deactivate=true
    fireEvent.click(undoBtn)
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1]).toMatchObject({ ioa: 100, select: true, deactivate: true })

    // 撤销成功 → 按钮复位禁用
    await waitFor(() => expect(undoBtn).toBeDisabled())
  })

  it('执行成功后「已选择未执行」状态清除，撤销按钮禁用', async () => {
    const posts: Array<Record<string, unknown>> = []
    ykPosts(posts)
    setup()
    await fillIoa('7')

    fireEvent.click(screen.getByRole('button', { name: /选\s*择\s*\(SBO\)/ }))
    const undoBtn = screen.getByRole('button', { name: /撤\s*销\s*选\s*择/ })
    await waitFor(() => expect(undoBtn).not.toBeDisabled())

    fireEvent.click(screen.getByRole('button', { name: /^执\s*行$/ }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1]).toMatchObject({ ioa: 7, select: false })

    await waitFor(() => expect(undoBtn).toBeDisabled())
  })
})
