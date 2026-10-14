import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import { api } from './endpoints'

// jsdom 环境下 import.meta.url 不是 file: 协议，故以 vitest 的 cwd（= vite root，
// 即 webui/frontend）为基准定位契约文档与源码。
const DOC_PATH = resolve(process.cwd(), '../api_contract.md')
const SRC_PATH = resolve(process.cwd(), 'src/api/endpoints.ts')

const DOC_ROW = /^\|\s*(GET|POST)\s*\|\s*`(\/api\/[^`\s]+)`\s*\|/gm

function documentedEndpoints(): string[] {
  const text = readFileSync(DOC_PATH, 'utf-8')
  return [...text.matchAll(DOC_ROW)].map((m) => m[2])
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

describe('REST 端点覆盖（与 api_contract.md 对齐）', () => {
  it('文档中的每个端点都在 endpoints.ts 中有对应调用', () => {
    const source = readFileSync(SRC_PATH, 'utf-8')
    const missing = documentedEndpoints().filter((path) => !source.includes(path))
    expect(missing, `未实现：${missing.join(', ')}`).toEqual([])
  })

  it('端点数量符合契约规模（35 REST + /api/schema）', () => {
    expect(documentedEndpoints().length).toBeGreaterThanOrEqual(35)
  })

  it('api 对象暴露全部端点分组', () => {
    for (const fn of [api.schema, api.status, api.points, api.recent, api.logs]) {
      expect(typeof fn).toBe('function')
    }
    for (const name of [
      'start', 'stop', 'gi', 'clock', 'ci', 'reset', 'test', 'read',
      'yk', 'setpoint', 'step', 'bitstring', 'delay', 'param', 'file',
    ] as const) {
      expect(typeof api.master[name]).toBe('function')
    }
    for (const name of [
      'start', 'stop', 'yx', 'yc', 'ym', 'ep', 'ps', 'response', 'sim',
    ] as const) {
      expect(typeof api.slave[name]).toBe('function')
    }
    for (const fn of [
      api.batchPoints, api.pointsYaml, api.importPointsYaml,
      api.importPoints, api.exportPointsCsv, api.exportSession,
    ]) {
      expect(typeof fn).toBe('function')
    }
  })
})

describe('端点请求构造', () => {
  it('日志查询拼接 query 并跳过空值', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true, logs: [] }))
    vi.stubGlobal('fetch', fetchMock)
    try {
      await api.logs({ level_min: 'INFO', q: 'sbo', limit: 50, category: undefined })
      expect(fetchMock).toHaveBeenCalledTimes(1)
      const [url] = fetchMock.mock.calls[0] as unknown as [string]
      expect(url).toBe('/api/logs?level_min=INFO&q=sbo&limit=50')
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('YK 命令以 JSON POST 下发', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    try {
      await api.master.yk({ ioa: 2001, state: 1, select: true })
      const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
      expect(url).toBe('/api/master/yk')
      expect(init.method).toBe('POST')
      expect(JSON.parse(String(init.body))).toEqual({ ioa: 2001, state: 1, select: true })
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('无参命令仍发送空 JSON 体', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    try {
      await api.master.stop()
      const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
      expect(url).toBe('/api/master/stop')
      expect(String(init.body)).toBe('{}')
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('点表导入按格式拼 query', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    try {
      await api.importPoints('ioa,type\n1,M_SP_NA_1\n', 'csv')
      const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
      expect(url).toBe('/api/points/import?format=csv')
      expect(init.body).toBe('ioa,type\n1,M_SP_NA_1\n')
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
