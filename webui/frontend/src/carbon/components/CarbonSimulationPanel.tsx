import { useEffect, useRef, useState } from 'react'

import { Button, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand, useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { useT } from '../../i18n'
import { BoolField, Note, NumField, Panel, SelectField } from './ui'

type Scope = 'all' | 'selected'

interface Props {
  disabled?: boolean
  selected: Point | null
}

/** 模拟控制：YX / YC 可独立开启，各自支持全部点/选中点范围。 */
export function CarbonSimulationPanel({ disabled = false, selected }: Props) {
  const t = useT()
  const { data: status } = useStatusQuery()
  const backendOn = Boolean(status?.simulation)

  const [yxEnabled, setYxEnabled] = useState(true)
  const [ycEnabled, setYcEnabled] = useState(true)
  const [yxInterval, setYxInterval] = useState(5)
  const [ycInterval, setYcInterval] = useState(2)
  const [yxChangeRate, setYxChangeRate] = useState(0.1)
  const [ycChangeRange, setYcChangeRange] = useState(0.05)
  const [yxScope, setYxScope] = useState<Scope>('all')
  const [ycScope, setYcScope] = useState<Scope>('all')
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const synced = useRef(false)
  useEffect(() => {
    if (!backendOn) {
      synced.current = false
      return
    }
    if (synced.current) return
    synced.current = true
    if (typeof status?.simulation_yx === 'boolean') setYxEnabled(status.simulation_yx)
    if (typeof status?.simulation_yc === 'boolean') setYcEnabled(status.simulation_yc)
  }, [backendOn, status?.simulation_yx, status?.simulation_yc])

  const sim = useCommand(api.slave.sim)

  const send = async (on: boolean): Promise<void> => {
    if (on && !yxEnabled && !ycEnabled) {
      setLast({ ok: false, text: t('simPanel.needOneType') })
      return
    }
    if (on && yxEnabled && yxScope === 'selected' && selected?.type !== 'YX') {
      setLast({ ok: false, text: t('simPanel.needYx') })
      return
    }
    if (on && ycEnabled && ycScope === 'selected' && selected?.type !== 'YC') {
      setLast({ ok: false, text: t('simPanel.needYc') })
      return
    }
    const result = await sim.mutateAsync({
      enabled: on,
      ...(on
        ? {
            yx_enabled: yxEnabled,
            yc_enabled: ycEnabled,
            yx_interval: yxInterval,
            yc_interval: ycInterval,
            yx_change_rate: yxChangeRate,
            yc_change_range: ycChangeRange,
            yx_scope: yxScope,
            yc_scope: ycScope,
            ...(yxEnabled && yxScope === 'selected' && selected?.type === 'YX'
              ? { yx_ioas: [selected.ioa] }
              : {}),
            ...(ycEnabled && ycScope === 'selected' && selected?.type === 'YC'
              ? { yc_ioas: [selected.ioa] }
              : {}),
          }
        : {}),
    })
    setLast(
      result.ok
        ? { ok: true, text: on ? t('simPanel.started') : t('simPanel.stopped') }
        : { ok: false, text: t('simPanel.failed', { error: result.error ?? t('cmd.unknown') }) },
    )
  }

  return (
    <Panel
      title={
        <span className="app-row">
          {t('simPanel.title')}
          <Tag size="sm" type={backendOn ? 'green' : 'gray'}>
            {backendOn ? t('simPanel.running') : t('simPanel.idle')}
          </Tag>
          {selected ? (
            <Tag size="sm" type="blue">
              {t('simPanel.selectedInfo', {
                key: `${selected.type}-${selected.ioa}`,
                name: selected.name,
              })}
            </Tag>
          ) : null}
        </span>
      }
    >
      {disabled ? <Note kind="info" title={t('simPanel.slaveOff')} /> : null}
      {last ? <Note kind={last.ok ? 'success' : 'error'} title={last.text} style={{ marginTop: 8 }} /> : null}
      <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', margin: '8px 0' }}>{t('simPanel.hint')}</div>

      <div className="app-row" style={{ alignItems: 'flex-start', gap: '2.5rem' }}>
        <div style={{ minWidth: 260, flex: 1 }}>
          <BoolField id="cb-sim-yx" label={t('simPanel.enableYx')} value={yxEnabled} onChange={setYxEnabled} />
          <div className="app-row" style={{ alignItems: 'flex-end', marginTop: 8 }}>
            <NumField
              id="cb-sim-yx-interval"
              label={t('simPanel.yxInterval')}
              value={yxInterval}
              onChange={(v) => setYxInterval(Math.max(0.1, v))}
              min={0.1}
              step={0.5}
              width={140}
            />
            <NumField
              id="cb-sim-yx-rate"
              label={t('simPanel.rate')}
              value={yxChangeRate}
              onChange={(v) => setYxChangeRate(Math.max(0, Math.min(1, v)))}
              min={0}
              max={1}
              step={0.01}
              width={140}
            />
            <SelectField
              id="cb-sim-yx-scope"
              label={t('simPanel.yxScope')}
              width={160}
              value={yxScope}
              onChange={(v) => setYxScope(v as Scope)}
              disabled={!yxEnabled}
              options={[
                { value: 'all', label: t('simPanel.scope.all') },
                { value: 'selected', label: t('simPanel.scope.selected') },
              ]}
            />
          </div>
          <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>{t('simPanel.rateTip')}</div>
        </div>

        <div style={{ minWidth: 260, flex: 1 }}>
          <BoolField id="cb-sim-yc" label={t('simPanel.enableYc')} value={ycEnabled} onChange={setYcEnabled} />
          <div className="app-row" style={{ alignItems: 'flex-end', marginTop: 8 }}>
            <NumField
              id="cb-sim-yc-interval"
              label={t('simPanel.ycInterval')}
              value={ycInterval}
              onChange={(v) => setYcInterval(Math.max(0.1, v))}
              min={0.1}
              step={0.5}
              width={140}
            />
            <NumField
              id="cb-sim-yc-range"
              label={t('simPanel.range')}
              value={ycChangeRange}
              onChange={(v) => setYcChangeRange(Math.max(0, v))}
              min={0}
              step={0.01}
              width={140}
            />
            <SelectField
              id="cb-sim-yc-scope"
              label={t('simPanel.ycScope')}
              width={160}
              value={ycScope}
              onChange={(v) => setYcScope(v as Scope)}
              disabled={!ycEnabled}
              options={[
                { value: 'all', label: t('simPanel.scope.all') },
                { value: 'selected', label: t('simPanel.scope.selected') },
              ]}
            />
          </div>
          <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>{t('simPanel.rangeTip')}</div>
        </div>
      </div>

      <div className="app-row" style={{ marginTop: 12 }}>
        <Button
          kind="primary"
          disabled={disabled || backendOn || sim.isPending}
          onClick={() => void send(true)}
        >
          {t('simPanel.start')}
        </Button>
        <Button
          kind="danger"
          disabled={disabled || !backendOn || sim.isPending}
          onClick={() => void send(false)}
        >
          {t('simPanel.stop')}
        </Button>
      </div>
    </Panel>
  )
}
