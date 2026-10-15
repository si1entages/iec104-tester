import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { toNumericValue, trendBuffer } from './trendBuffer'

describe('trendBuffer（趋势采样环形缓冲）', () => {
  beforeEach(() => {
    trendBuffer.clear()
    trendBuffer.setWatched([])
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('只采样被 watch 的点位；未 watch 的 record 直接丢弃', () => {
    trendBuffer.setWatched(['YC-1008'])
    trendBuffer.record('YC-1008', 1, 12.5)
    trendBuffer.record('YC-9999', 1, 7)
    expect(trendBuffer.get('YC-1008')).toEqual([{ ts: 1, value: 12.5 }])
    expect(trendBuffer.get('YC-9999')).toEqual([])
  })

  it('setWatched 收窄后清理不再 watch 的历史序列', () => {
    trendBuffer.setWatched(['YC-1', 'YC-2'])
    trendBuffer.record('YC-1', 1, 1)
    trendBuffer.record('YC-2', 1, 2)
    trendBuffer.setWatched(['YC-2'])
    expect(trendBuffer.get('YC-1')).toEqual([])
    expect(trendBuffer.get('YC-2')).toHaveLength(1)
  })

  it('数值化：ON/OFF → 1/0，非数值 → null（不采样）', () => {
    expect(toNumericValue(3.14)).toBe(3.14)
    expect(toNumericValue('ON')).toBe(1)
    expect(toNumericValue('OFF')).toBe(0)
    expect(toNumericValue(true)).toBe(1)
    expect(toNumericValue('BAD')).toBeNull()
  })

  it('record 触发节流通知（≤2Hz），clear 立即通知', () => {
    vi.useFakeTimers()
    trendBuffer.setWatched(['YC-1'])
    const listener = vi.fn()
    trendBuffer.subscribe(listener)

    trendBuffer.record('YC-1', 1, 1)
    trendBuffer.record('YC-1', 2, 2)
    expect(listener).not.toHaveBeenCalled() // 节流窗口内不通知
    vi.advanceTimersByTime(500)
    expect(listener).toHaveBeenCalledTimes(1)

    trendBuffer.clear()
    expect(listener).toHaveBeenCalledTimes(2)
  })

  it('采样超过上限 600 时丢弃最旧样本', () => {
    trendBuffer.setWatched(['YC-1'])
    for (let i = 0; i < 610; i += 1) trendBuffer.record('YC-1', i, i)
    const samples = trendBuffer.get('YC-1')
    expect(samples).toHaveLength(600)
    expect(samples[0].ts).toBe(10)
    expect(samples[599].ts).toBe(609)
  })
})
