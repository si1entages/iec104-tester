import { describe, expect, it } from 'vitest'

import type { FrameObject, FrameTree } from '../api/types'
import {
  expandable, objectValue, qualityBad, qualityFlags, treeSummaryParts,
} from './frameTree'

function obj(over: Partial<FrameObject> = {}): FrameObject {
  return {
    index: 1, ioa: 1000, value_display: 'ON', value: true,
    quality: 'GOOD', quality_bits: { iv: false, nt: false, sb: false, bl: false, ov: false },
    quality_raw: 0, timestamp: null, raw_hex: '01', ...over,
  }
}

function tree(over: Partial<FrameTree> = {}): FrameTree {
  return {
    ok: true, format: 'I',
    apci: {
      length: 20, asdu_length: 14, frame_type: 'I',
      tx_seq: 3, rx_seq: 1, u_func: null, u_func_name: null,
    },
    asdu: {
      type_id: 1, type_name: 'M_SP_NA_1(1)', sq: true, num: 2, cot: 3,
      cot_name: '突发', pn: false, test: false, origin_addr: 0,
      common_addr: 1, object_count: 2,
    },
    objects: [obj({ index: 1, ioa: 1000 }), obj({ index: 2, ioa: 1001, sq_index: 1 })],
    ...over,
  }
}

describe('报文值域解码树展示逻辑（WP7）', () => {
  it('品质位标签：无位显示 GOOD，多位按严重度排列', () => {
    expect(qualityFlags({ iv: false, nt: false, sb: false, bl: false, ov: false })).toBe('GOOD')
    expect(qualityFlags({ iv: true, nt: false, sb: false, bl: false, ov: false })).toBe('IV')
    expect(qualityFlags({ iv: true, nt: true, sb: false, bl: true, ov: false }))
      .toBe('IV|NT|BL')
    expect(qualityFlags(null)).toBe('')
  })

  it('品质异常判定：任一位置即异常', () => {
    expect(qualityBad({ iv: false, nt: false, sb: false, bl: false, ov: false })).toBe(false)
    expect(qualityBad({ iv: false, nt: false, sb: false, bl: false, ov: true })).toBe(true)
    expect(qualityBad(null)).toBe(false)
  })

  it('值展示：优先 value_display，布尔回落 ON/OFF（与点表口径一致）', () => {
    expect(objectValue(obj({ value_display: 'QOI=20（站召唤）' }))).toBe('QOI=20（站召唤）')
    expect(objectValue(obj({ value_display: '', value: true }))).toBe('ON')
    expect(objectValue(obj({ value_display: '', value: false }))).toBe('OFF')
    expect(objectValue(obj({ value_display: '', value: null }))).toBe('—')
    expect(objectValue(obj({ value_display: '', value: 3.5 }))).toBe('3.5')
  })

  it('只有含信息对象的 I 帧可展开（S/U 帧不给空表）', () => {
    expect(expandable(tree())).toBe(true)
    expect(expandable(tree({ objects: [] }))).toBe(false)
    expect(expandable(tree({ format: 'S' }))).toBe(false)
    expect(expandable(tree({ format: 'U' }))).toBe(false)
    expect(expandable(tree({ ok: false }))).toBe(false)
    expect(expandable(null)).toBe(false)
    expect(expandable(undefined)).toBe(false)
  })

  it('子表标题字段：类型/对象数/SQ/公共地址', () => {
    expect(treeSummaryParts(tree())).toEqual({
      typeName: 'M_SP_NA_1(1)', count: 2, sq: true, commonAddr: 1,
    })
    expect(treeSummaryParts(tree({ asdu: null }))).toBeNull()
    expect(treeSummaryParts(null)).toBeNull()
  })
})
