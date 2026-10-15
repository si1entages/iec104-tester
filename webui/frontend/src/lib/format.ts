/** 通用格式化工具（T12） */

/** `HH:mm:ss.SSS` —— 报文/日志密集场景用，节省列宽 */
export function formatClock(ts: number): string {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const p = (n: number, w = 2): string => String(n).padStart(w, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`
}

/** `YYYY/MM/DD HH:mm:ss` */
export function formatDateTime(ts: number): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3)
  return String(value)
}

/** HEX 字串按空格分组（每字节一组），便于阅读 */
export function groupHex(hex: string): string {
  return hex.replace(/(..)/g, '$1 ').trim().toUpperCase()
}
