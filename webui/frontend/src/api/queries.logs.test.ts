import { describe, expect, it } from 'vitest'

import { QueryClient } from '@tanstack/react-query'

import {
  MAX_LIVE_LOGS,
  appendLiveLog,
  appendLiveLogs,
  clearLiveLogs,
  queryKeys,
  replaceLiveLogs,
} from './queries'
import type { LogRow } from './types'

function row(i: number): LogRow {
  return { ts: 1730000000 + i, level: 'INFO', source: 'test', category: 'system', message: `m${i}` }
}

describe('实时日志缓存写入（批量合并）', () => {
  it('appendLiveLogs 整批一次写入，保持顺序', () => {
    const client = new QueryClient()
    appendLiveLogs(client, [row(1), row(2), row(3)])
    appendLiveLogs(client, [row(4)])
    const data = client.getQueryData<LogRow[]>(queryKeys.liveLogs())
    expect(data?.map((r) => r.message)).toEqual(['m1', 'm2', 'm3', 'm4'])
  })

  it('空批次不触发缓存写入（引用不变，不引发渲染）', () => {
    const client = new QueryClient()
    appendLiveLogs(client, [row(1)])
    const before = client.getQueryData<LogRow[]>(queryKeys.liveLogs())
    appendLiveLogs(client, [])
    expect(client.getQueryData<LogRow[]>(queryKeys.liveLogs())).toBe(before)
  })

  it('超过 MAX_LIVE_LOGS 时裁掉最旧（不静默增长）', () => {
    const client = new QueryClient()
    const many = Array.from({ length: MAX_LIVE_LOGS + 50 }, (_, i) => row(i))
    appendLiveLogs(client, many)
    const data = client.getQueryData<LogRow[]>(queryKeys.liveLogs())
    expect(data).toHaveLength(MAX_LIVE_LOGS)
    expect(data?.[0].message).toBe(`m${50}`)
    expect(data?.[MAX_LIVE_LOGS - 1].message).toBe(`m${MAX_LIVE_LOGS + 49}`)
  })

  it('appendLiveLog 单条是批量的特例', () => {
    const client = new QueryClient()
    appendLiveLog(client, row(1))
    expect(client.getQueryData<LogRow[]>(queryKeys.liveLogs())).toHaveLength(1)
  })

  it('replaceLiveLogs 覆盖并截断；clearLiveLogs 清空视图缓冲', () => {
    const client = new QueryClient()
    replaceLiveLogs(client, [row(1), row(2)])
    expect(client.getQueryData<LogRow[]>(queryKeys.liveLogs())).toHaveLength(2)
    clearLiveLogs(client)
    expect(client.getQueryData<LogRow[]>(queryKeys.liveLogs())).toEqual([])
  })
})
