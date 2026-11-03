import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Point } from '../../api/types'
import { PointCommandDialog } from './PointCommandDialog'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

interface Post {
  path: string
  body: Record<string, unknown>
}

function capturePosts(): Post[] {
  const posts: Post[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posts.push({
          path: String(input),
          body: JSON.parse(String(init.body ?? '{}')) as Record<string, unknown>,
        })
      }
      return jsonResponse({ ok: true })
    }),
  )
  return posts
}

function setup(point: Point | null) {
  const onClose = vi.fn()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <PointCommandDialog point={point} onClose={onClose} />
      </AntdApp>
    </QueryClientProvider>,
  )
  return onClose
}

const confirmButton = (): HTMLElement =>
  screen.getByRole('button', { name: /确\s*认\s*下\s*发/ })

describe('PointCommandDialog（双击值直接发命令确认）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('YK 单命令 SBO 点位：展示 SBO 说明，确认后只发执行帧（选择由后端自动完成）', async () => {
    const posts = capturePosts()
    const onClose = setup({
      ioa: 201,
      type: 'YK',
      name: 'YK_SBO_TRUE',
      enabled: true,
      value: '—',
      subtype: 'single',
      sbo: true,
    })

    expect(screen.getByText(/SBO 选择-执行/)).toBeInTheDocument()
    expect(screen.getByText(/主站自动先发送选择帧/)).toBeInTheDocument()
    fireEvent.click(confirmButton())

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].path).toBe('/api/master/yk')
    expect(posts[0].body).toMatchObject({ ioa: 201, state: 1, select: false, double: false })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('YK 双命令：state 使用 2=合/1=分，请求带 double=true', async () => {
    const posts = capturePosts()
    setup({
      ioa: 202,
      type: 'YK',
      name: 'YK_DOUBLE',
      enabled: true,
      value: '—',
      subtype: 'double',
      sbo: false,
    })

    fireEvent.click(screen.getByRole('radio', { name: '分闸 OFF' }))
    fireEvent.click(confirmButton())

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toMatchObject({ ioa: 202, state: 1, select: false, double: true })
  })

  it('YC 设点：按点位 subtype 选择设点类型，确认后带目标值下发', async () => {
    const posts = capturePosts()
    setup({
      ioa: 101,
      type: 'YC',
      name: 'YC_101',
      enabled: true,
      value: 12.5,
      subtype: 'normalized',
    })

    const input = screen.getByRole('spinbutton')
    fireEvent.change(input, { target: { value: '7.5' } })
    fireEvent.click(confirmButton())

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].path).toBe('/api/master/setpoint')
    expect(posts[0].body).toMatchObject({
      ioa: 101,
      value: 7.5,
      kind: 'normalized',
      select: false,
    })
  })

  it('STEP 升降：确认后 state=2（升一步）', async () => {
    const posts = capturePosts()
    setup({
      ioa: 401,
      type: 'STEP',
      name: 'STEP_401',
      enabled: true,
      value: 0,
    })

    fireEvent.click(confirmButton())

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].path).toBe('/api/master/step')
    expect(posts[0].body).toMatchObject({ ioa: 401, state: 2, select: false })
  })
})
