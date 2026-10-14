import { describe, expect, it } from 'vitest'

import {
  isLogRow,
  isLogsResponse,
  isPointsResponse,
  isRecord,
  isStatus,
  isWsMessage,
  readSchemaVersion,
} from './validate'

describe('运行时校验：宽进严出、绝不抛异常', () => {
  it('isRecord 排除数组与 null', () => {
    expect(isRecord({})).toBe(true)
    expect(isRecord([])).toBe(false)
    expect(isRecord(null)).toBe(false)
    expect(isRecord('x')).toBe(false)
  })

  it('isStatus 只要求 role 合法', () => {
    expect(isStatus({ role: 'master' })).toBe(true)
    expect(isStatus({ role: 'slave', running: false })).toBe(true)
    expect(isStatus({ role: 'other' })).toBe(false)
    expect(isStatus({ running: false })).toBe(false)
    expect(isStatus(null)).toBe(false)
  })

  it('isPointsResponse 逐点校验', () => {
    expect(isPointsResponse({ points: [] })).toBe(true)
    expect(isPointsResponse({ points: [{ ioa: 1, type: 'M_SP_NA_1' }] })).toBe(true)
    expect(isPointsResponse({ points: [{ type: 'M_SP_NA_1' }] })).toBe(false)
    expect(isPointsResponse({ points: 'nope' })).toBe(false)
    expect(isPointsResponse(undefined)).toBe(false)
  })

  it('isLogsResponse 容忍非日志噪声', () => {
    expect(isLogsResponse({ ok: true, logs: [] })).toBe(true)
    const bad = { logs: [{ ts: 'x', level: 'INFO', message: 'm' }] }
    expect(isLogsResponse(bad)).toBe(false)
  })

  it('isLogRow 要求 ts/level/message', () => {
    expect(isLogRow({ ts: 1, level: 'INFO', message: 'hi' })).toBe(true)
    expect(isLogRow({ ts: 1, level: 'INFO' })).toBe(false)
  })

  it('isWsMessage 只要求 kind + data', () => {
    expect(isWsMessage({ kind: 'log', data: { ts: 1 } })).toBe(true)
    expect(isWsMessage({ kind: 'snapshot', schemaVersion: 1, data: {} })).toBe(true)
    expect(isWsMessage({ data: {} })).toBe(false)
    expect(isWsMessage('nope')).toBe(false)
  })

  it('readSchemaVersion 安全取值', () => {
    expect(readSchemaVersion({ schemaVersion: 2 })).toBe(2)
    expect(readSchemaVersion({ schemaVersion: '2' })).toBeUndefined()
    expect(readSchemaVersion(null)).toBeUndefined()
  })
})
