import { useEffect, useState } from 'react'

import { Checkbox, Modal, RadioButton, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { Point, SetpointKind } from '../../api/types'
import { useT } from '../../i18n'
import { formatValue } from '../../lib/format'
import { directCommandKind, isDoubleCommand, setpointKindOf } from '../../lib/pointCommand'
import { KvList, Note, NumField, SelectField } from './ui'

interface Props {
  point: Point | null
  disabled?: boolean
  onClose: () => void
}

/** 点表双击值直接下发命令的确认弹窗（Carbon 版）：YK / 设点 / 升降。 */
export function CarbonPointCommandDialog({ point, disabled = false, onClose }: Props) {
  const t = useT()
  const [ykOn, setYkOn] = useState<'on' | 'off'>('on')
  const [spKind, setSpKind] = useState<SetpointKind>('short_float')
  const [spValue, setSpValue] = useState(0)
  const [stepUp, setStepUp] = useState(true)
  const [force, setForce] = useState(false)
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!point) return
    setYkOn('on')
    setSpKind(setpointKindOf(point))
    setSpValue(typeof point.value === 'number' ? point.value : 0)
    setStepUp(true)
    setForce(false)
    setLast(null)
  }, [point])

  const yk = useCommand(api.master.yk)
  const setpoint = useCommand(api.master.setpoint)
  const step = useCommand(api.master.step)
  const busy = yk.isPending || setpoint.isPending || step.isPending

  const interlocks = point?.interlock ?? []
  const hasInterlock = interlocks.length > 0
  const asText = interlocks
    .map((c) => `${c.ioa}${c.label ? `（${c.label}）` : ''} → ${c.value ? t('pcd.on') : t('pcd.off')}`)
    .join('；')
  const kind = point ? directCommandKind(point) : null
  const double = point ? isDoubleCommand(point) : false
  const dangerous = (kind === 'yk' && ykOn === 'off') || force

  const send = async (): Promise<void> => {
    if (!point) return
    try {
      if (kind === 'yk') {
        const r = await yk.mutateAsync({
          ioa: point.ioa,
          state: ykOn === 'on' ? 1 : 0,
          select: false,
          double,
          with_time: false,
          force,
        })
        setLast(
          r.ok
            ? { ok: true, text: t('pcd.ykSent', { dir: ykOn === 'on' ? t('pcd.on') : t('pcd.off') }) }
            : { ok: false, text: t('pcd.ykFailed', { error: r.error ?? t('cmd.unknown') }) },
        )
      } else if (kind === 'setpoint') {
        const r = await setpoint.mutateAsync({
          ioa: point.ioa,
          value: spValue,
          kind: spKind,
          select: false,
          with_time: false,
          force,
        })
        setLast(
          r.ok
            ? { ok: true, text: t('pcd.spSent', { value: spValue }) }
            : { ok: false, text: t('pcd.spFailed', { error: r.error ?? t('cmd.unknown') }) },
        )
      } else {
        const r = await step.mutateAsync({
          ioa: point.ioa, state: stepUp ? 2 : 1, select: false, force,
        })
        setLast(
          r.ok
            ? { ok: true, text: t('pcd.stepSent', { dir: stepUp ? t('pcd.up') : t('pcd.down') }) }
            : { ok: false, text: t('pcd.stepFailed', { error: r.error ?? t('cmd.unknown') }) },
        )
      }
    } catch (e) {
      setLast({ ok: false, text: t('pcd.sendFailed', { error: (e as Error).message }) })
    }
  }

  return (
    <Modal
      open={Boolean(point && kind)}
      modalHeading={
        kind === 'yk' ? t('pcd.title.yk') : kind === 'setpoint' ? t('pcd.title.sp') : t('pcd.title.step')
      }
      size="sm"
      primaryButtonText={t('pcd.ok')}
      secondaryButtonText={t('pcd.cancel')}
      primaryButtonDisabled={disabled || busy}
      onRequestSubmit={() => void send()}
      onRequestClose={onClose}
      onSecondarySubmit={onClose}
      danger={dangerous}
    >
      {point && kind ? (
        <>
          <div style={{ marginBottom: 8 }}>
            <Tag size="sm" type="blue">
              {point.type}-{point.ioa}
            </Tag>
          </div>
          <KvList
            items={[
              { term: t('pcd.name'), value: point.name || '—' },
              { term: t('pcd.current'), value: formatValue(point.value) },
              {
                term: t('pcd.pointType'),
                value: (
                  <span className="app-row">
                    {point.type}
                    {point.sbo ? (
                      <Tag size="sm" type="magenta">
                        {t('pcd.sboTag')}
                      </Tag>
                    ) : null}
                  </span>
                ),
              },
            ]}
          />

          {disabled ? <Note kind="info" title={t('cmd.engineOff')} style={{ marginTop: 12 }} /> : null}
          {last ? <Note kind={last.ok ? 'success' : 'error'} title={last.text} style={{ marginTop: 12 }} /> : null}

          {kind === 'yk' ? (
            <div role="radiogroup" aria-label={t('pcd.direction')} style={{ display: 'flex', gap: 16, marginTop: 12 }}>
              <RadioButton
                id="cb-pcd-on"
                name="cb-pcd-dir"
                labelText={t('pcd.on')}
                checked={ykOn === 'on'}
                onChange={() => setYkOn('on')}
              />
              <RadioButton
                id="cb-pcd-off"
                name="cb-pcd-dir"
                labelText={t('pcd.off')}
                checked={ykOn === 'off'}
                onChange={() => setYkOn('off')}
              />
            </div>
          ) : null}

          {kind === 'setpoint' ? (
            <div style={{ marginTop: 12 }}>
              <SelectField
                id="cb-pcd-spkind"
                label={t('cmd.value')}
                value={spKind}
                onChange={(v) => setSpKind(v as SetpointKind)}
                options={[
                  { value: 'short_float', label: t('cmd.sp.shortFloat') },
                  { value: 'normalized', label: t('cmd.sp.normalized') },
                  { value: 'scaled', label: t('cmd.sp.scaled') },
                ]}
              />
              <NumField id="cb-pcd-spval" label={t('pcd.target')} value={spValue} onChange={setSpValue} step={0.001} />
            </div>
          ) : null}

          {kind === 'step' ? (
            <div role="radiogroup" aria-label={t('pcd.direction')} style={{ display: 'flex', gap: 16, marginTop: 12 }}>
              <RadioButton
                id="cb-pcd-up"
                name="cb-pcd-step"
                labelText={t('pcd.up')}
                checked={stepUp}
                onChange={() => setStepUp(true)}
              />
              <RadioButton
                id="cb-pcd-down"
                name="cb-pcd-step"
                labelText={t('pcd.down')}
                checked={!stepUp}
                onChange={() => setStepUp(false)}
              />
            </div>
          ) : null}

          {hasInterlock ? (
            <>
              <div style={{ marginTop: 12 }}>
                <Tag size="sm" type="magenta">{t('pcd.interlockTag')}</Tag>
              </div>
              <Note kind="warning" title={t('pcd.interlockTitle')} style={{ marginTop: 8 }}>
                {t('pcd.interlockDesc', { cond: asText })}
              </Note>
              <div style={{ marginTop: 8 }}>
                <Checkbox
                  id="cb-pcd-force"
                  labelText={t('pcd.forceLabel')}
                  checked={force}
                  onChange={(_e, checked) => setForce(Boolean(checked))}
                />
                <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>{t('pcd.forceDesc')}</div>
              </div>
            </>
          ) : null}

          {point.sbo ? <Note kind="warning" title={t('pcd.sboTitle')} style={{ marginTop: 12 }}>{t('pcd.sboDesc')}</Note> : null}

          <div style={{ marginTop: 12, fontSize: 12, color: 'var(--cds-text-secondary)' }}>{t('pcd.hint')}</div>
        </>
      ) : null}
    </Modal>
  )
}
