import { useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Checkbox,
  Flex,
  Label,
  TextInput,
} from '@patternfly/react-core'

import { commissionExportUrl } from '../../api/endpoints'
import type { CommissionItem, CommissionVerdict } from '../../api/types'
import { useT } from '../../i18n'
import { useCommission } from '../../lib/useCommission'

const VERDICT_COLOR: Record<CommissionVerdict, 'green' | 'red' | 'orange' | 'grey'> = {
  pass: 'green', fail: 'red', manual: 'orange', pending: 'grey',
}

function VerdictCell({ item, t, onSet }: {
  item: CommissionItem
  t: ReturnType<typeof useT>
  onSet: (v: CommissionVerdict) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}
      flexWrap={{ default: 'wrap' }}>
      <Label isCompact color={VERDICT_COLOR[item.verdict]}>
        {t(`commission.verdict.${item.verdict}` as const)}
      </Label>
      {open ? (
        <>
          {(['pass', 'fail', 'manual'] as const).map((v) => (
            <Button key={v} variant="link" isInline size="sm"
              onClick={() => { onSet(v); setOpen(false) }}>
              {t(`commission.verdict.${v}` as const)}
            </Button>
          ))}
        </>
      ) : (
        <Button variant="link" isInline size="sm" aria-label={t('commission.manualVerdict')}
          onClick={() => setOpen(true)}>✎</Button>
      )}
    </Flex>
  )
}

export function PfCommissionPage() {
  const t = useT()
  const c = useCommission()
  const s = c.detail.data?.session

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <CardTitle>
          <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
            <span>{t('commission.title')}</span>
            <Button variant="link" isInline size="sm" onClick={c.actions.refresh}
              data-testid="commission-refresh">{t('commission.refresh')}</Button>
          </Flex>
        </CardTitle>
        <CardBody>
          <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 12 }}>{t('commission.hint')}</div>
          {c.error ? (
            <Label isCompact color="red">{t('commission.error', { error: c.error })}</Label>
          ) : null}
          <Flex alignItems={{ default: 'alignItemsFlexEnd' }} gap={{ default: 'gapSm' }}
            flexWrap={{ default: 'wrap' }} style={{ marginTop: 8 }}>
            <div>
              <div style={{ fontSize: 12, marginBottom: 4 }}>{t('commission.sessionName')}</div>
              <TextInput id="pf-commission-name" aria-label={t('commission.sessionName')}
                value={c.newName} onChange={(_e, v) => c.setNewName(v)} />
            </div>
            <div>
              <div style={{ fontSize: 12, marginBottom: 4 }}>{t('commission.operator')}</div>
              <TextInput id="pf-commission-operator" aria-label={t('commission.operator')}
                value={c.operator} onChange={(_e, v) => c.setOperator(v)} />
            </div>
            <Button variant="primary" isDisabled={c.busy} onClick={c.actions.create}
              data-testid="commission-create">{t('commission.create')}</Button>
            <span style={{ fontSize: 12, opacity: 0.7 }}>
              {t('commission.selected', { n: c.selected.size })}
            </span>
            <Button variant="link" isInline size="sm" onClick={() => c.selectAll(c.points)}>
              {t('commission.selectAll')}
            </Button>
            <Button variant="link" isInline size="sm" onClick={() => c.setSelected(new Set())}>
              {t('commission.selectNone')}
            </Button>
          </Flex>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>{t('commission.newSession')}</CardTitle>
        <CardBody>
          {c.sessions.length === 0 ? (
            <div style={{ fontSize: 12, opacity: 0.7 }}>{t('commission.noSession')}</div>
          ) : (
            <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}
              data-testid="commission-sessions">
              <thead className="pf-v6-c-table__thead">
                <tr className="pf-v6-c-table__tr">
                  <th className="pf-v6-c-table__th">{t('commission.sessionName')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 140, minWidth: 140 }}>{t('commission.operator')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 120, minWidth: 120 }}>{t('commission.col.verdict')}</th>
                  <th className="pf-v6-c-table__th">{t('commission.summary')}</th>
                </tr>
              </thead>
              <tbody className="pf-v6-c-table__tbody">
                {c.sessions.map((row) => (
                  <tr key={row.id} className="pf-v6-c-table__tr"
                    onClick={() => c.setActiveId(row.id)}
                    style={{ cursor: 'pointer', background: row.id === c.activeId ? 'var(--pf-t--global--background--color--secondary--default)' : undefined }}>
                    <td className="pf-v6-c-table__td">{row.name}</td>
                    <td className="pf-v6-c-table__td">{row.operator}</td>
                    <td className="pf-v6-c-table__td">
                      <Label isCompact color={row.status === 'done' ? 'green' : row.status === 'running' ? 'blue' : 'grey'}>
                        {t(`commission.status.${row.status}` as const)}
                      </Label>
                    </td>
                    <td className="pf-v6-c-table__td">{t('commission.summary', {
                      total: row.summary.total, pass: row.summary.pass,
                      fail: row.summary.fail, manual: row.summary.manual,
                      pending: row.summary.pending,
                    })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>

      {c.activeId ? (
        <Card>
          <CardTitle>
            <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
              <span>{s?.name ?? c.activeId}</span>
              <Button variant="primary" size="sm" isDisabled={c.busy || c.running}
                onClick={c.actions.run} data-testid="commission-run">{t('commission.run')}</Button>
              <Button variant="danger" size="sm" isDisabled={c.busy || !c.running}
                onClick={c.actions.stop} data-testid="commission-stop">{t('commission.stop')}</Button>
              <Button variant="link" isInline size="sm" isDisabled={c.busy || c.running}
                onClick={c.actions.remove}>{t('commission.delete')}</Button>
            </Flex>
          </CardTitle>
          <CardBody>
            {s ? (
              <>
                <Flex gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }} style={{ marginBottom: 10 }}>
                  <Label isCompact color={c.running ? 'blue' : 'grey'}>
                    {t(`commission.status.${s.status}` as const)}
                  </Label>
                  <span style={{ fontSize: 12, opacity: 0.7 }}>
                    {t('commission.progress', { cursor: s.cursor, total: s.summary.total })}
                  </span>
                  <span style={{ fontSize: 12, opacity: 0.7 }}>
                    {t('commission.summary', {
                      total: s.summary.total, pass: s.summary.pass, fail: s.summary.fail,
                      manual: s.summary.manual, pending: s.summary.pending,
                    })}
                  </span>
                </Flex>
                <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }} style={{ marginBottom: 10 }}>
                  {(['xlsx', 'json', 'html'] as const).map((f) => (
                    <a key={f} href={commissionExportUrl(s.id, f)} download={f !== 'html'}
                      target={f === 'html' ? '_blank' : undefined}>
                      {t(`commission.export${f === 'xlsx' ? 'Xlsx' : f === 'json' ? 'Json' : 'Html'}` as const)}
                    </a>
                  ))}
                </Flex>
                {s.items.length === 0 ? (
                  <div style={{ fontSize: 12, opacity: 0.7 }}>{t('commission.noItems')}</div>
                ) : (
                  <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}
                    data-testid="commission-items">
                    <thead className="pf-v6-c-table__thead">
                      <tr className="pf-v6-c-table__tr">
                        <th className="pf-v6-c-table__th" style={{ width: 80, minWidth: 80 }}>{t('commission.col.ioa')}</th>
                        <th className="pf-v6-c-table__th">{t('commission.col.name')}</th>
                        <th className="pf-v6-c-table__th" style={{ width: 70, minWidth: 70 }}>{t('commission.col.kind')}</th>
                        <th className="pf-v6-c-table__th" style={{ width: 100, minWidth: 100 }}>{t('commission.col.expected')}</th>
                        <th className="pf-v6-c-table__th" style={{ width: 100, minWidth: 100 }}>{t('commission.col.actual')}</th>
                        <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>{t('commission.col.quality')}</th>
                        <th className="pf-v6-c-table__th" style={{ width: 160, minWidth: 160 }}>{t('commission.col.verdict')}</th>
                        <th className="pf-v6-c-table__th">{t('commission.col.reason')}</th>
                        <th className="pf-v6-c-table__th">{t('commission.col.evidence')}</th>
                      </tr>
                    </thead>
                    <tbody className="pf-v6-c-table__tbody">
                      {s.items.map((it) => (
                        <tr key={it.ioa} className="pf-v6-c-table__tr">
                          <td className="pf-v6-c-table__td">{it.ioa}</td>
                          <td className="pf-v6-c-table__td">{it.name}</td>
                          <td className="pf-v6-c-table__td">{it.kind}</td>
                          <td className="pf-v6-c-table__td">{it.expected === null || it.expected === undefined ? '—' : String(it.expected)}</td>
                          <td className="pf-v6-c-table__td">{it.actual === null || it.actual === undefined ? '—' : String(it.actual)}</td>
                          <td className="pf-v6-c-table__td">{it.quality || '—'}</td>
                          <td className="pf-v6-c-table__td">
                            <VerdictCell item={it} t={t}
                              onSet={(v) => c.actions.setVerdict(it, v, it.note)} />
                          </td>
                          <td className="pf-v6-c-table__td">{it.reason || it.note || '—'}</td>
                          <td className="pf-v6-c-table__td" style={{ fontSize: 10, wordBreak: 'break-all' }}>
                            {it.tx_frame ? t('commission.evidence.tx', { hex: it.tx_frame.slice(0, 24) }) : ''}
                            <br />
                            {it.rx_frame ? t('commission.evidence.rx', { hex: it.rx_frame.slice(0, 24) }) : ''}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            ) : null}
          </CardBody>
        </Card>
      ) : null}

      {!c.activeId ? (
        <Card>
          <CardTitle>{t('commission.selectAll')}</CardTitle>
          <CardBody>
            <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 10 }}>
              {t('commission.commandIoaHint')}
            </div>
            <div style={{ overflowX: 'auto' }}>
            <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', minWidth: 700, tableLayout: 'fixed' }}
              data-testid="commission-points">
              <thead className="pf-v6-c-table__thead">
                <tr className="pf-v6-c-table__tr">
                  <th className="pf-v6-c-table__th" style={{ width: 44, minWidth: 44 }} />
                  <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>{t('commission.col.ioa')}</th>
                  <th className="pf-v6-c-table__th">{t('commission.col.name')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 80, minWidth: 80 }}>{t('commission.col.kind')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 130, minWidth: 130 }}>{t('commission.col.expected')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 130, minWidth: 130 }}>{t('commission.commandIoa')}</th>
                </tr>
              </thead>
              <tbody className="pf-v6-c-table__tbody">
                {c.points.slice(0, 200).map((p) => (
                  <tr key={p.ioa} className="pf-v6-c-table__tr">
                    <td className="pf-v6-c-table__td">
                      <Checkbox id={`pf-cp-${p.ioa}`} aria-label={String(p.ioa)}
                        isChecked={c.selected.has(p.ioa)}
                        onChange={(_e, checked) => { if (checked !== c.selected.has(p.ioa)) c.toggle(p.ioa) }} />
                    </td>
                    <td className="pf-v6-c-table__td">{p.ioa}</td>
                    <td className="pf-v6-c-table__td">{p.name}</td>
                    <td className="pf-v6-c-table__td">{p.type}</td>
                    <td className="pf-v6-c-table__td">
                      <TextInput aria-label={t('commission.expectedPlaceholder')}
                        placeholder={t('commission.expectedPlaceholder')}
                        value={c.drafts[p.ioa]?.value ?? ''}
                        onChange={(_e, v) => c.setDraft(p.ioa, { value: v })} />
                    </td>
                    <td className="pf-v6-c-table__td">
                      <TextInput aria-label={t('commission.commandIoa')}
                        placeholder={t('commission.commandIoaPlaceholder')}
                        value={c.drafts[p.ioa]?.commandIoa ?? ''}
                        onChange={(_e, v) => c.setDraft(p.ioa, { commandIoa: v })} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </CardBody>
        </Card>
      ) : null}
    </div>
  )
}
