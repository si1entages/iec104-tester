import { useState } from 'react'

import { Button, Checkbox, Link, Tag } from '@carbon/react'

import { commissionExportUrl } from '../../api/endpoints'
import type { CommissionItem, CommissionVerdict } from '../../api/types'
import { useT } from '../../i18n'
import { useCommission } from '../../lib/useCommission'
import { Note, Panel, TableFrame, TextField } from '../components/ui'

const VERDICT_TONE: Record<CommissionVerdict, 'green' | 'red' | 'magenta' | 'gray'> = {
  pass: 'green', fail: 'red', manual: 'magenta', pending: 'gray',
}

/** 逐点结论展示 + 人工改判（两套件共用纯逻辑，由 useCommission 提供）。 */
function VerdictCell({ item, t, onSet }: {
  item: CommissionItem
  t: ReturnType<typeof useT>
  onSet: (v: CommissionVerdict) => void
}) {
  const [open, setOpen] = useState(false)
  const key = `commission.verdict.${item.verdict}` as const
  return (
    <span>
      <Tag type={VERDICT_TONE[item.verdict]}>{t(key)}</Tag>
      {open ? (
        <span style={{ marginLeft: 6 }}>
          {(['pass', 'fail', 'manual'] as const).map((v) => (
            <Button key={v} kind="ghost" size="sm"
              onClick={() => { onSet(v); setOpen(false) }}>
              {t(`commission.verdict.${v}` as const)}
            </Button>
          ))}
        </span>
      ) : (
        <Button kind="ghost" size="sm" aria-label={t('commission.manualVerdict')}
          onClick={() => setOpen(true)}>✎</Button>
      )}
    </span>
  )
}

export function CarbonCommissionPage() {
  const t = useT()
  const c = useCommission()
  const s = c.detail.data?.session

  return (
    <div className="app-gap">
      <Panel title={t('commission.title')} right={
        <Button kind="ghost" size="sm" onClick={c.actions.refresh}
          data-testid="commission-refresh">{t('commission.refresh')}</Button>
      }>
        <div className="app-hint">{t('commission.hint')}</div>
        {c.error ? <Note kind="error" title={t('common.error')}>{t('commission.error', { error: c.error })}</Note> : null}
        <div className="app-row" style={{ marginTop: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <TextField id="commission-name" label={t('commission.sessionName')}
            value={c.newName} onChange={c.setNewName} width={220} />
          <TextField id="commission-operator" label={t('commission.operator')}
            value={c.operator} onChange={c.setOperator} width={160} />
          <Button kind="primary" disabled={c.busy} onClick={c.actions.create}
            data-testid="commission-create">{t('commission.create')}</Button>
          <span className="app-hint">{t('commission.selected', { n: c.selected.size })}</span>
          <Button kind="ghost" size="sm" onClick={() => c.selectAll(c.points)}>
            {t('commission.selectAll')}
          </Button>
          <Button kind="ghost" size="sm" onClick={() => c.setSelected(new Set())}>
            {t('commission.selectNone')}
          </Button>
        </div>
      </Panel>

      <Panel title={t('commission.newSession')}>
        {c.sessions.length === 0 ? (
          <div className="app-hint">{t('commission.noSession')}</div>
        ) : (
          <TableFrame testid="commission-sessions">
            <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
              <thead><tr>
                <th>{t('commission.sessionName')}</th>
                <th>{t('commission.operator')}</th>
                <th>{t('commission.col.verdict')}</th>
                <th>{t('commission.summary')}</th>
              </tr></thead>
              <tbody>
                {c.sessions.map((row) => (
                  <tr key={row.id} onClick={() => c.setActiveId(row.id)}
                    style={{ cursor: 'pointer', background: row.id === c.activeId ? 'var(--cds-layer-selected-01)' : undefined }}>
                    <td>{row.name}</td>
                    <td>{row.operator}</td>
                    <td>{t(`commission.status.${row.status}` as const)}</td>
                    <td>{t('commission.summary', {
                      total: row.summary.total, pass: row.summary.pass,
                      fail: row.summary.fail, manual: row.summary.manual,
                      pending: row.summary.pending,
                    })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
        )}
      </Panel>

      {c.activeId ? (
        <Panel title={s?.name ?? c.activeId} right={
          <span className="app-row">
            <Button kind="primary" size="sm" disabled={c.busy || c.running}
              onClick={c.actions.run} data-testid="commission-run">{t('commission.run')}</Button>
            <Button kind="danger" size="sm" disabled={c.busy || !c.running}
              onClick={c.actions.stop} data-testid="commission-stop">{t('commission.stop')}</Button>
            <Button kind="ghost" size="sm" disabled={c.busy || c.running}
              onClick={c.actions.remove}>{t('commission.delete')}</Button>
          </span>
        }>
          {s ? (
            <>
              <div className="app-row" style={{ flexWrap: 'wrap', marginBottom: 10 }}>
                <Tag type={c.running ? 'blue' : 'gray'}>
                  {t(`commission.status.${s.status}` as const)}
                </Tag>
                <span className="app-hint">{t('commission.progress', { cursor: s.cursor, total: s.summary.total })}</span>
                <span className="app-hint">{t('commission.summary', {
                  total: s.summary.total, pass: s.summary.pass, fail: s.summary.fail,
                  manual: s.summary.manual, pending: s.summary.pending,
                })}</span>
              </div>
              <div className="app-row" style={{ marginBottom: 10 }}>
                <Link href={commissionExportUrl(s.id, 'xlsx')} download>
                  {t('commission.exportXlsx')}
                </Link>
                <Link href={commissionExportUrl(s.id, 'json')} download>
                  {t('commission.exportJson')}
                </Link>
                <Link href={commissionExportUrl(s.id, 'html')} target="_blank">
                  {t('commission.exportHtml')}
                </Link>
              </div>
              {s.items.length === 0 ? (
                <div className="app-hint">{t('commission.noItems')}</div>
              ) : (
                <TableFrame testid="commission-items">
                  <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
                    <thead><tr>
                      <th style={{ width: 90 }}>{t('commission.col.ioa')}</th>
                      <th>{t('commission.col.name')}</th>
                      <th style={{ width: 70 }}>{t('commission.col.kind')}</th>
                      <th style={{ width: 110 }}>{t('commission.col.expected')}</th>
                      <th style={{ width: 110 }}>{t('commission.col.actual')}</th>
                      <th style={{ width: 90 }}>{t('commission.col.quality')}</th>
                      <th style={{ width: 150 }}>{t('commission.col.verdict')}</th>
                      <th>{t('commission.col.reason')}</th>
                      <th>{t('commission.col.evidence')}</th>
                    </tr></thead>
                    <tbody>
                      {s.items.map((it) => (
                        <tr key={it.ioa}>
                          <td>{it.ioa}</td>
                          <td>{it.name}</td>
                          <td>{it.kind}</td>
                          <td>{it.expected === null || it.expected === undefined ? '—' : String(it.expected)}</td>
                          <td>{it.actual === null || it.actual === undefined ? '—' : String(it.actual)}</td>
                          <td>{it.quality || '—'}</td>
                          <td><VerdictCell item={it} t={t}
                            onSet={(v) => c.actions.setVerdict(it, v, it.note)} /></td>
                          <td>{it.reason || it.note || '—'}</td>
                          <td className="mono" style={{ fontSize: 10, wordBreak: 'break-all' }}>
                            {it.tx_frame ? t('commission.evidence.tx', { hex: it.tx_frame.slice(0, 24) }) : ''}
                            <br />
                            {it.rx_frame ? t('commission.evidence.rx', { hex: it.rx_frame.slice(0, 24) }) : ''}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableFrame>
              )}
            </>
          ) : null}
        </Panel>
      ) : null}

      {!c.activeId ? (
        <Panel title={t('commission.selectAll')}>
          <div className="app-hint" style={{ marginBottom: 10 }}>
            {t('commission.commandIoaHint')}
          </div>
          <div style={{ overflowX: 'auto' }}>
          <TableFrame testid="commission-points">
            <table className="cds--data-table cds--data-table--md" style={{ width: '100%', minWidth: 700, tableLayout: 'fixed' }}>
              <thead><tr>
                <th style={{ width: 44, minWidth: 44 }} />
                <th style={{ width: 90, minWidth: 90 }}>{t('commission.col.ioa')}</th>
                <th>{t('commission.col.name')}</th>
                <th style={{ width: 80, minWidth: 80 }}>{t('commission.col.kind')}</th>
                <th style={{ width: 130, minWidth: 130 }}>{t('commission.col.expected')}</th>
                <th style={{ width: 130, minWidth: 130 }}>{t('commission.commandIoa')}</th>
              </tr></thead>
              <tbody>
                {c.points.slice(0, 200).map((p) => (
                  <tr key={p.ioa}>
                    <td><Checkbox id={`cp-${p.ioa}`} labelText="" aria-label={String(p.ioa)}
                      checked={c.selected.has(p.ioa)} onChange={() => c.toggle(p.ioa)} /></td>
                    <td>{p.ioa}</td>
                    <td>{p.name}</td>
                    <td>{p.type}</td>
                    <td><input className="cds--text-input" style={{ width: '100%' }}
                      aria-label={t('commission.expectedPlaceholder')}
                      placeholder={t('commission.expectedPlaceholder')}
                      value={c.drafts[p.ioa]?.value ?? ''}
                      onChange={(e) => c.setDraft(p.ioa, { value: e.target.value })} /></td>
                    <td><input className="cds--text-input" style={{ width: '100%' }}
                      aria-label={t('commission.commandIoa')}
                      placeholder={t('commission.commandIoaPlaceholder')}
                      value={c.drafts[p.ioa]?.commandIoa ?? ''}
                      onChange={(e) => c.setDraft(p.ioa, { commandIoa: e.target.value })} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
          </div>
        </Panel>
      ) : null}
    </div>
  )
}
