import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  Label,
  TextInput,
} from '@patternfly/react-core'

import { auditExportUrl } from '../../api/endpoints'
import type { AuditRecord } from '../../api/types'
import { useT } from '../../i18n'
import { useAudit, type AuditVerifyResult } from '../../lib/useAudit'

function fmtTime(ts: number | null | undefined): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`
}

function VerifyBanner({ result, t }: { result: AuditVerifyResult; t: ReturnType<typeof useT> }) {
  const ok = result.valid
  return (
    <Label isCompact color={ok ? 'green' : 'red'}>
      {ok
        ? t('audit.verifyOkDetail', { total: result.total })
        : t('audit.verifyBrokenDetail', { id: result.broken_at ?? -1, reason: result.reason })}
    </Label>
  )
}

function ResultLabel({ rec, t }: { rec: AuditRecord; t: ReturnType<typeof useT> }) {
  return (
    <Label isCompact color={rec.result === 'ok' ? 'green' : 'red'}>
      {rec.result === 'ok' ? t('audit.result.ok') : t('audit.result.fail')}
    </Label>
  )
}

export function PfAuditPage() {
  const t = useT()
  const a = useAudit()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <CardTitle>
          <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
            <span>{t('audit.title')}</span>
            <Button variant="link" isInline size="sm" onClick={a.refresh}
              data-testid="audit-refresh">{t('audit.refresh')}</Button>
            <Button variant="primary" size="sm" isDisabled={a.busy} onClick={a.verify}
              data-testid="audit-verify">{t('audit.verify')}</Button>
            <a href={auditExportUrl('json')} download>{t('audit.exportJson')}</a>
            <a href={auditExportUrl('csv')} download>{t('audit.exportCsv')}</a>
          </Flex>
        </CardTitle>
        <CardBody>
          <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 12 }}>{t('audit.hint')}</div>
          {a.error ? (
            <Label isCompact color="red">{a.error}</Label>
          ) : null}
          <Flex alignItems={{ default: 'alignItemsFlexEnd' }} gap={{ default: 'gapSm' }}
            flexWrap={{ default: 'wrap' }} style={{ marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 12, marginBottom: 4 }}>{t('audit.operatorName')}</div>
              <TextInput id="pf-audit-operator" aria-label={t('audit.operatorName')}
                value={a.operator} onChange={(_e, v) => a.changeOperator(v)} />
            </div>
            <span style={{ fontSize: 12, opacity: 0.7 }}>{t('audit.operatorHint')}</span>
            {a.stats ? (
              <span style={{ fontSize: 12, opacity: 0.7 }}>
                {t('audit.stats', {
                  total: a.stats.total, fails: a.stats.fails, operators: a.stats.operators,
                })}
              </span>
            ) : null}
          </Flex>
          {a.verifyResult ? <VerifyBanner result={a.verifyResult} t={t} /> : null}
        </CardBody>
      </Card>

      <Card>
        <CardTitle>{t('audit.records')}</CardTitle>
        <CardBody>
          {a.records.length === 0 ? (
            <div style={{ fontSize: 12, opacity: 0.7 }}>{t('audit.empty')}</div>
          ) : (
            <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}
              data-testid="audit-records">
              <thead className="pf-v6-c-table__thead">
                <tr className="pf-v6-c-table__tr">
                  <th className="pf-v6-c-table__th" style={{ width: 150, minWidth: 150 }}>{t('audit.col.time')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 110, minWidth: 110 }}>{t('audit.col.operator')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 80, minWidth: 80 }}>{t('audit.col.role')}</th>
                  <th className="pf-v6-c-table__th">{t('audit.col.action')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>{t('audit.col.target')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 80, minWidth: 80 }}>{t('audit.col.result')}</th>
                  <th className="pf-v6-c-table__th">{t('audit.col.reason')}</th>
                  <th className="pf-v6-c-table__th">{t('audit.col.frames')}</th>
                </tr>
              </thead>
              <tbody className="pf-v6-c-table__tbody">
                {a.records.map((rec) => (
                  <tr key={rec.id} className="pf-v6-c-table__tr">
                    <td className="pf-v6-c-table__td" style={{ fontSize: 12 }}>{fmtTime(rec.ts)}</td>
                    <td className="pf-v6-c-table__td">{rec.operator || '—'}</td>
                    <td className="pf-v6-c-table__td">{rec.role || '—'}</td>
                    <td className="pf-v6-c-table__td mono" style={{ fontSize: 11 }}>{rec.action}</td>
                    <td className="pf-v6-c-table__td">{rec.target || '—'}</td>
                    <td className="pf-v6-c-table__td"><ResultLabel rec={rec} t={t} /></td>
                    <td className="pf-v6-c-table__td" style={{ fontSize: 12 }}>{rec.reason || '—'}</td>
                    <td className="pf-v6-c-table__td" style={{ fontSize: 10, wordBreak: 'break-all' }}>
                      {rec.tx_frame ? t('audit.frameTx', { hex: rec.tx_frame.slice(0, 24) }) : ''}
                      <br />
                      {rec.rx_frame ? t('audit.frameRx', { hex: rec.rx_frame.slice(0, 24) }) : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
