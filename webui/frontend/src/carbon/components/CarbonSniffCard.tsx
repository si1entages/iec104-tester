import { Button, Link, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useT } from '../../i18n'
import { useSniffer } from '../../lib/useSniffer'
import { Note, Panel, Stat } from '../components/ui'

/** 旁路真实网卡抓包（WP9）：能力探测 + 启停 + 导出 pcap。 */
export function CarbonSniffCard() {
  const t = useT()
  const s = useSniffer()
  const cap = s.capability

  return (
    <Panel
      title={
        <span className="app-row">
          {t('sniff.title')}
          {s.running ? <Tag size="sm" type="green">{t('sniff.running')}</Tag> : null}
          {cap && !cap.available ? (
            <Tag size="sm" type="cool-gray">{t('sniff.unavailable')}</Tag>
          ) : null}
        </span>
      }
      right={
        <span className="app-row">
          <Button kind="ghost" size="sm" onClick={s.refresh}
            data-testid="sniff-refresh">{t('sniff.refresh')}</Button>
          <Button kind="primary" size="sm" disabled={s.busy || s.running}
            onClick={s.actions.start} data-testid="sniff-start">{t('sniff.start')}</Button>
          <Button kind="danger" size="sm" disabled={s.busy || !s.running}
            onClick={s.actions.stop} data-testid="sniff-stop">{t('sniff.stop')}</Button>
          <Link href={api.sniff.exportUrl()} download>{t('sniff.export')}</Link>
        </span>
      }
    >
      <div className="app-hint">{t('sniff.hint')}</div>

      {s.error ? <Note kind="error" title={t('common.error')}>{s.error}</Note> : null}
      {cap && !cap.available ? (
        <Note kind="warning" title={t('sniff.unavailableTitle')}>{cap.reason}</Note>
      ) : null}
      {cap && cap.available && !s.running ? (
        <Note kind="info" title={t('sniff.readyTitle')}>{cap.reason}</Note>
      ) : null}
      {s.stats?.last_error ? (
        <Note kind="error" title={t('sniff.lastError', { error: s.stats.last_error })} />
      ) : null}

      {s.stats ? (
        <div className="app-tiles" style={{ marginTop: 12 }}>
          <Stat label={t('sniff.stat.apdus')} value={String(s.stats.apdus)} />
          <Stat label={t('sniff.stat.packets')} value={String(s.stats.packets)} />
          <Stat label={t('sniff.stat.bytes')} value={String(s.stats.bytes)} />
          <Stat label={t('sniff.stat.dropped')} value={String(s.stats.dropped)} />
        </div>
      ) : null}

      <div style={{ marginTop: 10, fontSize: 12, color: 'var(--cds-text-secondary)' }}>
        {t('sniff.footer', {
          frames: s.frames, port: s.status?.port ?? '-',
          backend: cap?.backend || t('sniff.noBackend'),
        })}
      </div>
    </Panel>
  )
}
