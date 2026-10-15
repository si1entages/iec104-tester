/**
 * 趋势采样环形缓冲（T12）。
 *
 * 这不是服务端状态也不是 UI 状态，而是**本地派生遥测**，因此独立于 React Query
 * 与 Zustand，用模块级单例 + 订阅实现，避免把高频采样塞进 React 状态导致重渲染风暴。
 *
 * 关键约束：**只采样被订阅的点位**。十万点表若全量采样会瞬间打满内存，
 * 因此 `record()` 对未被 watch 的 key 直接丢弃。
 */

export interface TrendSample {
  ts: number
  value: number
}

const MAX_SAMPLES = 600
/** 通知节流：最多 2Hz 触发一次重渲染 */
const NOTIFY_INTERVAL_MS = 500

export function toNumericValue(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (value === 'ON' || value === true) return 1
  if (value === 'OFF' || value === false) return 0
  return null
}

class TrendBuffer {
  private series = new Map<string, TrendSample[]>()
  private watched = new Set<string>()
  private listeners = new Set<() => void>()
  private dirty = false
  private timer: ReturnType<typeof setTimeout> | null = null

  setWatched(keys: string[]): void {
    const next = new Set(keys)
    for (const key of this.series.keys()) {
      if (!next.has(key)) this.series.delete(key)
    }
    this.watched = next
    this.notify()
  }

  isWatched(key: string): boolean {
    return this.watched.has(key)
  }

  record(key: string, ts: number, value: unknown): void {
    if (!this.watched.has(key)) return
    const numeric = toNumericValue(value)
    if (numeric === null) return
    const list = this.series.get(key) ?? []
    list.push({ ts, value: numeric })
    if (list.length > MAX_SAMPLES) list.splice(0, list.length - MAX_SAMPLES)
    this.series.set(key, list)
    this.markDirty()
  }

  get(key: string): TrendSample[] {
    return this.series.get(key) ?? []
  }

  clear(): void {
    this.series.clear()
    this.notify()
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  private markDirty(): void {
    this.dirty = true
    if (this.timer) return
    this.timer = setTimeout(() => {
      this.timer = null
      if (!this.dirty) return
      this.notify()
    }, NOTIFY_INTERVAL_MS)
  }

  private notify(): void {
    this.dirty = false
    for (const listener of this.listeners) listener()
  }
}

export const trendBuffer = new TrendBuffer()
