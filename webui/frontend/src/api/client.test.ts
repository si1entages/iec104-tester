import { afterEach, describe, expect, it, vi } from 'vitest'

import { TOKEN_KEY, apiGet, buildUrl } from './client'

describe('buildUrl', () => {
  it('无参数时返回原路径', () => {
    expect(buildUrl('/api/status')).toBe('/api/status')
  })

  it('自动补前导斜杠', () => {
    expect(buildUrl('api/points')).toBe('/api/points')
  })

  it('跳过空值（undefined / null / 空串）', () => {
    expect(
      buildUrl('/api/logs', { level_min: 'INFO', category: undefined, q: '', source: null }),
    ).toBe('/api/logs?level_min=INFO')
  })

  it('按 URLSearchParams 规则编码', () => {
    expect(buildUrl('/api/logs', { q: 'a b', limit: 200 })).toBe('/api/logs?q=a+b&limit=200')
  })
})

describe('访问令牌（B7）', () => {
  afterEach(() => {
    localStorage.removeItem(TOKEN_KEY)
    vi.unstubAllGlobals()
  })

  it('localStorage 有令牌时自动附加 Authorization 头', async () => {
    localStorage.setItem(TOKEN_KEY, 'tok-1')
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ ok: true }),
    }))
    vi.stubGlobal('fetch', fetchMock)

    await apiGet('/api/status')
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer tok-1')
  })

  it('无令牌时不附加 Authorization 头', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ ok: true }),
    }))
    vi.stubGlobal('fetch', fetchMock)

    await apiGet('/api/status')
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
  })
})
