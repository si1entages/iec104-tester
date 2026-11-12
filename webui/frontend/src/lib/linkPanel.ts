/** 链路参数面板的共享展示逻辑（WP6）——Carbon / PF 两套件复用。 */

import type { MessageKey } from '../i18n'
import type { LinkSnapshot, LinkTimerInfo, Status } from '../api/types'

export type LinkTone = 'green' | 'blue' | 'orange' | 'red' | 'gray'

/** 状态 → 语义色（Running 绿 / Connecting 蓝 / Stopped 灰 / 未知红） */
export function stateTone(state: string | undefined): LinkTone {
  if (state === 'Running') return 'green'
  if (state === 'Connecting') return 'blue'
  if (state === 'Stopped') return 'gray'
  return 'red'
}

export interface LinkCard {
  /** 指标名（i18n key） */
  label: MessageKey
  /** 展示值（已格式化） */
  value: string
  /** 是否告警态（t1 逼近超时 / 窗口将满 / 有未确认帧且已重连） */
  warn?: boolean
}

/** 定时器剩余秒数 → 展示串；未激活显示「—」（"没在计时"） */
export function timerText(t: LinkTimerInfo | undefined): string {
  if (!t || !t.active) return '—'
  return `${t.remaining.toFixed(1)} / ${t.timeout.toFixed(1)} s`
}

/**
 * 汇总面板要显示的指标。
 *
 * 设计取舍：**未确认 I 帧数与 t1 剩余并排**——t1 超时的直接前因就是
 * "有 I 帧发出去但没人确认"，现场排查时这两个数必须一起看，
 * 分开放在两个卡片里反而要来回对照。
 */
export function linkCards(status: Status | undefined, t: (k: MessageKey) => string): LinkCard[] {
  const link: LinkSnapshot | undefined = status?.link
  const st = link?.state
  const seq = link?.sequence
  const tp = link?.transport
  if (!link) return []
  const t1 = st?.timers?.t1
  const cards: LinkCard[] = []

  cards.push({
    label: 'link.state',
    value: st ? t(`link.state.${st.state}` as MessageKey) : '—',
  })
  cards.push({ label: 'link.since', value: st ? `${st.since_seconds.toFixed(0)} s` : '—' })

  if (seq) {
    cards.push({
      label: 'link.unacked',
      value: `${seq.unacked} / ${seq.k}`,
      warn: seq.unacked > 0 && !seq.window_available,
    })
    cards.push({
      label: 'link.window',
      value: `${seq.send_seq} / ${seq.recv_seq}`,
    })
  }

  if (t1) {
    cards.push({
      label: 'link.t1Remaining',
      value: timerText(t1),
      warn: Boolean(t1.active && t1.remaining <= Math.max(1, t1.timeout * 0.2)),
    })
  }

  if (tp) {
    cards.push({
      label: 'link.target',
      value: tp.target || '—',
      warn: false,
    })
    cards.push({
      label: 'link.reconnects',
      value: tp.max_reconnects > 0
        ? `${tp.reconnect_count} / ${tp.max_reconnects}`
        : String(tp.reconnect_count),
      warn: tp.reconnect_count > 0,
    })
  }
  // WP11a：冗余双通道切换可观测（数据来自 /api/status 的 link.redundancy）
  const red = link.redundancy
  if (red && red.enabled) {
    cards.push({
      label: 'link.redundancyActive',
      value: red.active ? t(`link.redundancy.${red.active}` as MessageKey) : '—',
      warn: red.active === 'standby',
    })
    cards.push({
      label: 'link.redundancyFailovers',
      value: String(red.failovers),
      warn: red.failovers > 0,
    })
    cards.push({
      label: 'link.redundancyLinks',
      value: `${red.primary_connected ? '✓' : '✗'} / ${red.standby_connected ? '✓' : '✗'}`,
      warn: !red.primary_connected || !red.standby_connected,
    })
  }

  return cards
}

/** 定时器表（t0~t3 全部列出，未激活显示「—」） */
export function timerRows(t: (k: MessageKey) => string) {
  return (['t0', 't1', 't2', 't3'] as const).map((name) => ({
    name,
    label: t(`link.timer.${name}` as MessageKey),
    text: (timer: LinkTimerInfo | undefined) => timerText(timer),
  }))
}

/** 重连原因展示：无错误时给「—」，避免空字符串显得像渲染失败 */
export function lastErrorText(status: Status | undefined): string {
  const tp = status?.link?.transport
  if (!tp) return '—'
  if (!tp.last_error) return '—'
  return tp.last_error
}

/** 最近一次错误时间（本地时间串） */
export function lastErrorWhen(status: Status | undefined): string {
  const ts = status?.link?.transport?.last_error_at
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString()
}

/** 状态变迁时间线（旧→新，取最后 8 条够用且不撑高页面） */
export function timeline(
  status: Status | undefined,
  t: (k: MessageKey) => string,
): { ts: string; text: string }[] {
  const hist = status?.link?.state?.history ?? []
  return hist.slice(-8).map((h) => ({
    ts: new Date(h.ts * 1000).toLocaleTimeString(),
    text: `${t(`link.state.${h.from}` as MessageKey)} → ${t(`link.state.${h.to}` as MessageKey)}`,
  }))
}