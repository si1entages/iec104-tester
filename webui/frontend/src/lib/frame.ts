/**
 * IEC 60870-5-104 报文解析（T12 报文查看器）。
 *
 * 只做**只读解析**：APCI（启动/长度/控制域）+ ASDU 头部 + 首个信息对象地址。
 * 不依赖后端 `core/`，类型名/COT 名在此独立登记（与 core/protocol/types.py 对齐）。
 */

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

const TYPE_NAMES: Record<number, string> = {
  1: 'M_SP_NA_1 单点信息',
  2: 'M_SP_TA_1 带时标单点',
  3: 'M_DP_NA_1 双点信息',
  4: 'M_DP_TA_1 带时标双点',
  5: 'M_ST_NA_1 步位置',
  6: 'M_ST_TA_1 带时标步位置',
  7: 'M_BO_NA_1 32比特串',
  8: 'M_BO_TA_1 带时标32比特串',
  9: 'M_ME_NA_1 归一化测量值',
  10: 'M_ME_TA_1 带时标归一化测量值',
  11: 'M_ME_NB_1 标度化测量值',
  12: 'M_ME_TB_1 带时标标度化测量值',
  13: 'M_ME_NC_1 短浮点测量值',
  14: 'M_ME_TC_1 带时标短浮点测量值',
  15: 'M_IT_NA_1 累计量',
  16: 'M_IT_TA_1 带时标累计量',
  17: 'M_EP_TA_1 继保事件',
  18: 'M_EP_TB_1 继保成组启动事件',
  19: 'M_EP_TC_1 继保成组输出电路信息',
  20: 'M_PS_NA_1 成组单点(带状态检出)',
  21: 'M_ME_ND_1 归一化测量值(无品质)',
  30: 'M_SP_TB_1 单点信息(CP56)',
  31: 'M_DP_TB_1 双点信息(CP56)',
  32: 'M_ST_TB_1 步位置(CP56)',
  33: 'M_BO_TB_1 32比特串(CP56)',
  34: 'M_ME_TD_1 归一化测量值(CP56)',
  35: 'M_ME_TE_1 标度化测量值(CP56)',
  36: 'M_ME_TF_1 短浮点测量值(CP56)',
  37: 'M_IT_TB_1 累计量(CP56)',
  38: 'M_EP_TD_1 继保事件(CP56)',
  39: 'M_EP_TE_1 继保成组启动事件(CP56)',
  40: 'M_EP_TF_1 继保成组输出电路信息(CP56)',
  45: 'C_SC_NA_1 单命令',
  46: 'C_DC_NA_1 双命令',
  47: 'C_RC_NA_1 升降命令',
  48: 'C_SE_NA_1 设点(归一化)',
  49: 'C_SE_NB_1 设点(标度化)',
  50: 'C_SE_NC_1 设点(短浮点)',
  51: 'C_BO_NA_1 32比特串命令',
  58: 'C_SC_TA_1 单命令(CP56)',
  59: 'C_DC_TA_1 双命令(CP56)',
  60: 'C_RC_TA_1 升降命令(CP56)',
  61: 'C_SE_TA_1 设点(归一化,CP56)',
  62: 'C_SE_TB_1 设点(标度化,CP56)',
  63: 'C_SE_TC_1 设点(短浮点,CP56)',
  64: 'C_BO_TA_1 32比特串命令(CP56)',
  70: 'M_EI_NA_1 初始化结束',
  71: 'M_PS_TB_1 成组单点(CP56)',
  100: 'C_IC_NA_1 总召唤',
  101: 'C_CI_NA_1 累计量召唤',
  102: 'C_RD_NA_1 读命令',
  103: 'C_CS_NA_1 时钟同步',
  104: 'C_TS_NA_1 测试命令',
  105: 'C_RP_NA_1 复位进程',
  106: 'C_CD_NA_1 延时获得',
  107: 'C_TS_TA_1 测试命令(CP56)',
  110: 'P_ME_NA_1 参数(归一化)',
  111: 'P_ME_NB_1 参数(标度化)',
  112: 'P_ME_NC_1 参数(短浮点)',
  113: 'P_AC_NA_1 参数激活',
  120: 'F_FR_NA_1 文件准备就绪',
  121: 'F_SR_NA_1 节准备就绪',
  122: 'F_SC_NA_1 召唤目录/选择文件/召唤文件',
  123: 'F_LS_NA_1 最后的节/段',
  124: 'F_AF_NA_1 确认文件/节',
  125: 'F_SG_NA_1 段',
  126: 'F_DR_TA_1 目录',
}

const COT_NAMES: Record<number, string> = {
  0: '未用',
  1: '周期',
  2: '背景扫描',
  3: '突发',
  4: '初始化',
  5: '被请求',
  6: '激活',
  7: '激活确认',
  8: '停止激活',
  9: '停止激活确认',
  10: '激活终止',
  11: '远方命令返送',
  12: '当地命令返送',
  13: '文件传输',
  20: '响应站召唤',
  37: '响应累计量总召唤',
  42: '未知类型标识',
  43: '未知传送原因',
  44: '未知公共地址',
  45: '未知信息对象地址',
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
  return TYPE_NAMES[typeId] ?? `TypeID ${typeId}`
}

export function cotName(cot: number): string {
  if (COT_NAMES[cot]) return COT_NAMES[cot]
  if (cot >= 21 && cot <= 36) return `响应第 ${cot - 20} 组召唤`
  if (cot >= 38 && cot <= 41) return `响应第 ${cot - 37} 组累计量召唤`
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
    parsed.note = `长度字段 ${declared + 2} ≠ 实际 ${bytes.length}`
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
    parsed.note = 'I 帧无 ASDU'
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

export const DIRECTION_LABEL: Record<string, string> = {
  tx: '发送',
  rx: '接收',
}
