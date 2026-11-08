import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiContractError } from './contract'
import {
  TOKEN_KEY,
  apiGet,
  apiUrl,
  buildUrl,
  setActiveRole,
  setSlaveApiPrefix,
} from './client'
import { api } from './endpoints'
import { okSchema } from './contracts'

describe('buildUrl', () => {
  afterEach(() => {
    setActiveRole('master')
    setSlaveApiPrefix(null)
  })

  it('无参数时返回原路径', () => {
    expect(buildUrl('/api/status')).toBe('/api/status')
  })

  it('合并模式子站使用 /slave 前缀', () => {
    setActiveRole('slave')
    setSlaveApiPrefix('/slave')
    expect(buildUrl('/api/status')).toBe('/slave/api/status')
    expect(buildUrl('/api/logs', { limit: 10 })).toBe('/slave/api/logs?limit=10')
    expect(apiUrl('/api/logs/export')).toBe('/slave/api/logs/export')
  })

  it('单角色模式子站不加前缀', () => {
    setActiveRole('slave')
    setSlaveApiPrefix(null)
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

    await apiGet('/api/status', okSchema)
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

    await apiGet('/api/status', okSchema)
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('响应不符合 schema → 抛 ApiContractError（不静默返回 undefined）', async () => {
    // 旧缺陷的错误假设：嵌套 translation，缺少契约要求的 format/segments
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        text: async () => JSON.stringify({ ok: true, translation: { format: 'I', segments: [] } }),
      })),
    )

    try {
      await api.framesDecode('680401000000')
      expect.unreachable('应抛 ApiContractError')
    } catch (e) {
      expect(e).toBeInstanceOf(ApiContractError)
      expect((e as ApiContractError).path).toBe('/api/frames/decode.format')
      expect((e as ApiContractError).message).toContain('接口响应不符合契约')
    }
  })
})
