/** 报文值域解码树的展示逻辑（WP7）——Carbon / PF 两套件复用。 */

import type { FrameObject, FrameTree, QualityBits } from '../api/types'

/** 品质位 → 紧凑标签（IV/NT/SB/BL/OV；无位时 GOOD） */
export function qualityFlags(bits: QualityBits | null | undefined): string {
  if (!bits) return ''
  const on: string[] = []
  if (bits.iv) on.push('IV')
  if (bits.nt) on.push('NT')
  if (bits.sb) on.push('SB')
  if (bits.bl) on.push('BL')
  if (bits.ov) on.push('OV')
  return on.length ? on.join('|') : 'GOOD'
}

/** 品质是否异常（决定子表是否标红） */
export function qualityBad(bits: QualityBits | null | undefined): boolean {
  if (!bits) return false
  return bits.iv || bits.nt || bits.sb || bits.bl || bits.ov
}

/** 值 → 展示串（布尔转 ON/OFF 与点表口径一致） */
export function objectValue(o: FrameObject): string {
  if (o.value_display) return o.value_display
  if (typeof o.value === 'boolean') return o.value ? 'ON' : 'OFF'
  if (o.value === null || o.value === undefined) return '—'
  return String(o.value)
}

/**
 * 子表是否值得展开。
 *
 * 取舍：**只有 ≥1 个信息对象的 I 帧才展开**——S/U 帧没有信息体，
 * 展开只会得到一张空表，反而让用户以为解析失败。
 */
export function expandable(tree: FrameTree | null | undefined): boolean {
  if (!tree || !tree.ok) return false
  return tree.format === 'I' && tree.objects.length > 0
}

/** 子表标题所需的原始字段（文案由组件经 i18n 拼装，本模块不出中文） */
export function treeSummaryParts(tree: FrameTree | null | undefined): {
  typeName: string
  count: number
  sq: boolean
  commonAddr: number
} | null {
  if (!tree || !tree.asdu) return null
  const a = tree.asdu
  return { typeName: a.type_name, count: a.object_count, sq: a.sq, commonAddr: a.common_addr }
}
