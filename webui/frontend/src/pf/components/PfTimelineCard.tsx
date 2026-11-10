import { useEffect, useRef, useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FormSelect,
  FormSelectOption,
  Label,
} from '@patternfly/react-core'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { queryKeys, useTimelineQuery } from '../../api/queries'
import { useT, type MessageKey } from '../../i18n'
import type { TimelineExpect, TimelineStep } from '../../api/types'

const EXPECT_OPTIONS: { value: TimelineExpect; labelKey: MessageKey }[] = [
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
  if (row.loss_pct > 0) condition.loss_rate = row.loss_pct / 100
  if (row.delay_ms > 0) condition.delay_ms = row.delay_ms
  return {
    label: row.label.trim() || `step-${idx + 1}`,
    duration_s: row.duration_s > 0 ? row.duration_s : 2,
    condition,
    expect: row.expect,
  }
}

const NUM_STYLE = { width: 90, minWidth: 90 }

/**
 * 注入时间线卡（T97，PatternFly 版）：与 CarbonTimelineCard 同构——
 * 步骤编排 + 保存/运行/停止 + 逐步判定结果行.
 */
export function PfTimelineCard() {
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
    <Card>
      <CardTitle>{t('tl.title')}</CardTitle>
      <CardBody>
        <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 8 }}>{t('tl.hint')}</div>

        {rows.length === 0 ? (
          <div style={{ opacity: 0.75, fontSize: 13, marginBottom: 8 }}>{t('tl.noSteps')}</div>
        ) : (
          <div style={{ overflowX: 'auto' }} data-testid="timeline-rows">
            <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed', minWidth: 700 }}>
              <thead className="pf-v6-c-table__thead">
                <tr className="pf-v6-c-table__tr">
                  <th className="pf-v6-c-table__th" style={{ width: 180, minWidth: 180 }}>{t('tl.colLabel')}</th>
                  <th className="pf-v6-c-table__th" style={NUM_STYLE}>{t('tl.colDur')}</th>
                  <th className="pf-v6-c-table__th" style={NUM_STYLE}>{t('tl.colLoss')}</th>
                  <th className="pf-v6-c-table__th" style={NUM_STYLE}>{t('tl.colDelay')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 130, minWidth: 130 }}>{t('tl.colExpect')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 70, minWidth: 70 }}>{t('tl.remove')}</th>
                </tr>
              </thead>
              <tbody className="pf-v6-c-table__tbody">
                {rows.map((row, i) => (
                  <tr key={i} className="pf-v6-c-table__tr">
                    <td className="pf-v6-c-table__td">
                      <input
                        className="pf-v6-c-form-control"
                        value={row.label}
                        onChange={(e) => patch(i, { label: e.target.value })}
                        aria-label={t('tl.colLabel')}
                      />
                    </td>
                    <td className="pf-v6-c-table__td">
                      <input
                        className="pf-v6-c-form-control" type="number" style={NUM_STYLE}
                        min={0.5} max={600} value={row.duration_s}
                        onChange={(e) => patch(i, { duration_s: Number(e.target.value) || 0 })}
                        aria-label={t('tl.colDur')}
                      />
                    </td>
                    <td className="pf-v6-c-table__td">
                      <input
                        className="pf-v6-c-form-control" type="number" style={NUM_STYLE}
                        min={0} max={100} value={row.loss_pct}
                        onChange={(e) => patch(i, { loss_pct: Number(e.target.value) || 0 })}
                        aria-label={t('tl.colLoss')}
                      />
                    </td>
                    <td className="pf-v6-c-table__td">
                      <input
                        className="pf-v6-c-form-control" type="number" style={NUM_STYLE}
                        min={0} max={5000} value={row.delay_ms}
                        onChange={(e) => patch(i, { delay_ms: Number(e.target.value) || 0 })}
                        aria-label={t('tl.colDelay')}
                      />
                    </td>
                    <td className="pf-v6-c-table__td">
                      <FormSelect
                        value={row.expect}
                        onChange={(_e, v) => patch(i, { expect: v as TimelineExpect })}
                        aria-label={t('tl.colExpect')}
                      >
                        {EXPECT_OPTIONS.map((o) => (
                          <FormSelectOption key={o.value} value={o.value} label={t(o.labelKey)} />
                        ))}
                      </FormSelect>
                    </td>
                    <td className="pf-v6-c-table__td">
                      <Button variant="danger" size="sm" onClick={() => setRows(rows.filter((_, idx) => idx !== i))}>
                        {t('tl.remove')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Flex gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          <Button variant="secondary" size="sm" onClick={() => setRows([...rows, {
            label: t('tl.stepDefault', { n: rows.length + 1 }), duration_s: 2, loss_pct: 0,
            delay_ms: 0, expect: 'none',
          }])}>
            {t('tl.add')}
          </Button>
          <Button variant="secondary" size="sm" isDisabled={rows.length === 0} onClick={() => void save()}>
            {t('tl.save')}
          </Button>
          <Button variant="primary" size="sm" isDisabled={rows.length === 0 || data?.running}
            onClick={() => void run()} data-testid="timeline-run">
            {t('tl.run')}
          </Button>
          <Button variant="danger" size="sm" isDisabled={!data?.running} onClick={() => void stop()}>
            {t('tl.stop')}
          </Button>
          {data?.running ? <Label isCompact color="blue">{t('tl.running')}</Label> : null}
        </Flex>
        {msg ? (
          <div style={{
            marginTop: 6, fontSize: 13,
            color: msg.ok
              ? 'var(--pf-t--global--text--color--status--success--default)'
              : 'var(--pf-t--global--text--color--status--danger--default)',
          }}>
            {msg.text}
          </div>
        ) : null}

        <div style={{ marginTop: 14, fontSize: 13 }}>{t('tl.lastResult')}</div>
        {!result ? (
          <div style={{ opacity: 0.75, fontSize: 13 }}>{t('tl.noResult')}</div>
        ) : (
          <div style={{ marginTop: 6 }} data-testid="timeline-result">
            <Label isCompact color={result.ok ? 'green' : 'red'}>
              {result.ok ? t('tl.allPass') : t('tl.verdict', { passed, total: judged })}
            </Label>
            {steps.map((s, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, marginTop: 6, alignItems: 'baseline' }}>
                {s.skipped ? (
                  <Label isCompact color="grey">{t('tl.skipped')}</Label>
                ) : (
                  <Label isCompact color={s.ok ? 'green' : 'red'} data-testid={`timeline-step-${s.ok ? 'ok' : 'fail'}`}>
                    {s.ok ? t('tl.pass') : t('tl.fail')}
                  </Label>
                )}
                <span style={{ fontSize: 13, minWidth: 90 }}><b>{s.label}</b></span>
                <span style={{ fontSize: 12, opacity: 0.8, flex: 1, minWidth: 120 }}>
                  {s.condition} · {s.detail}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
