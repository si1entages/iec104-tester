import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TestCenterPage } from './TestCenterPage'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

const SCRIPTS = {
  ok: true,
  scripts: [
    { id: 'basic_connection_gi.yaml', name: 'basic_connection_gi', description: '连接 + 总召', role: 'master', steps: 4 },
    { id: 'slave_basic.yaml', name: 'slave_basic', description: '子站基础', role: 'slave', steps: 2 },
  ],
}

const STATUS = {
  ok: true,
  running: false,
  run: {
    id: 'run-1',
    status: 'passed',
    scripts: ['basic_connection_gi.yaml'],
    started_at: 1,
    ended_at: 2,
    returncode: 0,
    summary: { scripts: 1, passed: 1, failed: 0 },
    lines: ['▶ Running: basic_connection_gi', '✅ basic_connection_gi (0.10s)'],
    results: [{ script: 'basic_connection_gi.yaml', returncode: 0 }],
    reports: [{ name: 'basic_connection_gi.html', format: 'html', size: 100 }],
  },
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <TestCenterPage />
      </AntdApp>
    </QueryClientProvider>,
  )
}

describe('TestCenterPage（自动化测试中心）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('展示脚本/上次运行日志与报告', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/api/tests/scripts')) return jsonResponse(SCRIPTS)
        return jsonResponse(STATUS)
      }),
    )
    setup()

    expect(await screen.findByText('自动化测试中心')).toBeTruthy()
    expect(await screen.findByText('basic_connection_gi')).toBeTruthy()
    expect(await screen.findByText(/✅ basic_connection_gi/)).toBeTruthy()
    expect(await screen.findByText('basic_connection_gi.html')).toBeTruthy()
    expect(screen.getByText('共 1，通过 1，失败 0')).toBeTruthy()
  })

  it('勾选脚本后运行，POST 请求体包含脚本 id', async () => {
    const posts: Array<{ path: string; body: Record<string, unknown> }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          posts.push({
            path: new URL(url, 'http://x').pathname,
            body: JSON.parse(String(init.body ?? '{}')),
          })
          return jsonResponse({ ok: true })
        }
        if (url.includes('/api/tests/scripts')) return jsonResponse(SCRIPTS)
        return jsonResponse({ ok: true, running: false, run: null })
      }),
    )
    setup()

    await screen.findByText('basic_connection_gi', {}, { timeout: 10_000 })
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1), { timeout: 10_000 })
    fireEvent.click(screen.getAllByRole('checkbox')[1])
    fireEvent.click(screen.getByRole('button', { name: /运行选中/ }))
    await waitFor(() => expect(posts.length).toBe(1))
    expect(posts[0].path).toBe('/api/tests/run')
    expect(posts[0].body.scripts).toEqual(['basic_connection_gi.yaml'])
  })
})
