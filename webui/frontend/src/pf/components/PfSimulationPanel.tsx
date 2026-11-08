import { useEffect, useRef, useState } from 'react'

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
import { useCommand, useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { useT } from '../../i18n'
import { BoolField, NumField } from './PfField'

type Scope = 'all' | 'selected'

interface Props {
  disabled?: boolean
  selected: Point | null
}

/** 模拟控制：YX / YC 可独立开启，各自支持全部点/选中点范围。 */
export function PfSimulationPanel({ disabled = false, selected }: Props) {
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
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
          <span>{t('simPanel.title')}</span>
          <Label isCompact color={backendOn ? 'green' : 'grey'}>
            {backendOn ? t('simPanel.running') : t('simPanel.idle')}
          </Label>
          {selected ? (
            <Label isCompact color="blue">
              {t('simPanel.selectedInfo', {
                key: `${selected.type}-${selected.ioa}`,
                name: selected.name,
              })}
            </Label>
          ) : null}
        </Flex>
      </CardTitle>
      <CardBody>
        {disabled ? <Alert isInline variant="info" title={t('simPanel.slaveOff')} /> : null}
        {last ? (
          <Alert
            isInline
            variant={last.ok ? 'success' : 'danger'}
            title={last.text}
            style={{ marginTop: 8 }}
          />
        ) : null}
        <div style={{ fontSize: 12, opacity: 0.7, margin: '8px 0' }}>{t('simPanel.hint')}</div>

        <Form onSubmit={(event) => event.preventDefault()}>
          <Flex gap={{ default: 'gapLg' }} flexWrap={{ default: 'wrap' }}>
            <div style={{ minWidth: 260, flex: 1 }}>
              <BoolField
                id="pf-sim-yx"
                label={t('simPanel.enableYx')}
                value={yxEnabled}
                onChange={setYxEnabled}
              />
              <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
                <NumField
                  id="pf-sim-yx-interval"
                  label={t('simPanel.yxInterval')}
                  value={yxInterval}
                  onChange={(v) => setYxInterval(Math.max(0.1, v))}
                  min={0.1}
                  step={0.5}
                  width={140}
                />
                <NumField
                  id="pf-sim-yx-rate"
                  label={t('simPanel.rate')}
                  value={yxChangeRate}
                  onChange={(v) => setYxChangeRate(Math.max(0, Math.min(1, v)))}
                  min={0}
                  max={1}
                  step={0.01}
                  width={140}
                />
                <FormGroup label={t('simPanel.yxScope')} fieldId="pf-sim-yx-scope" style={{ maxWidth: 160 }}>
                  <FormSelect
                    id="pf-sim-yx-scope"
                    value={yxScope}
                    onChange={(_e, v) => setYxScope(v as Scope)}
                    aria-label={t('simPanel.yxScope')}
                    isDisabled={!yxEnabled}
                  >
                    <FormSelectOption value="all" label={t('simPanel.scope.all')} />
                    <FormSelectOption value="selected" label={t('simPanel.scope.selected')} />
                  </FormSelect>
                </FormGroup>
              </Flex>
              <div style={{ fontSize: 12, opacity: 0.65 }}>{t('simPanel.rateTip')}</div>
            </div>

            <div style={{ minWidth: 260, flex: 1 }}>
              <BoolField
                id="pf-sim-yc"
                label={t('simPanel.enableYc')}
                value={ycEnabled}
                onChange={setYcEnabled}
              />
              <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
                <NumField
                  id="pf-sim-yc-interval"
                  label={t('simPanel.ycInterval')}
                  value={ycInterval}
                  onChange={(v) => setYcInterval(Math.max(0.1, v))}
                  min={0.1}
                  step={0.5}
                  width={140}
                />
                <NumField
                  id="pf-sim-yc-range"
                  label={t('simPanel.range')}
                  value={ycChangeRange}
                  onChange={(v) => setYcChangeRange(Math.max(0, v))}
                  min={0}
                  step={0.01}
                  width={140}
                />
                <FormGroup label={t('simPanel.ycScope')} fieldId="pf-sim-yc-scope" style={{ maxWidth: 160 }}>
                  <FormSelect
                    id="pf-sim-yc-scope"
                    value={ycScope}
                    onChange={(_e, v) => setYcScope(v as Scope)}
                    aria-label={t('simPanel.ycScope')}
                    isDisabled={!ycEnabled}
                  >
                    <FormSelectOption value="all" label={t('simPanel.scope.all')} />
                    <FormSelectOption value="selected" label={t('simPanel.scope.selected')} />
                  </FormSelect>
                </FormGroup>
              </Flex>
              <div style={{ fontSize: 12, opacity: 0.65 }}>{t('simPanel.rangeTip')}</div>
            </div>
          </Flex>

          <ActionGroup>
            <Button
              variant="primary"
              isDisabled={disabled || backendOn || sim.isPending}
              isLoading={sim.isPending}
              onClick={() => void send(true)}
            >
              {t('simPanel.start')}
            </Button>
            <Button
              variant="danger"
              isDisabled={disabled || !backendOn || sim.isPending}
              onClick={() => void send(false)}
            >
              {t('simPanel.stop')}
            </Button>
          </ActionGroup>
        </Form>
      </CardBody>
    </Card>
  )
}
