import { describe, expect, it } from 'vitest'

import type { LinkSnapshot, Status } from '../api/types'
import { DICTIONARIES } from '../i18n'
import type { MessageKey } from '../i18n'

const zh = DICTIONARIES.zh
import {
  lastErrorText,
  lastErrorWhen,
  linkCards,
  stateTone,
  timeline,
  timerRows,
  timerText,
} from './linkPanel'

const t = (k: MessageKey): string => zh[k] ?? String(k)

function st(over: Partial<LinkSnapshot> = {}): Status {
  const base: LinkSnapshot = {
    role: 'master',
    state: {
      state: 'Running',
      since_seconds: 12.4,
      timers: {
        t0: { timeout: 30, active: false, elapsed: 0, remaining: 0 },
        t1: { timeout: 15, active: true, elapsed: 3.2, remaining: 11.8 },
        t2: { timeout: 10, active: false, elapsed: 0, remaining: 0 },
        t3: { timeout: 20, active: true, elapsed: 2.0, remaining: 18.0 },
      },
      history: [
        { ts: 1000, from: 'Stopped', to: 'Connecting' },
        { ts: 1001, from: 'Connecting', to: 'Running' },
      ],
    },
    sequence: {
      k: 12, w: 8, send_seq: 5, recv_seq: 3, last_ack_rx: 2,
      unacked: 3, window_available: true, i_frame_count: 1,
    },
    transport: {
      target: '10.0.0.1:2404', connected: true, tls: false,
      reconnect_count: 2, max_reconnects: 0, reconnect_interval: 5,
      reconnect_in_seconds: null, ever_connected: true,
      last_error: '', last_error_at: 0,
    },
  }
  return { role: 'master', link: { ...base, ...over } }
}

describe('链路面板展示逻辑（WP6）', () => {
  it('状态语义色：Running 绿 / Connecting 蓝 / Stopped 灰 / 未知红', () => {
    expect(stateTone('Running')).toBe('green')
    expect(stateTone('Connecting')).toBe('blue')
    expect(stateTone('Stopped')).toBe('gray')
    expect(stateTone(undefined)).toBe('red')
    expect(stateTone('Weird')).toBe('red')
  })

  it('定时器未激活显示「—」而不是 0 秒', () => {
    expect(timerText(undefined)).toBe('—')
    expect(timerText({ timeout: 15, active: false, elapsed: 0, remaining: 0 })).toBe('—')
    expect(timerText({ timeout: 15, active: true, elapsed: 3.2, remaining: 11.8 }))
      .toBe('11.8 / 15.0 s')
  })

  it('指标卡同时含未确认 I 帧与 t1 剩余（t1 超时的两个前因并排）', () => {
    const cards = linkCards(st(), t)
    const labels = cards.map((c) => c.label)
    expect(labels).toContain('link.unacked')
    expect(labels).toContain('link.t1Remaining')
    expect(cards.find((c) => c.label === 'link.unacked')?.value).toBe('3 / 12')
    expect(cards.find((c) => c.label === 'link.t1Remaining')?.value).toBe('11.8 / 15.0 s')
  })

  it('满窗告警：未确认达到 k 时 unacked 卡转为告警态', () => {
    const s = st()
    s.link!.sequence = { ...s.link!.sequence!, unacked: 12, window_available: false }
    const card = linkCards(s, t).find((c) => c.label === 'link.unacked')
    expect(card?.warn).toBe(true)
  })

  it('t1 逼近超时（≤20%）转告警', () => {
    const s = st()
    s.link!.state!.timers.t1 = { timeout: 15, active: true, elapsed: 14, remaining: 1.0 }
    const card = linkCards(s, t).find((c) => c.label === 'link.t1Remaining')
    expect(card?.warn).toBe(true)
  })

  it('重连计数有值时转告警；上限为 0（无限）时只显示次数', () => {
    const s = st()
    s.link!.transport = { ...s.link!.transport!, reconnect_count: 7 }
    const card = linkCards(s, t).find((c) => c.label === 'link.reconnects')
    expect(card?.value).toBe('7')
    expect(card?.warn).toBe(true)

    s.link!.transport = { ...s.link!.transport!, max_reconnects: 10 }
    expect(linkCards(s, t).find((c) => c.label === 'link.reconnects')?.value).toBe('7 / 10')
  })

  it('无引擎（state/sequence 为 null）仍给出目标与重连信息', () => {
    const s: Status = {
      role: 'master',
      link: {
        role: 'master', state: null, sequence: null,
        transport: {
          target: '127.0.0.1:2404', connected: false, tls: false,
          reconnect_count: 0, max_reconnects: 0, reconnect_interval: 5,
          reconnect_in_seconds: null, ever_connected: false,
          last_error: '', last_error_at: 0,
        },
      },
    }
    const cards = linkCards(s, t)
    expect(cards.map((c) => c.label)).toEqual([
      'link.state', 'link.since', 'link.target', 'link.reconnects',
    ])
    expect(cards[0].value).toBe('—')
    expect(cards[2].value).toBe('127.0.0.1:2404')
  })

  it('完全没有 link 段（bridge 角色/旧后端）返回空数组，不抛错', () => {
    expect(linkCards(undefined, t)).toEqual([])
    expect(linkCards({ role: 'bridge' }, t)).toEqual([])
  })

  it('重连原因与时刻', () => {
    expect(lastErrorText(undefined)).toBe('—')
    expect(lastErrorText(st())).toBe('—')
    const s = st()
    s.link!.transport = {
      ...s.link!.transport!, last_error: 'ConnectionRefusedError: refused',
      last_error_at: 1794450000,
    }
    expect(lastErrorText(s)).toBe('ConnectionRefusedError: refused')
    expect(lastErrorWhen(s)).not.toBe('—')
    expect(lastErrorWhen(st())).toBe('—')
  })

  it('时间线取最后 8 条并翻译状态名', () => {
    const s = st()
    s.link!.state!.history = Array.from({ length: 12 }, (_, i) => ({
      ts: 1000 + i, from: 'Connecting', to: 'Running',
    }))
    const rows = timeline(s, t)
    expect(rows).toHaveLength(8)
    expect(rows[0].text).toBe('连接中 → 运行中')
    expect(rows[0].ts).toBeTruthy()
    expect(timeline(undefined, t)).toEqual([])
  })

  it('定时器行覆盖 t0~t3 且都能渲染未激活态', () => {
    const rows = timerRows(t)
    expect(rows.map((r) => r.name)).toEqual(['t0', 't1', 't2', 't3'])
    expect(rows[0].text(undefined)).toBe('—')
    expect(rows[1].text({ timeout: 15, active: true, elapsed: 1, remaining: 14 }))
      .toBe('14.0 / 15.0 s')
  })

  it('状态名 i18n 键齐全（三态都有译文，不缺键）', () => {
    for (const st of ['Stopped', 'Connecting', 'Running'] as const) {
      const key = `link.state.${st}` as MessageKey
      expect(zh[key]).toBeTruthy()
      expect(zh[key]).not.toBe(key)
    }
  })

  it('冗余双通道启用时显示活动通道/切换次数/主备连接', () => {
    const s = st()
    s.link!.redundancy = {
      enabled: true, active: 'standby', primary_connected: false,
      standby_connected: true, standby_host: '10.0.0.2', standby_port: 2404,
      switch_timeout: 2, dedup_window: 5, failovers: 3,
    }
    const cards = linkCards(s, t)
    const labels = cards.map((c) => c.label)
    expect(labels).toContain('link.redundancyActive')
    expect(labels).toContain('link.redundancyFailovers')
    expect(labels).toContain('link.redundancyLinks')
    const active = cards.find((c) => c.label === 'link.redundancyActive')
    expect(active?.value).toBe('备用')
    expect(active?.warn).toBe(true)
    expect(cards.find((c) => c.label === 'link.redundancyFailovers')?.value).toBe('3')
  })

  it('冗余未启用时不产生冗余卡片', () => {
    const s = st()
    s.link!.redundancy = null
    const labels = linkCards(s, t).map((c) => c.label)
    expect(labels.some((l) => String(l).startsWith('link.redundancy'))).toBe(false)
  })
})
