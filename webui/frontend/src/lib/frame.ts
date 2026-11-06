/**
 * IEC 60870-5-104 报文解析（T12 报文查看器）。
 *
 * 只做**只读解析**：APCI（启动/长度/控制域）+ ASDU 头部 + 首个信息对象地址。
 * 不依赖后端 `core/`，类型名/COT 名在此独立登记（与 core/protocol/types.py 对齐）。
 *
 * i18n：协议类型/传送原因的标准名称用本地 zh/en 对照表（避免污染主词典）；
 * 说明性文案（长度不符、组召唤模板）走 i18n 词典的 `frame.*` 键。
 */

import { tNow } from '../i18n'
import type { Locale } from '../i18n'
import { useUiStore } from '../store/uiStore'

export type FrameFormat = 'I' | 'S' | 'U' | '?'

export interface ParsedFrame {
  format: FrameFormat
  /** I 帧发送序号 N(S) */
  ns?: number
  /** I 帧/S 帧接收序号 N(R) */
  nr?: number
  /** U 帧功能名（STARTDT act 等） */
  uFunc?: string
  /** ASDU 类型标识 */
  typeId?: number
  typeName?: string
  /** 传送原因 */
  cot?: number
  cotName?: string
  /** 信息对象个数（VSQ 低 7 位） */
  count?: number
  /** 是否连续（SQ=1） */
  sq?: boolean
  commonAddr?: number
  originAddr?: number
  /** 首个信息对象地址 */
  firstIoa?: number
  /** 解析备注（截断 / 长度不符等） */
  note?: string
}

type L10n = Record<Locale, string>

function loc(value: L10n): string {
  return value[useUiStore.getState().locale] ?? value.zh
}

const TYPE_NAMES: Record<number, L10n> = {
  1: { zh: 'M_SP_NA_1 单点信息', en: 'M_SP_NA_1 Single-point information' },
  2: { zh: 'M_SP_TA_1 带时标单点', en: 'M_SP_TA_1 Single-point information with time tag' },
  3: { zh: 'M_DP_NA_1 双点信息', en: 'M_DP_NA_1 Double-point information' },
  4: { zh: 'M_DP_TA_1 带时标双点', en: 'M_DP_TA_1 Double-point information with time tag' },
  5: { zh: 'M_ST_NA_1 步位置', en: 'M_ST_NA_1 Step position information' },
  6: { zh: 'M_ST_TA_1 带时标步位置', en: 'M_ST_TA_1 Step position information with time tag' },
  7: { zh: 'M_BO_NA_1 32比特串', en: 'M_BO_NA_1 Bitstring of 32 bit' },
  8: { zh: 'M_BO_TA_1 带时标32比特串', en: 'M_BO_TA_1 Bitstring of 32 bit with time tag' },
  9: { zh: 'M_ME_NA_1 归一化测量值', en: 'M_ME_NA_1 Measured value, normalized value' },
  10: {
    zh: 'M_ME_TA_1 带时标归一化测量值',
    en: 'M_ME_TA_1 Measured value, normalized value with time tag',
  },
  11: { zh: 'M_ME_NB_1 标度化测量值', en: 'M_ME_NB_1 Measured value, scaled value' },
  12: {
    zh: 'M_ME_TB_1 带时标标度化测量值',
    en: 'M_ME_TB_1 Measured value, scaled value with time tag',
  },
  13: { zh: 'M_ME_NC_1 短浮点测量值', en: 'M_ME_NC_1 Measured value, short floating point' },
  14: {
    zh: 'M_ME_TC_1 带时标短浮点测量值',
    en: 'M_ME_TC_1 Measured value, short floating point with time tag',
  },
  15: { zh: 'M_IT_NA_1 累计量', en: 'M_IT_NA_1 Integrated totals' },
  16: { zh: 'M_IT_TA_1 带时标累计量', en: 'M_IT_TA_1 Integrated totals with time tag' },
  17: { zh: 'M_EP_TA_1 继保事件', en: 'M_EP_TA_1 Event of protection equipment with time tag' },
  18: {
    zh: 'M_EP_TB_1 继保成组启动事件',
    en: 'M_EP_TB_1 Packed start events of protection equipment with time tag',
  },
  19: {
    zh: 'M_EP_TC_1 继保成组输出电路信息',
    en: 'M_EP_TC_1 Packed output circuit information of protection equipment with time tag',
  },
  20: {
    zh: 'M_PS_NA_1 成组单点(带状态检出)',
    en: 'M_PS_NA_1 Packed single-point information with status change detection',
  },
  21: {
    zh: 'M_ME_ND_1 归一化测量值(无品质)',
    en: 'M_ME_ND_1 Measured value, normalized value without quality descriptor',
  },
  30: { zh: 'M_SP_TB_1 单点信息(CP56)', en: 'M_SP_TB_1 Single-point information with CP56Time2a' },
  31: { zh: 'M_DP_TB_1 双点信息(CP56)', en: 'M_DP_TB_1 Double-point information with CP56Time2a' },
  32: { zh: 'M_ST_TB_1 步位置(CP56)', en: 'M_ST_TB_1 Step position information with CP56Time2a' },
  33: { zh: 'M_BO_TB_1 32比特串(CP56)', en: 'M_BO_TB_1 Bitstring of 32 bit with CP56Time2a' },
  34: {
    zh: 'M_ME_TD_1 归一化测量值(CP56)',
    en: 'M_ME_TD_1 Measured value, normalized value with CP56Time2a',
  },
  35: {
    zh: 'M_ME_TE_1 标度化测量值(CP56)',
    en: 'M_ME_TE_1 Measured value, scaled value with CP56Time2a',
  },
  36: {
    zh: 'M_ME_TF_1 短浮点测量值(CP56)',
    en: 'M_ME_TF_1 Measured value, short floating point with CP56Time2a',
  },
  37: { zh: 'M_IT_TB_1 累计量(CP56)', en: 'M_IT_TB_1 Integrated totals with CP56Time2a' },
  38: {
    zh: 'M_EP_TD_1 继保事件(CP56)',
    en: 'M_EP_TD_1 Event of protection equipment with CP56Time2a',
  },
  39: {
    zh: 'M_EP_TE_1 继保成组启动事件(CP56)',
    en: 'M_EP_TE_1 Packed start events of protection equipment with CP56Time2a',
  },
  40: {
    zh: 'M_EP_TF_1 继保成组输出电路信息(CP56)',
    en: 'M_EP_TF_1 Packed output circuit information of protection equipment with CP56Time2a',
  },
  45: { zh: 'C_SC_NA_1 单命令', en: 'C_SC_NA_1 Single command' },
  46: { zh: 'C_DC_NA_1 双命令', en: 'C_DC_NA_1 Double command' },
  47: { zh: 'C_RC_NA_1 升降命令', en: 'C_RC_NA_1 Regulating step command' },
  48: { zh: 'C_SE_NA_1 设点(归一化)', en: 'C_SE_NA_1 Set-point command, normalized value' },
  49: { zh: 'C_SE_NB_1 设点(标度化)', en: 'C_SE_NB_1 Set-point command, scaled value' },
  50: {
    zh: 'C_SE_NC_1 设点(短浮点)',
    en: 'C_SE_NC_1 Set-point command, short floating point',
  },
  51: { zh: 'C_BO_NA_1 32比特串命令', en: 'C_BO_NA_1 Bitstring of 32 bit command' },
  58: { zh: 'C_SC_TA_1 单命令(CP56)', en: 'C_SC_TA_1 Single command with CP56Time2a' },
  59: { zh: 'C_DC_TA_1 双命令(CP56)', en: 'C_DC_TA_1 Double command with CP56Time2a' },
  60: { zh: 'C_RC_TA_1 升降命令(CP56)', en: 'C_RC_TA_1 Regulating step command with CP56Time2a' },
  61: {
    zh: 'C_SE_TA_1 设点(归一化,CP56)',
    en: 'C_SE_TA_1 Set-point command, normalized value with CP56Time2a',
  },
  62: {
    zh: 'C_SE_TB_1 设点(标度化,CP56)',
    en: 'C_SE_TB_1 Set-point command, scaled value with CP56Time2a',
  },
  63: {
    zh: 'C_SE_TC_1 设点(短浮点,CP56)',
    en: 'C_SE_TC_1 Set-point command, short floating point with CP56Time2a',
  },
  64: { zh: 'C_BO_TA_1 32比特串命令(CP56)', en: 'C_BO_TA_1 Bitstring of 32 bit command with CP56Time2a' },
  70: { zh: 'M_EI_NA_1 初始化结束', en: 'M_EI_NA_1 End of initialization' },
  71: {
    zh: 'M_PS_TB_1 成组单点(CP56)',
    en: 'M_PS_TB_1 Packed single-point information with status change detection (CP56Time2a)',
  },
  100: { zh: 'C_IC_NA_1 总召唤', en: 'C_IC_NA_1 Interrogation command' },
  101: { zh: 'C_CI_NA_1 累计量召唤', en: 'C_CI_NA_1 Counter interrogation command' },
  102: { zh: 'C_RD_NA_1 读命令', en: 'C_RD_NA_1 Read command' },
  103: { zh: 'C_CS_NA_1 时钟同步', en: 'C_CS_NA_1 Clock synchronization command' },
  104: { zh: 'C_TS_NA_1 测试命令', en: 'C_TS_NA_1 Test command' },
  105: { zh: 'C_RP_NA_1 复位进程', en: 'C_RP_NA_1 Reset process command' },
  106: { zh: 'C_CD_NA_1 延时获得', en: 'C_CD_NA_1 Delay acquisition command' },
  107: { zh: 'C_TS_TA_1 测试命令(CP56)', en: 'C_TS_TA_1 Test command with CP56Time2a' },
  110: { zh: 'P_ME_NA_1 参数(归一化)', en: 'P_ME_NA_1 Parameter, normalized value' },
  111: { zh: 'P_ME_NB_1 参数(标度化)', en: 'P_ME_NB_1 Parameter, scaled value' },
  112: { zh: 'P_ME_NC_1 参数(短浮点)', en: 'P_ME_NC_1 Parameter, short floating point' },
  113: { zh: 'P_AC_NA_1 参数激活', en: 'P_AC_NA_1 Parameter activation' },
  120: { zh: 'F_FR_NA_1 文件准备就绪', en: 'F_FR_NA_1 File ready' },
  121: { zh: 'F_SR_NA_1 节准备就绪', en: 'F_SR_NA_1 Section ready' },
  122: {
    zh: 'F_SC_NA_1 召唤目录/选择文件/召唤文件',
    en: 'F_SC_NA_1 Call directory / select file / call file',
  },
  123: { zh: 'F_LS_NA_1 最后的节/段', en: 'F_LS_NA_1 Last section or segment' },
  124: { zh: 'F_AF_NA_1 确认文件/节', en: 'F_AF_NA_1 ACK file or section' },
  125: { zh: 'F_SG_NA_1 段', en: 'F_SG_NA_1 Segment' },
  126: { zh: 'F_DR_TA_1 目录', en: 'F_DR_TA_1 Directory' },
}

const COT_NAMES: Record<number, L10n> = {
  0: { zh: '未用', en: 'Not used' },
  1: { zh: '周期', en: 'Periodic/cyclic' },
  2: { zh: '背景扫描', en: 'Background scan' },
  3: { zh: '突发', en: 'Spontaneous' },
  4: { zh: '初始化', en: 'Initialized' },
  5: { zh: '被请求', en: 'Requested' },
  6: { zh: '激活', en: 'Activation' },
  7: { zh: '激活确认', en: 'Activation confirmation' },
  8: { zh: '停止激活', en: 'Deactivation' },
  9: { zh: '停止激活确认', en: 'Deactivation confirmation' },
  10: { zh: '激活终止', en: 'Activation termination' },
  11: { zh: '远方命令返送', en: 'Return info caused by remote command' },
  12: { zh: '当地命令返送', en: 'Return info caused by local command' },
  13: { zh: '文件传输', en: 'File transfer' },
  20: { zh: '响应站召唤', en: 'Interrogated by station interrogation' },
  37: { zh: '响应累计量总召唤', en: 'Requested by general counter request' },
  42: { zh: '未知类型标识', en: 'Unknown type identification' },
  43: { zh: '未知传送原因', en: 'Unknown cause of transmission' },
  44: { zh: '未知公共地址', en: 'Unknown common address' },
  45: { zh: '未知信息对象地址', en: 'Unknown information object address' },
}

const U_FUNCS: Record<number, string> = {
  0x07: 'STARTDT act',
  0x0b: 'STARTDT con',
  0x13: 'STOPDT act',
  0x23: 'STOPDT con',
  0x43: 'TESTFR act',
  0x83: 'TESTFR con',
}

export function typeName(typeId: number): string {
  const name = TYPE_NAMES[typeId]
  return name ? loc(name) : `TypeID ${typeId}`
}

export function cotName(cot: number): string {
  const known = COT_NAMES[cot]
  if (known) return loc(known)
  if (cot >= 21 && cot <= 36) return tNow('frame.cot.group', { n: cot - 20 })
  if (cot >= 38 && cot <= 41) return tNow('frame.cot.counterGroup', { n: cot - 37 })
  return `COT ${cot}`
}

/** 解析一帧的十六进制串（"" 或非法输入返回 null）。 */
export function parseFrame(hex: string): ParsedFrame | null {
  if (!hex || hex.length < 8 || hex.length % 2 !== 0) return null
  const bytes = new Uint8Array(hex.length / 2)
  for (let i = 0; i < bytes.length; i += 1) {
    const b = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16)
    if (Number.isNaN(b)) return null
    bytes[i] = b
  }
  if (bytes.length < 6) return null

  const parsed: ParsedFrame = { format: '?' }
  const declared = bytes[1]
  if (declared + 2 !== bytes.length) {
    parsed.note = tNow('frame.note.lengthMismatch', {
      declared: declared + 2,
      actual: bytes.length,
    })
  }

  const b0 = bytes[2]
  if ((b0 & 0x03) === 0x03) {
    parsed.format = 'U'
    parsed.uFunc = U_FUNCS[b0] ?? `U 0x${b0.toString(16).padStart(2, '0')}`
    return parsed
  }
  if ((b0 & 0x03) === 0x01) {
    parsed.format = 'S'
    parsed.nr = ((bytes[4] >> 1) | (bytes[5] << 7)) & 0xffff
    return parsed
  }

  parsed.format = 'I'
  parsed.ns = ((bytes[2] >> 1) | (bytes[3] << 7)) & 0xffff
  parsed.nr = ((bytes[4] >> 1) | (bytes[5] << 7)) & 0xffff

  if (bytes.length < 10) {
    parsed.note = tNow('frame.note.noAsdu')
    return parsed
  }
  parsed.typeId = bytes[6]
  parsed.typeName = typeName(parsed.typeId)
  parsed.sq = (bytes[7] & 0x80) !== 0
  parsed.count = bytes[7] & 0x7f
  parsed.cot = bytes[8] & 0x3f
  parsed.cotName = cotName(parsed.cot)
  parsed.originAddr = bytes[9]
  if (bytes.length >= 12) parsed.commonAddr = bytes[10] | (bytes[11] << 8)
  if (bytes.length >= 15) {
    parsed.firstIoa = bytes[12] | (bytes[13] << 8) | (bytes[14] << 16)
  }
  return parsed
}

export const FORMAT_COLOR: Record<FrameFormat, string> = {
  I: 'blue',
  S: 'cyan',
  U: 'purple',
  '?': 'default',
}

export const DIRECTION_COLOR: Record<string, string> = {
  tx: 'green',
  rx: 'gold',
}

const DIRECTION_LABELS: Record<string, L10n> = {
  tx: { zh: '发送', en: 'Send' },
  rx: { zh: '接收', en: 'Receive' },
}

/** 方向显示名（随界面语言）；未知方向原样返回 */
export function directionLabel(direction: string): string {
  const label = DIRECTION_LABELS[direction]
  return label ? loc(label) : direction
}
