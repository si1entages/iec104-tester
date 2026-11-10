import { useEffect, useRef, useState } from 'react'

import { Button, Tag } from '@carbon/react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { queryKeys, useTimelineQuery } from '../../api/queries'
import { useT, type MessageKey } from '../../i18n'
import type { TimelineExpect, TimelineStep } from '../../api/types'
import { NumField, Panel, SelectField, TextField } from './ui'

const EXPECT_OPTIONS: { value: TimelineExpect; labelKey: string }[] = [
  { value: 'none', labelKey: 'tl.expect.none' },
  { value: 'loss', labelKey: 'tl.expect.loss' },
  { value: 'k-exceed', labelKey: 'tl.expect.k-exceed' },
  { value: 't1', labelKey: 'tl.expect.t1' },
  { value: 'disconnect', labelKey: 'tl.expect.disconnect' },
]

interface EditRow {
  label: string
  duration_s: number
  loss_pct: number
  delay_ms: number
  expect: TimelineExpect
}

function toEditRow(step: TimelineStep): EditRow {
  const cond = (step.condition ?? {}) as Record<string, number | string>
  return {
    label: step.label,
    duration_s: Number(step.duration_s) || 2,
    loss_pct: cond.loss_rate !== undefined ? Math.round(Number(cond.loss_rate) * 100) : 0,
    delay_ms: cond.delay_ms !== undefined ? Number(cond.delay_ms) : 0,
    expect: step.expect,
  }
}

function toStep(row: EditRow, idx: number): TimelineStep {
  const condition: Record<string, number | string> = {}
  if (Number(row.loss_pct) > 0) condition.loss_rate = Number(row.loss_pct) / 100
  if (Number(row.delay_ms) > 0) condition.delay_ms = Number(row.delay_ms)
  return {
    label: row.label.trim() || `step-${idx + 1}`,
    duration_s: row.duration_s > 0 ? row.duration_s : 2,
    condition,
    expect: row.expect,
  }
}

/**
 * 注入时间线卡（T97，Carbon 版）：步骤编排 + 保存/运行/停止 + 逐步判定结果行.
 * 判定口径在后端（webui/timeline.py::judge），前端只展示红绿与证据摘要.
 */
export function CarbonTimelineCard() {
  const t = useT()
  const queryClient = useQueryClient()
  const { data } = useTimelineQuery()
  const [rows, setRows] = useState<EditRow[]>([])
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const synced = useRef(false)

  useEffect(() => {
    if (!synced.current && data?.steps) {
      synced.current = true
      setRows(data.steps.map(toEditRow))
    }
  }, [data])

  const patch = (i: number, p: Partial<EditRow>): void =>
    setRows(rows.map((r, idx) => (idx === i ? { ...r, ...p } : r)))

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.timeline() })
  }

  const save = async (): Promise<void> => {
    const steps = rows.map(toStep)
    const r = await api.timelineSet(steps)
    setMsg(r.ok
      ? { ok: true, text: t('tl.saved', { n: r.steps ?? steps.length }) }
      : { ok: false, text: r.error ?? t('cmd.unknown') })
    invalidate()
  }

  const run = async (): Promise<void> => {
    const r = await api.timelineRun()
    setMsg(r.ok
      ? { ok: true, text: t('tl.running') }
      : { ok: false, text: r.error ?? t('cmd.unknown') })
    invalidate()
  }

  const stop = async (): Promise<void> => {
    await api.timelineStop()
    invalidate()
  }

  const result = data?.last_result ?? null
  const steps = result?.steps ?? []
  const passed = steps.filter((s) => s.ok).length
  const judged = steps.filter((s) => !s.skipped).length

  return (
    <Panel title={t('tl.title')}>
      <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginBottom: 8 }}>
        {t('tl.hint')}
      </div>

      {rows.length === 0 ? (
        <div style={{ color: 'var(--cds-text-secondary)', fontSize: 13, marginBottom: 8 }}>
          {t('tl.noSteps')}
        </div>
      ) : (
        <div className="app-table-scroll" data-testid="timeline-rows">
          <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed', minWidth: 700 }}>
            <thead>
              <tr>
                <th style={{ width: 180, minWidth: 180 }}><span className="cds--table-header-label">{t('tl.colLabel')}</span></th>
                <th style={{ width: 90, minWidth: 90 }}><span className="cds--table-header-label">{t('tl.colDur')}</span></th>
                <th style={{ width: 90, minWidth: 90 }}><span className="cds--table-header-label">{t('tl.colLoss')}</span></th>
                <th style={{ width: 90, minWidth: 90 }}><span className="cds--table-header-label">{t('tl.colDelay')}</span></th>
                <th style={{ width: 130, minWidth: 130 }}><span className="cds--table-header-label">{t('tl.colExpect')}</span></th>
                <th style={{ width: 70, minWidth: 70 }}><span className="cds--table-header-label">{t('tl.remove')}</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td>
                    <TextField id={`tl-label-${i}`} label="" hideLabel value={row.label}
                      onChange={(v) => patch(i, { label: v })} />
                  </td>
                  <td>
                    <NumField id={`tl-dur-${i}`} label="" hideLabel width={80} min={0.5} max={600}
                      value={row.duration_s} onChange={(v) => patch(i, { duration_s: v })} />
                  </td>
                  <td>
                    <NumField id={`tl-loss-${i}`} label="" hideLabel width={80} min={0} max={100}
                      value={row.loss_pct} onChange={(v) => patch(i, { loss_pct: v })} />
                  </td>
                  <td>
                    <NumField id={`tl-delay-${i}`} label="" hideLabel width={80} min={0} max={5000}
                      value={row.delay_ms} onChange={(v) => patch(i, { delay_ms: v })} />
                  </td>
                  <td>
                    <SelectField
                      id={`tl-expect-${i}`}
                      label=""
                      hideLabel
                      width={120}
                      value={row.expect}
                      options={EXPECT_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey as MessageKey) }))}
                      onChange={(v) => patch(i, { expect: v as TimelineExpect })}
                    />
                  </td>
                  <td>
                    <Button kind="danger--ghost" size="sm" onClick={() => setRows(rows.filter((_, idx) => idx !== i))}>
                      {t('tl.remove')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="app-row" style={{ marginTop: 8, flexWrap: 'wrap' }}>
        <Button kind="secondary" size="sm" onClick={() => setRows([...rows, {
          label: t('tl.stepDefault', { n: rows.length + 1 }), duration_s: 2, loss_pct: 0, delay_ms: 0,
          expect: 'none',
        }])}>
          {t('tl.add')}
        </Button>
        <Button kind="secondary" size="sm" disabled={rows.length === 0} onClick={() => void save()}>
          {t('tl.save')}
        </Button>
        <Button kind="primary" size="sm" disabled={rows.length === 0 || data?.running} onClick={() => void run()}
          data-testid="timeline-run">
          {t('tl.run')}
        </Button>
        <Button kind="danger" size="sm" disabled={!data?.running} onClick={() => void stop()}>
          {t('tl.stop')}
        </Button>
        {data?.running ? <Tag size="sm" type="blue">{t('tl.running')}</Tag> : null}
      </div>
      {msg ? (
        <div style={{ marginTop: 6, fontSize: 13, color: msg.ok ? 'var(--cds-support-success)' : 'var(--cds-text-error)' }}>
          {msg.text}
        </div>
      ) : null}

      <div style={{ marginTop: 14, fontSize: 13 }}>{t('tl.lastResult')}</div>
      {!result ? (
        <div style={{ color: 'var(--cds-text-secondary)', fontSize: 13 }}>{t('tl.noResult')}</div>
      ) : (
        <div style={{ marginTop: 6 }} data-testid="timeline-result">
          <Tag size="sm" type={result.ok ? 'green' : 'red'}>
            {result.ok ? t('tl.allPass') : t('tl.verdict', { passed, total: judged })}
          </Tag>
          {steps.map((s, i) => (
            <div key={i} className="app-row" style={{ marginTop: 6, alignItems: 'baseline' }}>
              {s.skipped ? (
                <Tag size="sm" type="warm-gray">{t('tl.skipped')}</Tag>
              ) : (
                <Tag size="sm" type={s.ok ? 'green' : 'red'} data-testid={`timeline-step-${s.ok ? 'ok' : 'fail'}`}>
                  {s.ok ? t('tl.pass') : t('tl.fail')}
                </Tag>
              )}
              <span style={{ fontSize: 13, minWidth: 90 }}><b>{s.label}</b></span>
              <span style={{ fontSize: 12, color: 'var(--cds-text-secondary)', flex: 1, minWidth: 120 }}>
                {s.condition} · {s.detail}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
