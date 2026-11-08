/** 通用格式化工具（T12） */

/** `HH:mm:ss.SSS` —— 报文/日志密集场景用，节省列宽 */
export function formatClock(ts: number): string {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const p = (n: number, w = 2): string => String(n).padStart(w, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`
}

/** UI 语言 → `toLocaleString` 区域标签（日期格式跟随界面语言，不硬编码 zh-CN） */
export function localeTag(locale: string): string {
  return locale === 'en' ? 'en-GB' : 'zh-CN'
}

/** `YYYY/MM/DD HH:mm:ss`（跟随界面语言） */
export function formatDateTime(ts: number, locale = 'zh-CN'): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString(locale, { hour12: false })
}

/** `YYYY/MM/DD`（跟随界面语言） */
export function formatDate(ts: number, locale = 'zh-CN'): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleDateString(locale)
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3)
  return String(value)
}

/**
 * 测量值格式化（设计规范 §5.3）：
 * 优先用点位声明的 `decimal_places`；缺省按量级选择，避免一律 `toFixed(3)`。
 */
export function formatMeasurement(value: unknown, decimalPlaces?: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return formatValue(value)
  const dp =
    typeof decimalPlaces === 'number' && decimalPlaces >= 0
      ? Math.min(decimalPlaces, 6)
      : Math.abs(value) >= 1000
        ? 1
        : Math.abs(value) >= 10
          ? 2
          : 3
  return value.toFixed(dp)
}

/** HEX 字串按空格分组（每字节一组），便于阅读 */
export function groupHex(hex: string): string {
  return hex.replace(/(..)/g, '$1 ').trim().toUpperCase()
}
