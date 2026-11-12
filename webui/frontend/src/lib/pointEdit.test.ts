import { describe, expect, it } from 'vitest'

import type { Point } from '../api/types'
import {
  draftFromPoint, draftToPayload, validateDraft,
} from './pointEdit'

const yk: Point = {
  ioa: 2001, type: 'YK', name: '合闸', group: 3, enabled: true,
  sbo: true, subtype: 'double',
}

describe('点表在线编辑草稿（WP10a）', () => {
  it('从现有点生成草稿', () => {
    const d = draftFromPoint(yk)
    expect(d.ioa).toBe('2001')
    expect(d.name).toBe('合闸')
    expect(d.group).toBe('3')
    expect(d.type).toBe('YK')
    expect(d.sbo).toBe(true)
  })

  it('新增时用默认值', () => {
    const d = draftFromPoint(null)
    expect(d.ioa).toBe('')
    expect(d.type).toBe('YX')
    expect(d.group).toBe('1')
    expect(d.enabled).toBe(true)
  })

  it('未知类型回落 YX，不产生非法请求', () => {
    const d = draftFromPoint({ ...yk, type: 'ZZ' })
    expect(d.type).toBe('YX')
  })

  it('按类型只带该类型的字段（YK 带 sbo，不带量程/单位）', () => {
    const p = draftToPayload({ ...draftFromPoint(yk), min_value: '5' })
    expect(p.sbo).toBe(true)
    expect(p.min_value).toBeUndefined()
    expect(p.unit).toBeUndefined()
  })

  it('YC 带量程/单位/小数位', () => {
    const d = draftFromPoint(null)
    d.type = 'YC'
    d.unit = 'kV'
    d.min_value = '-5'
    d.max_value = '5'
    d.decimal_places = '2'
    const p = draftToPayload(d)
    expect(p.unit).toBe('kV')
    expect(p.min_value).toBe(-5)
    expect(p.max_value).toBe(5)
    expect(p.decimal_places).toBe(2)
  })

  it('STEP 带量程但不带单位', () => {
    const d = draftFromPoint(null)
    d.type = 'STEP'
    d.min_value = '-64'
    d.max_value = '63'
    const p = draftToPayload(d)
    expect(p.min_value).toBe(-64)
    expect(p.unit).toBeUndefined()
  })

  it('校验：非法 IOA / 组号 / 数值', () => {
    const d = draftFromPoint(null)
    expect(validateDraft({ ...d, ioa: '1' })).toBe('')
    expect(validateDraft({ ...d, ioa: '-1' })).toBe('ioa')
    expect(validateDraft({ ...d, ioa: 'abc' })).toBe('ioa')
    expect(validateDraft({ ...d, ioa: '1', group: 'x' })).toBe('group')
    expect(validateDraft({ ...d, ioa: '1', min_value: 'x' })).toBe('min')
    expect(validateDraft({ ...d, ioa: '1', max_value: 'x' })).toBe('max')
    expect(validateDraft({ ...d, ioa: '1', decimal_places: 'x' })).toBe('decimals')
  })

  it('空数值字段不算错误（可选字段）', () => {
    const d = draftFromPoint(null)
    expect(validateDraft({ ...d, ioa: '7', min_value: '', max_value: '', decimal_places: '' }))
      .toBe('')
  })
})
