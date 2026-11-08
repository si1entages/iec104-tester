import { useEffect, useState } from 'react'

import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  Form,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Label,
} from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { OkResponse, Point } from '../../api/types'
import { useT } from '../../i18n'
import { formatValue } from '../../lib/format'
import { NumField } from './PfField'

type SetKind = 'YX' | 'YC' | 'YM' | 'STEP'

interface Props {
  point: Point | null
  disabled?: boolean
}

/** 子站手动置数：YX/YC/YM/STEP 四类，目标 IOA 跟随选中行。 */
export function PfManualSetPanel({ point, disabled = false }: Props) {
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
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
          <span>{t('msp.title')}</span>
          {point ? (
            <Label isCompact color="blue">
              {t('cmd.selected', { type: point.type, ioa: point.ioa })}
            </Label>
          ) : (
            <Label isCompact>{t('cmd.noPoint')}</Label>
          )}
        </Flex>
      </CardTitle>
      <CardBody>
        {disabled ? <Alert isInline variant="info" title={t('msp.slaveOff')} /> : null}
        {!disabled && noIoa ? (
          <Alert isInline variant="warning" title={t('cmd.needIoa')} style={{ marginTop: 8 }} />
        ) : null}
        {last ? (
          <Alert
            isInline
            variant={last.ok ? 'success' : 'danger'}
            title={last.text}
            style={{ marginTop: 8 }}
          />
        ) : null}
        {mismatch ? (
          <div style={{ fontSize: 12, opacity: 0.75, marginTop: 8 }}>{t('msp.mismatch')}</div>
        ) : null}

        <Form onSubmit={(event) => event.preventDefault()} style={{ marginTop: 12 }}>
          <FormGroup label={t('common.type')} fieldId="pf-msp-kind" style={{ maxWidth: 240 }}>
            <FormSelect
              id="pf-msp-kind"
              value={kind}
              onChange={(_e, v) => setKind(v as SetKind)}
              aria-label={t('common.type')}
            >
              <FormSelectOption value="YX" label={t('msp.kind.yx')} />
              <FormSelectOption value="YC" label={t('msp.kind.yc')} />
              <FormSelectOption value="YM" label={t('msp.kind.ym')} />
              <FormSelectOption value="STEP" label={t('msp.kind.step')} />
            </FormSelect>
          </FormGroup>

          <NumField id="pf-msp-ioa" label={t('cmd.targetIoa')} value={ioa} onChange={setIoa} min={0} />

          {point ? (
            <div style={{ opacity: 0.75, fontSize: 12, marginBottom: 8 }}>
              {t('cmd.currentValue', { name: point.name, value: formatValue(point.value) })}
            </div>
          ) : (
            <div style={{ opacity: 0.75, fontSize: 12, marginBottom: 8 }}>{t('cmd.pickHint')}</div>
          )}

          <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
            {kind === 'YX' ? (
              <FormGroup label={t('msp.value')} fieldId="pf-msp-yx">
                <FormSelect
                  id="pf-msp-yx"
                  value={yx ? 'on' : 'off'}
                  onChange={(_e, v) => setYx(v === 'on')}
                  aria-label={t('msp.value')}
                >
                  <FormSelectOption value="on" label="ON" />
                  <FormSelectOption value="off" label="OFF" />
                </FormSelect>
              </FormGroup>
            ) : kind === 'YC' ? (
              <NumField id="pf-msp-yc" label={t('msp.value')} value={yc} onChange={setYc} step={0.001} />
            ) : kind === 'YM' ? (
              <NumField id="pf-msp-ym" label={t('msp.value')} value={ym} onChange={setYm} />
            ) : (
              <NumField
                id="pf-msp-step"
                label={t('msp.value')}
                value={step}
                onChange={(v) => setStep(Math.max(-64, Math.min(63, v)))}
                min={-64}
                max={63}
              />
            )}
            <ActionGroup>
              <Button variant="primary" isDisabled={noRun || noIoa || busy} onClick={send}>
                {t('msp.send')}
              </Button>
            </ActionGroup>
          </Flex>

          <div style={{ fontSize: 12, opacity: 0.65, marginTop: 8 }}>
            {kind === 'YX'
              ? t('msp.kind.yxHint')
              : kind === 'YC'
                ? t('msp.kind.ycHint')
                : kind === 'YM'
                  ? t('msp.kind.ymHint')
                  : t('msp.kind.stepHint')}
          </div>
        </Form>
      </CardBody>
    </Card>
  )
}
