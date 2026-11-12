import { Button, Link, Tag } from '@carbon/react'

import { auditExportUrl } from '../../api/endpoints'
import type { AuditRecord } from '../../api/types'
import { useT } from '../../i18n'
import { useAudit } from '../../lib/useAudit'
import { Note, Panel, TableFrame, TextField } from '../components/ui'

/** 时间戳 → 本地时间字符串（审计列表展示用） */
function fmtTime(ts: number | null | undefined): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`
}

function resultTag(rec: AuditRecord, t: ReturnType<typeof useT>) {
  const label = rec.result === 'ok' ? t('audit.result.ok') : t('audit.result.fail')
  return <Tag type={rec.result === 'ok' ? 'green' : 'red'}>{label}</Tag>
}

export function CarbonAuditPage() {
  const t = useT()
  const a = useAudit()

  return (
    <div className="app-gap">
      <Panel title={t('audit.title')} right={
        <span className="app-row">
          <Button kind="ghost" size="sm" onClick={a.refresh}
            data-testid="audit-refresh">{t('audit.refresh')}</Button>
          <Button kind="primary" size="sm" disabled={a.busy} onClick={a.verify}
            data-testid="audit-verify">{t('audit.verify')}</Button>
          <Link href={auditExportUrl('json')} download>
            {t('audit.exportJson')}
          </Link>
          <Link href={auditExportUrl('csv')} download>{t('audit.exportCsv')}</Link>
        </span>
      }>
        <div className="app-hint">{t('audit.hint')}</div>
        {a.error ? <Note kind="error" title={t('common.error')}>{a.error}</Note> : null}
        <div className="app-row" style={{ marginTop: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <TextField id="audit-operator" label={t('audit.operatorName')}
            value={a.operator} onChange={a.changeOperator} width={200}
          />
          <span className="app-hint">{t('audit.operatorHint')}</span>
          {a.stats ? (
            <span className="app-hint">
              {t('audit.stats', {
                total: a.stats.total, fails: a.stats.fails, operators: a.stats.operators,
              })}
            </span>
          ) : null}
        </div>
        {a.verifyResult ? (
          <Note kind={a.verifyResult.valid ? 'success' : 'error'}
            title={t(a.verifyResult.valid ? 'audit.verifyOk' : 'audit.verifyBroken')}>
            {a.verifyResult.valid
              ? t('audit.verifyOkDetail', { total: a.verifyResult.total })
              : t('audit.verifyBrokenDetail', {
                  id: a.verifyResult.broken_at ?? -1, reason: a.verifyResult.reason,
                })}
          </Note>
        ) : null}
      </Panel>

      <Panel title={t('audit.records')}>
        {a.records.length === 0 ? (
          <div className="app-hint">{t('audit.empty')}</div>
        ) : (
          <TableFrame testid="audit-records">
            <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
              <thead><tr>
                <th style={{ width: 90 }}>{t('audit.col.time')}</th>
                <th style={{ width: 110 }}>{t('audit.col.operator')}</th>
                <th style={{ width: 80 }}>{t('audit.col.role')}</th>
                <th>{t('audit.col.action')}</th>
                <th style={{ width: 90 }}>{t('audit.col.target')}</th>
                <th style={{ width: 80 }}>{t('audit.col.result')}</th>
                <th>{t('audit.col.reason')}</th>
                <th>{t('audit.col.frames')}</th>
              </tr></thead>
              <tbody>
                {a.records.map((rec) => (
                  <tr key={rec.id}>
                    <td style={{ fontSize: 12 }}>{fmtTime(rec.ts)}</td>
                    <td>{rec.operator || '—'}</td>
                    <td>{rec.role || '—'}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{rec.action}</td>
                    <td>{rec.target || '—'}</td>
                    <td>{resultTag(rec, t)}</td>
                    <td style={{ fontSize: 12 }}>{rec.reason || '—'}</td>
                    <td className="mono" style={{ fontSize: 10, wordBreak: 'break-all' }}>
                      {rec.tx_frame ? t('audit.frameTx', { hex: rec.tx_frame.slice(0, 24) }) : ''}
                      <br />
                      {rec.rx_frame ? t('audit.frameRx', { hex: rec.rx_frame.slice(0, 24) }) : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
        )}
      </Panel>
    </div>
  )
}
