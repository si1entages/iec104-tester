import { Tag } from '@carbon/react'

import type { Status } from '../../api/types'
import { useT } from '../../i18n'
import {
  lastErrorText, lastErrorWhen, linkCards, stateTone, timeline, timerRows,
} from '../../lib/linkPanel'
import { KvList, Note, Panel, Stat } from '../components/ui'

const TAG_TYPE = {
  green: 'green', blue: 'blue', orange: 'magenta', red: 'red', gray: 'cool-gray',
} as const

/** 链路参数可观测面板（WP6）：k/w/t0~t3、未确认 I 帧、重连原因、状态时间线。 */
export function CarbonLinkStatsCard({ status }: { status: Status | undefined }) {
  const t = useT()
  const link = status?.link
  if (!link) return null
  const st = link.state
  const tp = link.transport
  const cards = linkCards(status, (k) => t(k))
  const rows = timerRows((k) => t(k))
  const events = timeline(status, (k) => t(k))

  return (
    <Panel
      title={t('link.title')}
      right={
        <span className="app-row">
          <Tag type={st ? TAG_TYPE[stateTone(st.state)] : 'cool-gray'}>
            {st ? t(`link.state.${st.state}` as Parameters<typeof t>[0]) : t('link.noEngine')}
          </Tag>
        </span>
      }
    >
      <div className="app-hint">{t('link.hint')}</div>

      {!st ? <Note kind="info" title={t('link.engineOff')} /> : null}
      {tp?.last_error ? (
        <Note kind="error" title={t('link.lastError', {
          error: lastErrorText(status), when: lastErrorWhen(status),
        })} />
      ) : null}

      <div className="app-tiles" style={{ marginTop: 12 }}>
        {cards.map((c) => (
          <Stat key={c.label as string} label={t(c.label)}
            value={c.value} />
        ))}
      </div>

      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginTop: 14 }}>
        <div style={{ minWidth: 260, flex: '0 0 auto' }}>
          <KvList items={rows.map((r) => ({
            term: r.label,
            value: st ? r.text(st.timers[r.name]) : '—',
          }))} />
        </div>
        <div style={{ minWidth: 280, flex: '1 1 320px' }}>
          <div className="app-hint" style={{ marginBottom: 6 }}>{t('link.timeline')}</div>
          {events.length === 0 ? (
            <div className="app-hint">{t('link.timelineEmpty')}</div>
          ) : (
            <ol className="mono" style={{ margin: 0, paddingInlineStart: 18, fontSize: 12 }}>
              {events.map((e, i) => (
                <li key={`${e.ts}-${i}`}>{e.ts} · {e.text}</li>
              ))}
            </ol>
          )}
        </div>
      </div>

      {tp ? (
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--cds-text-secondary)' }}>
          {t('link.transportLine', {
            target: tp.target || '—',
            tls: tp.tls ? 'TLS' : t('link.plain'),
            interval: tp.reconnect_interval ? `${tp.reconnect_interval}s` : '—',
            ever: tp.ever_connected ? t('link.everYes') : t('link.everNo'),
          })}
        </div>
      ) : null}
    </Panel>
  )
}