import { useEffect, useState } from 'react'

import { DisconnectOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  App as AntdApp,
  Button,
  Card,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from 'antd'

import { api } from '../api/endpoints'
import { queryKeys, useSimulationStatusQuery } from '../api/queries'
import type { NetworkCondition, SimStats } from '../api/types'
import { useT } from '../i18n'
import type { MessageKey } from '../i18n'

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
  loss: number // 百分比
  corrupt: number
  reorder: number
  disconnect: number
  bandwidth_bps: number
  direction: string
}

/**
 * 网络异常模拟卡片（B6）：传输层延迟/丢包/重复/损坏/乱序/断线/限速注入。
 *
 * 开关控制是否注入；预设/自定义只修改条件。引擎未启动时也可启用——主站/子站
 * 启动时会自动安装，引擎停止时自动卸载并保留启用状态。
 */
export function NetworkSimCard() {
  const t = useT()
  const { message } = AntdApp.useApp()
  const queryClient = useQueryClient()
  const statusQuery = useSimulationStatusQuery()
  const status = statusQuery.data
  const [preset, setPreset] = useState<string | undefined>(undefined)
  const [form, setForm] = useState<FormState | null>(null)
  const [disconnectSec, setDisconnectSec] = useState(5)

  // 自定义表单只在首次拿到完整状态时回填一次（避免轮询覆盖用户正在编辑的值）；
  // 响应缺少 condition（旧后端/契约不一致）时保持空表单，不崩溃。
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
    void queryClient.invalidateQueries({ queryKey: queryKeys.simulationStatus })
  }
  const setMutation = useMutation({ mutationFn: api.simulation.set, onSettled: invalidate })
  const resetMutation = useMutation({ mutationFn: api.simulation.reset, onSettled: invalidate })
  const disconnectMutation = useMutation({
    mutationFn: api.simulation.disconnect,
    onSettled: invalidate,
  })

  const report = async (promise: Promise<{ ok: boolean; error?: string }>): Promise<void> => {
    try {
      const result = await promise
      if (result.ok) message.success(t('common.ok'))
      else message.error(result.error ?? t('common.failed'))
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const applyPreset = (): void => {
    if (!preset) return
    void report(setMutation.mutateAsync({ enabled: status?.enabled ?? false, preset }))
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
      direction: form.direction,
    }
    void report(setMutation.mutateAsync({ enabled: status?.enabled ?? false, condition }))
  }

  const statsLine = (prefix: 'rx' | 'tx', stats: SimStats): string => {
    const n = (key: string): number => stats[`${prefix}_${key}`] ?? 0
    const label = prefix === 'rx' ? t('sim.rx') : t('sim.tx')
    return `${label} ${t('sim.total')} ${n('total')} · ${t('sim.lost')} ${n('dropped')} · ${t('sim.dup')} ${n('duplicated')} · ${t('sim.reordered')} ${n('reordered')} · ${t('sim.corruptShort')} ${n('corrupted')}`
  }

  const directionOptions = [
    { value: 'both', label: t('sim.both') },
    { value: 'rx', label: t('sim.rxOnly') },
    { value: 'tx', label: t('sim.txOnly') },
  ]

  return (
    <Card
      size="small"
      title={
        <Space size={4} wrap>
          <ThunderboltOutlined />
          <span>{t('sim.title')}</span>
          <Tag color={status?.enabled ? 'green' : 'default'}>
            {status?.enabled ? t('sim.enabled') : t('sim.disabled')}
          </Tag>
          <Tag color={status?.installed ? 'blue' : 'default'}>
            {status?.installed ? t('sim.installed') : t('sim.notInstalled')}
          </Tag>
          {status?.describe && status.describe !== '(none)' ? <Tag>{status.describe}</Tag> : null}
        </Space>
      }
      extra={
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={resetMutation.isPending}
          onClick={() => void report(resetMutation.mutateAsync())}
        >
          {t('sim.resetStats')}
        </Button>
      }
    >
      <Space wrap>
        <Tooltip title={t('sim.switchTip')}>
          <Switch
            checked={status?.enabled ?? false}
            checkedChildren={t('sim.injecting')}
            unCheckedChildren={t('sim.notEnabled')}
            loading={setMutation.isPending}
            onChange={(checked) =>
              void report(setMutation.mutateAsync({ enabled: checked }))
            }
          />
        </Tooltip>
        <Select
          style={{ width: 250 }}
          allowClear
          placeholder={t('sim.preset')}
          value={preset}
          options={Object.entries(PRESET_KEYS).map(([value, key]) => ({
            value,
            label: t(key),
          }))}
          onChange={(v) => setPreset(v)}
        />
        <Button onClick={applyPreset} disabled={!preset} loading={setMutation.isPending}>
          {t('sim.applyPreset')}
        </Button>
        <Tooltip title={t('sim.disconnectTip')}>
          <Space.Compact>
            <InputNumber
              min={1}
              max={600}
              value={disconnectSec}
              onChange={(v) => setDisconnectSec(Number(v ?? 5))}
              addonAfter={t('sim.seconds')}
              style={{ width: 140 }}
            />
            <Button
              icon={<DisconnectOutlined />}
              loading={disconnectMutation.isPending}
              onClick={() => void report(disconnectMutation.mutateAsync(disconnectSec))}
            >
              {t('sim.disconnect')}
            </Button>
          </Space.Compact>
        </Tooltip>
      </Space>

      {form ? (
        <Space wrap style={{ marginTop: 12 }}>
          <InputNumber
            prefix={t('sim.delay')}
            min={0}
            value={form.delay_ms}
            onChange={(v) => setForm({ ...form, delay_ms: Number(v ?? 0) })}
          />
          <InputNumber
            prefix={t('sim.loss')}
            min={0}
            max={100}
            value={form.loss}
            onChange={(v) => setForm({ ...form, loss: Number(v ?? 0) })}
          />
          <InputNumber
            prefix={t('sim.corrupt')}
            min={0}
            max={100}
            value={form.corrupt}
            onChange={(v) => setForm({ ...form, corrupt: Number(v ?? 0) })}
          />
          <InputNumber
            prefix={t('sim.reorder')}
            min={0}
            max={100}
            value={form.reorder}
            onChange={(v) => setForm({ ...form, reorder: Number(v ?? 0) })}
          />
          <InputNumber
            prefix={t('sim.disconnectRate')}
            min={0}
            max={100}
            value={form.disconnect}
            onChange={(v) => setForm({ ...form, disconnect: Number(v ?? 0) })}
          />
          <InputNumber
            prefix={t('sim.bandwidth')}
            min={0}
            value={form.bandwidth_bps}
            onChange={(v) => setForm({ ...form, bandwidth_bps: Number(v ?? 0) })}
          />
          <Select
            style={{ width: 130 }}
            value={form.direction}
            options={directionOptions}
            onChange={(v) => setForm({ ...form, direction: v })}
          />
          <Button onClick={applyCustom} loading={setMutation.isPending}>
            {t('sim.applyCustom')}
          </Button>
        </Space>
      ) : null}

      <div style={{ marginTop: 10 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {status?.installed && status.stats
            ? `${statsLine('rx', status.stats)} ｜ ${statsLine('tx', status.stats)} ｜ ${t('sim.disconnects')} ${
                status.stats.disconnects ?? 0
              }`
            : t('sim.notInstalledHint')}
        </Typography.Text>
      </div>
    </Card>
  )
}
