import { useState } from 'react'

import { Button } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { OkResponse } from '../../api/types'
import { useT } from '../../i18n'
import { Note, NumField, Panel, SelectField, TextField } from './ui'

interface Props {
  disabled?: boolean
}

/** 测试注入：继保事件 M_EP（COT=3 突发）与成组单点 M_PS（1–8 位状态位串）。 */
export function CarbonTestInjectionPanel({ disabled = false }: Props) {
  const t = useT()
  const [epIoa, setEpIoa] = useState(5001)
  const [epValue, setEpValue] = useState('1')
  const [epWithTime, setEpWithTime] = useState(true)
  const [psIoa, setPsIoa] = useState(5101)
  const [psStates, setPsStates] = useState('1,0,1')
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const ep = useCommand(api.slave.ep)
  const ps = useCommand(api.slave.ps)

  const run = async (label: string, task: Promise<OkResponse>): Promise<void> => {
    const result = await task
    setLast(
      result.ok
        ? { ok: true, text: t('tip.sent', { label }) }
        : { ok: false, text: t('tip.failed', { label, error: result.error ?? t('cmd.unknown') }) },
    )
  }

  const sendEp = (): void => {
    void run(
      t('tip.epLabel'),
      ep.mutateAsync({ ioa: epIoa, event_value: Number(epValue) || 0, with_time: epWithTime }),
    )
  }

  const sendPs = (): void => {
    // 与旧页一致：仅接受 0/1，长度 1–8
    const states = psStates
      .split(/[,\s，]+/)
      .map(Number)
      .filter((v) => v === 0 || v === 1)
    if (states.length === 0 || states.length > 8) {
      setLast({ ok: false, text: t('tip.invalidStates') })
      return
    }
    void run(t('tip.psLabel', { n: states.length }), ps.mutateAsync({ ioa: psIoa, states }))
  }

  return (
    <Panel title={t('tip.title')}>
      {disabled ? <Note kind="info" title={t('tip.slaveOff')} /> : null}
      {last ? <Note kind={last.ok ? 'success' : 'error'} title={last.text} style={{ marginTop: 8 }} /> : null}
      <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', margin: '8px 0' }}>{t('tip.hint')}</div>

      <div className="app-row" style={{ alignItems: 'flex-start', gap: '2.5rem' }}>
        <div style={{ minWidth: 280, flex: 1 }} className="app-stack">
          <NumField id="cb-ep-ioa" label={t('tip.epIoa')} value={epIoa} onChange={setEpIoa} min={0} />
          <div className="app-row" style={{ alignItems: 'flex-end' }}>
            <SelectField
              id="cb-ep-value"
              label={t('tip.epValue')}
              width={140}
              value={epValue}
              onChange={setEpValue}
              options={[
                { value: '1', label: '1' },
                { value: '2', label: '2' },
                { value: '3', label: '3' },
              ]}
            />
            <SelectField
              id="cb-ep-time"
              label={t('tip.withTime')}
              width={140}
              value={epWithTime ? 'yes' : 'no'}
              onChange={(v) => setEpWithTime(v === 'yes')}
              options={[
                { value: 'yes', label: t('conn.on') },
                { value: 'no', label: t('conn.off') },
              ]}
            />
          </div>
          <div>
            <Button kind="primary" disabled={disabled || ep.isPending} onClick={sendEp}>
              {t('tip.sendEp')}
            </Button>
          </div>
        </div>

        <div style={{ minWidth: 280, flex: 1 }} className="app-stack">
          <NumField id="cb-ps-ioa" label={t('tip.psIoa')} value={psIoa} onChange={setPsIoa} min={0} />
          <TextField
            id="cb-ps-states"
            label={t('tip.psLabel', { n: psStates.split(',').filter(Boolean).length })}
            value={psStates}
            onChange={setPsStates}
            placeholder={t('tip.statesPlaceholder')}
          />
          <div>
            <Button kind="primary" disabled={disabled || ps.isPending} onClick={sendPs}>
              {t('tip.sendPs')}
            </Button>
          </div>
        </div>
      </div>
    </Panel>
  )
}
