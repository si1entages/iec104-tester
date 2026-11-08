import { useEffect, useState } from 'react'

import { Button, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { OkResponse, Point } from '../../api/types'
import { useT } from '../../i18n'
import { formatValue } from '../../lib/format'
import { Note, NumField, Panel, SelectField } from './ui'

type SetKind = 'YX' | 'YC' | 'YM' | 'STEP'

interface Props {
  point: Point | null
  disabled?: boolean
}

/** 子站手动置数：YX/YC/YM/STEP 四类，目标 IOA 跟随选中行。 */
export function CarbonManualSetPanel({ point, disabled = false }: Props) {
  const t = useT()
  const [kind, setKind] = useState<SetKind>('YX')
  const [ioa, setIoa] = useState(0)
  const [yx, setYx] = useState(true)
  const [yc, setYc] = useState(0)
  const [ym, setYm] = useState(0)
  const [step, setStep] = useState(0)
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!point) return
    setIoa(point.ioa)
    if (point.type === 'YX' || point.type === 'YC' || point.type === 'YM' || point.type === 'STEP') {
      setKind(point.type)
    }
  }, [point?.ioa, point?.type])

  const yxCmd = useCommand(api.slave.yx)
  const ycCmd = useCommand(api.slave.yc)
  const ymCmd = useCommand(api.slave.ym)
  const stepCmd = useCommand(api.slave.step)
  const busy = yxCmd.isPending || ycCmd.isPending || ymCmd.isPending || stepCmd.isPending

  const run = async (label: string, task: Promise<OkResponse>): Promise<void> => {
    const result = await task
    setLast(
      result.ok
        ? { ok: true, text: t('cmd.done', { label }) }
        : { ok: false, text: t('cmd.failed', { label, error: result.error ?? t('cmd.unknown') }) },
    )
  }

  const noRun = disabled
  const noIoa = ioa <= 0
  const mismatch = Boolean(point && point.type !== kind)

  const send = (): void => {
    if (kind === 'YX') void run(t('msp.kind.yx'), yxCmd.mutateAsync({ ioa, value: yx }))
    else if (kind === 'YC') void run(t('msp.kind.yc'), ycCmd.mutateAsync({ ioa, value: yc }))
    else if (kind === 'YM') void run(t('msp.kind.ym'), ymCmd.mutateAsync({ ioa, value: ym }))
    else void run(t('msp.kind.step'), stepCmd.mutateAsync({ ioa, value: step }))
  }

  return (
    <Panel
      title={
        <span className="app-row">
          {t('msp.title')}
          {point ? (
            <Tag size="sm" type="blue">
              {t('cmd.selected', { type: point.type, ioa: point.ioa })}
            </Tag>
          ) : (
            <Tag size="sm" type="gray">
              {t('cmd.noPoint')}
            </Tag>
          )}
        </span>
      }
    >
      {disabled ? <Note kind="info" title={t('msp.slaveOff')} /> : null}
      {!disabled && noIoa ? <Note kind="warning" title={t('cmd.needIoa')} style={{ marginTop: 8 }} /> : null}
      {last ? <Note kind={last.ok ? 'success' : 'error'} title={last.text} style={{ marginTop: 8 }} /> : null}
      {mismatch ? (
        <div style={{ fontSize: 12, opacity: 0.75, marginTop: 8 }}>{t('msp.mismatch')}</div>
      ) : null}

      <div style={{ marginTop: 12 }} className="app-stack">
        <div style={{ maxWidth: 240 }}>
          <SelectField
            id="cb-msp-kind"
            label={t('common.type')}
            value={kind}
            onChange={(v) => setKind(v as SetKind)}
            options={[
              { value: 'YX', label: t('msp.kind.yx') },
              { value: 'YC', label: t('msp.kind.yc') },
              { value: 'YM', label: t('msp.kind.ym') },
              { value: 'STEP', label: t('msp.kind.step') },
            ]}
          />
        </div>

        <NumField id="cb-msp-ioa" label={t('cmd.targetIoa')} value={ioa} onChange={setIoa} min={0} />

        {point ? (
          <div style={{ opacity: 0.75, fontSize: 12 }}>
            {t('cmd.currentValue', { name: point.name, value: formatValue(point.value) })}
          </div>
        ) : (
          <div style={{ opacity: 0.75, fontSize: 12 }}>{t('cmd.pickHint')}</div>
        )}

        <div className="app-row" style={{ alignItems: 'flex-end' }}>
          {kind === 'YX' ? (
            <SelectField
              id="cb-msp-yx"
              label={t('msp.value')}
              width={140}
              value={yx ? 'on' : 'off'}
              onChange={(v) => setYx(v === 'on')}
              options={[
                { value: 'on', label: 'ON' },
                { value: 'off', label: 'OFF' },
              ]}
            />
          ) : kind === 'YC' ? (
            <NumField id="cb-msp-yc" label={t('msp.value')} value={yc} onChange={setYc} step={0.001} />
          ) : kind === 'YM' ? (
            <NumField id="cb-msp-ym" label={t('msp.value')} value={ym} onChange={setYm} />
          ) : (
            <NumField
              id="cb-msp-step"
              label={t('msp.value')}
              value={step}
              onChange={(v) => setStep(Math.max(-64, Math.min(63, v)))}
              min={-64}
              max={63}
            />
          )}
          <Button kind="primary" disabled={noRun || noIoa || busy} onClick={send}>
            {t('msp.send')}
          </Button>
        </div>

        <div style={{ fontSize: 12, opacity: 0.65 }}>
          {kind === 'YX'
            ? t('msp.kind.yxHint')
            : kind === 'YC'
              ? t('msp.kind.ycHint')
              : kind === 'YM'
                ? t('msp.kind.ymHint')
                : t('msp.kind.stepHint')}
        </div>
      </div>
    </Panel>
  )
}
