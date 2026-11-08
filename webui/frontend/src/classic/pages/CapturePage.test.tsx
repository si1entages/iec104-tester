import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CapturePage } from './CapturePage'

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

const IDLE = {
  ok: true,
  recording: false,
  paused: false,
  frames: 0,
  rx: 0,
  tx: 0,
  dropped: 0,
  elapsed: 0,
  file: null,
  files: [{ name: 'master_20260101-000000.i104', size: 1024, mtime: 1767225600 }],
  playback: { loaded: false },
}

const LOADED = {
  ...IDLE,
  playback: {
    loaded: true,
    file: 'master_20260101-000000.i104',
    state: 'stopped',
    index: 0,
    total: 2,
    progress: 0,
    duration: 1.5,
    current: {
      timestamp: 0,
      absolute_time: 1,
      direction: 'RX',
      frame_type: 'I',
      length: 6,
      hex: '680401000000',
      metadata: {},
    },
  },
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <CapturePage />
      </AntdApp>
    </QueryClientProvider>,
  )
}

describe('CapturePage（报文录制/回放）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('渲染录制状态与文件表，开始录制点击发 POST', async () => {
    const posts: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'POST') {
          posts.push(new URL(url, 'http://x').pathname)
          return jsonResponse({ ok: true })
        }
        return jsonResponse(IDLE)
      }),
    )
    setup()

    expect(await screen.findByText('报文录制与回放')).toBeTruthy()
    expect(await screen.findByText('master_20260101-000000.i104')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '开始录制' }))
    await waitFor(() => expect(posts).toContain('/api/capture/start'))
  })

  it('已加载回放时渲染帧表与播放控件', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/api/capture/frames')) {
          return jsonResponse({
            ok: true,
            total: 1,
            offset: 0,
            rows: [
              {
                timestamp: 0,
                absolute_time: 1,
                direction: 'RX',
                frame_type: 'I',
                length: 6,
                hex: '680401000000',
                metadata: {},
              },
            ],
          })
        }
        return jsonResponse(LOADED)
      }),
    )
    setup()

    expect((await screen.findAllByText('master_20260101-000000.i104')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('680401000000')).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /播\s*放/ })).toBeTruthy()
    expect(screen.getByText('0/2')).toBeTruthy()
  })
})
