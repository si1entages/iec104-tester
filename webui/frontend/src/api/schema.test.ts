import { describe, expect, it } from 'vitest'

import { describeSchemaMismatch, isSchemaMismatch, SCHEMA_VERSION } from './schema'

describe('schema 版本协商', () => {
  it('同版本不算不匹配', () => {
    expect(isSchemaMismatch(SCHEMA_VERSION)).toBe(false)
    expect(describeSchemaMismatch(SCHEMA_VERSION)).toBeNull()
  })

  it('不同版本判为不匹配并给出可读说明', () => {
    expect(isSchemaMismatch(SCHEMA_VERSION + 1)).toBe(true)
    const msg = describeSchemaMismatch(SCHEMA_VERSION + 1)
    expect(msg).toContain('契约版本不匹配')
    expect(msg).toContain(`前端期望 ${SCHEMA_VERSION}`)
  })

  it('缺失或非法版本视为未知，不告警也不崩', () => {
    for (const value of [undefined, null, 'v1', Number.NaN, {}, []]) {
      expect(isSchemaMismatch(value)).toBe(false)
      expect(describeSchemaMismatch(value)).toBeNull()
    }
  })
})
