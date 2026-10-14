import { describe, expect, it } from 'vitest'

import { buildUrl } from './client'

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
