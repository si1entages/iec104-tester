import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Role } from '../api/types'
import { AppLayout } from './AppLayout'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function setup(role: Role | null): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown) => {
      if (String(input).startsWith('/api/status')) {
        return jsonResponse(role ? { role, running: false, schemaVersion: 1 } : {})
      }
      return jsonResponse({ ok: true })
    }),
  )
  render(
    <QueryClientProvider client={client}>
      <AppLayout>
        <div>content</div>
      </AppLayout>
    </QueryClientProvider>,
  )
}

describe('AppLayout（导航按角色过滤）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('主站会话：隐藏「子站工作台」，保留主站/多站/状态/日志', async () => {
    setup('master')
    // 角色就绪后被过滤的菜单项消失（初始未过滤，需等状态加载）
    await waitFor(() =>
      expect(screen.queryByRole('menuitem', { name: /子站工作台/ })).toBeNull(),
    )
    expect(screen.getByRole('menuitem', { name: /主站工作台/ })).toBeInTheDocument()
    for (const name of [/多站/, /状态总览/, /日志/]) {
      expect(screen.getByRole('menuitem', { name })).toBeInTheDocument()
    }
  })

  it('子站会话：隐藏「主站工作台」，保留子站/多站/状态/日志', async () => {
    setup('slave')
    await waitFor(() =>
      expect(screen.queryByRole('menuitem', { name: /主站工作台/ })).toBeNull(),
    )
    expect(screen.getByRole('menuitem', { name: /子站工作台/ })).toBeInTheDocument()
    for (const name of [/多站/, /状态总览/, /日志/]) {
      expect(screen.getByRole('menuitem', { name })).toBeInTheDocument()
    }
  })
})
