import { useEffect, useState } from 'react'

import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Label,
  Switch,
} from '@patternfly/react-core'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { queryKeys, useSimulationStatusQuery } from '../../api/queries'
import type { NetworkCondition } from '../../api/types'
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'
import { NumField } from './PfField'

const PRESET_KEYS: Record<string, MessageKey> = {
  clean: 'sim.presets.clean',
  poor_wifi: 'sim.presets.poor_wifi',
  congested: 'sim.presets.congested',
  satellite: 'sim.presets.satellite',
  unreliable: 'sim.presets.unreliable',
  intermittent: 'sim.presets.intermittent',
  slow_link: 'sim.presets.slow_link',
  stress: 'sim.presets.stress',
}

interface FormState {
  delay_ms: number
  loss: number
  corrupt: number
  reorder: number
  disconnect: number
  bandwidth_bps: number
  direction: string
}

/** 网络异常模拟（B6）：预设/自定义条件、启停注入、断线、统计。 */
export function PfNetworkSimCard() {
  const t = useT()
  const queryClient = useQueryClient()
  const statusQuery = useSimulationStatusQuery()
  const status = statusQuery.data
  const [preset, setPreset] = useState('')
  const [form, setForm] = useState<FormState | null>(null)
  const [disconnectSec, setDisconnectSec] = useState(5)
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    const c = statusQuery.data?.condition
    if (form || !c) return
    setForm({
      delay_ms: c.delay_ms,
      loss: Math.round(c.loss_rate * 1000) / 10,
      corrupt: Math.round(c.corrupt_rate * 1000) / 10,
      reorder: Math.round(c.reorder_rate * 1000) / 10,
      disconnect: Math.round(c.disconnect_rate * 1000) / 10,
      bandwidth_bps: c.bandwidth_bps,
      direction: c.direction,
    })
  }, [statusQuery.data, form])

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.simulationStatus() })
  }
  const setMutation = useMutation({ mutationFn: api.simulation.set, onSettled: invalidate })
  const resetMutation = useMutation({ mutationFn: api.simulation.reset, onSettled: invalidate })
  const disconnectMutation = useMutation({ mutationFn: api.simulation.disconnect, onSettled: invalidate })

  const report = async (promise: Promise<{ ok: boolean; error?: string }>): Promise<void> => {
    try {
      const result = await promise
      setLast(
        result.ok
          ? { ok: true, text: t('common.ok') }
          : { ok: false, text: result.error ?? t('common.failed') },
      )
    } catch (e) {
      setLast({ ok: false, text: (e as Error).message })
    }
  }

  const applyCustom = (): void => {
    if (!form) return
    const condition: Partial<NetworkCondition> = {
      delay_ms: form.delay_ms,
      loss_rate: form.loss / 100,
      corrupt_rate: form.corrupt / 100,
      reorder_rate: form.reorder / 100,
      disconnect_rate: form.disconnect / 100,
      bandwidth_bps: form.bandwidth_bps,
      direction: form.direction as NetworkCondition['direction'],
    }
    void report(setMutation.mutateAsync({ enabled: status?.enabled ?? false, condition }))
  }

  const statsLine = (prefix: 'rx' | 'tx'): string => {
    const stats = status?.stats
    if (!stats) return ''
    const n = (key: string): number => Number((stats as Record<string, unknown>)[`${prefix}_${key}`] ?? 0)
    const label = prefix === 'rx' ? t('sim.rx') : t('sim.tx')
    return `${label} ${t('sim.total')} ${n('total')} · ${t('sim.lost')} ${n('dropped')} · ${t('sim.dup')} ${n('duplicated')} · ${t('sim.reordered')} ${n('reordered')} · ${t('sim.corruptShort')} ${n('corrupted')}`
  }

  return (
    <Card isCompact>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          <span>{t('sim.title')}</span>
          <Label isCompact color={status?.enabled ? 'green' : 'grey'}>
            {status?.enabled ? t('sim.enabled') : t('sim.disabled')}
          </Label>
          <Label isCompact color={status?.installed ? 'blue' : 'grey'}>
            {status?.installed ? t('sim.installed') : t('sim.notInstalled')}
          </Label>
          {status?.describe && status.describe !== '(none)' ? <Label isCompact>{status.describe}</Label> : null}
        </Flex>
      </CardTitle>
      <CardBody>
        {last ? (
          <Alert
            isInline
            variant={last.ok ? 'success' : 'danger'}
            title={last.text}
            style={{ marginBottom: 8 }}
          />
        ) : null}

        <Flex gap={{ default: 'gapMd' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
          <FormGroup label={t('sim.injecting')} fieldId="pf-sim-enable">
            <Switch
              id="pf-sim-enable"
              aria-label={t('sim.injecting')}
              isChecked={status?.enabled ?? false}
              onChange={(_event, checked) =>
                void report(setMutation.mutateAsync({ enabled: checked }))
              }
            />
          </FormGroup>
          <div style={{ width: 220 }}>
            <FormSelect
              value={preset}
              onChange={(_e, v) => setPreset(v)}
              aria-label={t('sim.preset')}
            >
              <FormSelectOption value="" label={t('sim.preset')} />
              {Object.entries(PRESET_KEYS).map(([value, key]) => (
                <FormSelectOption key={value} value={value} label={t(key)} />
              ))}
            </FormSelect>
          </div>
          <Button
            variant="secondary"
            isDisabled={!preset || setMutation.isPending}
            onClick={() => void report(setMutation.mutateAsync({ enabled: status?.enabled ?? false, preset }))}
          >
            {t('sim.applyPreset')}
          </Button>
          <NumField
            id="pf-sim-disc-sec"
            label={`${t('sim.disconnect')} (s)`}
            value={disconnectSec}
            onChange={setDisconnectSec}
            min={1}
            max={600}
            width={150}
          />
          <Button
            variant="danger"
            isDisabled={disconnectMutation.isPending}
            onClick={() => void report(disconnectMutation.mutateAsync(disconnectSec))}
          >
            {t('sim.disconnect')}
          </Button>
          <Button
            variant="link"
            isDisabled={resetMutation.isPending}
            onClick={() => void report(resetMutation.mutateAsync())}
          >
            {t('sim.resetStats')}
          </Button>
        </Flex>

        {form ? (
          <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }} style={{ marginTop: 8 }}>
            <NumField id="pf-sim-delay" label={t('sim.delay')} value={form.delay_ms} onChange={(v) => setForm({ ...form, delay_ms: v })} min={0} width={130} />
            <NumField id="pf-sim-loss" label={t('sim.loss')} value={form.loss} onChange={(v) => setForm({ ...form, loss: v })} min={0} max={100} width={120} />
            <NumField id="pf-sim-corrupt" label={t('sim.corrupt')} value={form.corrupt} onChange={(v) => setForm({ ...form, corrupt: v })} min={0} max={100} width={120} />
            <NumField id="pf-sim-reorder" label={t('sim.reorder')} value={form.reorder} onChange={(v) => setForm({ ...form, reorder: v })} min={0} max={100} width={120} />
            <NumField id="pf-sim-disc-rate" label={t('sim.disconnectRate')} value={form.disconnect} onChange={(v) => setForm({ ...form, disconnect: v })} min={0} max={100} width={140} />
            <NumField id="pf-sim-bw" label={t('sim.bandwidth')} value={form.bandwidth_bps} onChange={(v) => setForm({ ...form, bandwidth_bps: v })} min={0} width={150} />
            <FormGroup label={t('common.direction')} fieldId="pf-sim-direction" style={{ maxWidth: 140 }}>
              <FormSelect
                id="pf-sim-direction"
                value={form.direction}
                onChange={(_e, v) => setForm({ ...form, direction: v })}
                aria-label={t('common.direction')}
              >
                <FormSelectOption value="both" label={t('sim.both')} />
                <FormSelectOption value="rx" label={t('sim.rxOnly')} />
                <FormSelectOption value="tx" label={t('sim.txOnly')} />
              </FormSelect>
            </FormGroup>
            <ActionGroup>
              <Button variant="secondary" isDisabled={setMutation.isPending} onClick={applyCustom}>
                {t('sim.applyCustom')}
              </Button>
            </ActionGroup>
          </Flex>
        ) : null}

        <div style={{ marginTop: 10, fontSize: 12, opacity: 0.7 }}>
          {status?.installed && status.stats
            ? `${statsLine('rx')} ｜ ${statsLine('tx')} ｜ ${t('sim.disconnects')} ${status.stats.disconnects ?? 0}`
            : t('sim.notInstalledHint')}
        </div>
      </CardBody>
    </Card>
  )
}
