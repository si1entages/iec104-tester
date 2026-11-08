import { useEffect, useState } from 'react'

import {
  Alert,
  Button,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Radio,
  Label,
} from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { Point, SetpointKind } from '../../api/types'
import { useT } from '../../i18n'
import { formatValue } from '../../lib/format'
import { directCommandKind, isDoubleCommand, setpointKindOf } from '../../lib/pointCommand'
import { NumField } from './PfField'

interface Props {
  point: Point | null
  disabled?: boolean
  onClose: () => void
}

/** 点表双击值直接下发命令的确认弹窗（PF 版）：YK / 设点 / 升降。 */
export function PfPointCommandDialog({ point, disabled = false, onClose }: Props) {
  const t = useT()
  const [ykOn, setYkOn] = useState<'on' | 'off'>('on')
  const [spKind, setSpKind] = useState<SetpointKind>('short_float')
  const [spValue, setSpValue] = useState(0)
  const [stepUp, setStepUp] = useState(true)
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!point) return
    setYkOn('on')
    setSpKind(setpointKindOf(point))
    setSpValue(typeof point.value === 'number' ? point.value : 0)
    setStepUp(true)
    setLast(null)
  }, [point])

  const yk = useCommand(api.master.yk)
  const setpoint = useCommand(api.master.setpoint)
  const step = useCommand(api.master.step)
  const busy = yk.isPending || setpoint.isPending || step.isPending

  const kind = point ? directCommandKind(point) : null
  if (!point || !kind) return null

  const double = isDoubleCommand(point)
  const dangerous = kind === 'yk' && ykOn === 'off'

  const send = async (): Promise<void> => {
    try {
      if (kind === 'yk') {
        const r = await yk.mutateAsync({
          ioa: point.ioa,
          state: ykOn === 'on' ? 1 : 0,
          select: false,
          double,
          with_time: false,
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
        })
        setLast(
          r.ok
            ? { ok: true, text: t('pcd.spSent', { value: spValue }) }
            : { ok: false, text: t('pcd.spFailed', { error: r.error ?? t('cmd.unknown') }) },
        )
      } else {
        const r = await step.mutateAsync({ ioa: point.ioa, state: stepUp ? 2 : 1, select: false })
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
    <Modal isOpen variant="small" onClose={onClose} aria-labelledby="pf-pcd-title">
      <ModalHeader
        title={kind === 'yk' ? t('pcd.title.yk') : kind === 'setpoint' ? t('pcd.title.sp') : t('pcd.title.step')}
        labelId="pf-pcd-title"
      />
      <ModalBody>
      <div style={{ marginBottom: 8 }}>
        <Label isCompact color="blue">
          {point.type}-{point.ioa}
        </Label>
      </div>
      <DescriptionList isHorizontal columnModifier={{ default: '2Col' }}>
        <DescriptionListGroup>
          <DescriptionListTerm>{t('pcd.name')}</DescriptionListTerm>
          <DescriptionListDescription>{point.name || '—'}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>{t('pcd.current')}</DescriptionListTerm>
          <DescriptionListDescription>{formatValue(point.value)}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>{t('pcd.pointType')}</DescriptionListTerm>
          <DescriptionListDescription>
            {point.type}
            {point.sbo ? (
              <Label isCompact color="orange" style={{ marginInlineStart: 8 }}>
                {t('pcd.sboTag')}
              </Label>
            ) : null}
          </DescriptionListDescription>
        </DescriptionListGroup>
      </DescriptionList>

      {disabled ? <Alert isInline variant="info" title={t('cmd.engineOff')} style={{ marginTop: 12 }} /> : null}
      {last ? (
        <Alert
          isInline
          variant={last.ok ? 'success' : 'danger'}
          title={last.text}
          style={{ marginTop: 12 }}
        />
      ) : null}

      {kind === 'yk' ? (
        <FormGroup label={t('pcd.direction')} fieldId="pf-pcd-dir" style={{ marginTop: 12 }}>
          <div style={{ display: 'flex', gap: 16 }}>
            <Radio
              id="pf-pcd-on"
              name="pf-pcd-dir"
              label={t('pcd.on')}
              isChecked={ykOn === 'on'}
              onChange={() => setYkOn('on')}
            />
            <Radio
              id="pf-pcd-off"
              name="pf-pcd-dir"
              label={t('pcd.off')}
              isChecked={ykOn === 'off'}
              onChange={() => setYkOn('off')}
            />
          </div>
        </FormGroup>
      ) : null}

      {kind === 'setpoint' ? (
        <div style={{ marginTop: 12 }}>
          <FormGroup label={t('cmd.value')} fieldId="pf-pcd-spkind">
            <FormSelect
              id="pf-pcd-spkind"
              value={spKind}
              onChange={(_e, v) => setSpKind(v as SetpointKind)}
              aria-label={t('cmd.value')}
            >
              <FormSelectOption value="short_float" label={t('cmd.sp.shortFloat')} />
              <FormSelectOption value="normalized" label={t('cmd.sp.normalized')} />
              <FormSelectOption value="scaled" label={t('cmd.sp.scaled')} />
            </FormSelect>
          </FormGroup>
          <NumField id="pf-pcd-spval" label={t('pcd.target')} value={spValue} onChange={setSpValue} step={0.001} />
        </div>
      ) : null}

      {kind === 'step' ? (
        <FormGroup label={t('pcd.direction')} fieldId="pf-pcd-step" style={{ marginTop: 12 }}>
          <div style={{ display: 'flex', gap: 16 }}>
            <Radio id="pf-pcd-up" name="pf-pcd-step" label={t('pcd.up')} isChecked={stepUp} onChange={() => setStepUp(true)} />
            <Radio id="pf-pcd-down" name="pf-pcd-step" label={t('pcd.down')} isChecked={!stepUp} onChange={() => setStepUp(false)} />
          </div>
        </FormGroup>
      ) : null}

      {point.sbo ? (
        <Alert
          isInline
          variant="warning"
          title={t('pcd.sboTitle')}
          style={{ marginTop: 12 }}
        >
          {t('pcd.sboDesc')}
        </Alert>
      ) : null}

      <div style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>{t('pcd.hint')}</div>

      </ModalBody>
      <ModalFooter>
        <Button variant="link" isDisabled={busy} onClick={onClose}>
          {t('pcd.cancel')}
        </Button>
        <Button
          variant="primary"
          isDanger={dangerous}
          isDisabled={disabled || busy}
          isLoading={busy}
          onClick={() => void send()}
        >
          {t('pcd.ok')}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
