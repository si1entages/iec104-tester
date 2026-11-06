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

const PRESET_LABELS: Record<string, string> = {
  clean: '正常网络（无异常）',
  poor_wifi: '差 WiFi（延迟+丢包+乱序）',
  congested: '网络拥塞',
  satellite: '卫星链路（高延迟）',
  unreliable: '高丢包+损坏',
  intermittent: '间歇性断线',
  slow_link: '低带宽（1KB/s）',
  stress: '综合压力测试',
}

const DIRECTION_OPTIONS = [
  { value: 'both', label: '双向' },
  { value: 'rx', label: '仅接收 RX' },
  { value: 'tx', label: '仅发送 TX' },
]

interface FormState {
  delay_ms: number
  loss: number // 百分比
  corrupt: number
  reorder: number
  disconnect: number
  bandwidth_bps: number
  direction: string
}

function statsLine(label: string, s: SimStats, prefix: 'rx' | 'tx'): string {
  const n = (k: string): number => s[`${prefix}_${k}`] ?? 0
  return `${label} 总 ${n('total')} · 丢 ${n('dropped')} · 重 ${n('duplicated')} · 乱 ${n('reordered')} · 坏 ${n('corrupted')}`
}

/**
 * 网络异常模拟卡片（B6）：传输层延迟/丢包/重复/损坏/乱序/断线/限速注入。
 *
 * 开关控制是否注入；预设/自定义只修改条件。引擎未启动时也可启用——主站/子站
 * 启动时会自动安装，引擎停止时自动卸载并保留启用状态。
 */
export function NetworkSimCard() {
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
      if (result.ok) message.success('已下发')
      else message.error(result.error ?? '操作失败')
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

  return (
    <Card
      size="small"
      title={
        <Space size={4} wrap>
          <ThunderboltOutlined />
          <span>网络异常模拟</span>
          <Tag color={status?.enabled ? 'green' : 'default'}>
            {status?.enabled ? '已启用' : '已停用'}
          </Tag>
          <Tag color={status?.installed ? 'blue' : 'default'}>
            {status?.installed ? '已安装' : '引擎未启动'}
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
          重置统计
        </Button>
      }
    >
      <Space wrap>
        <Tooltip title="开启后立即注入；引擎未启动时保存启用状态，启动时自动安装">
          <Switch
            checked={status?.enabled ?? false}
            checkedChildren="注入中"
            unCheckedChildren="未启用"
            loading={setMutation.isPending}
            onChange={(checked) =>
              void report(setMutation.mutateAsync({ enabled: checked }))
            }
          />
        </Tooltip>
        <Select
          style={{ width: 250 }}
          allowClear
          placeholder="预设条件"
          value={preset}
          options={Object.entries(PRESET_LABELS).map(([value, label]) => ({ value, label }))}
          onChange={(v) => setPreset(v)}
        />
        <Button onClick={applyPreset} disabled={!preset} loading={setMutation.isPending}>
          应用预设
        </Button>
        <Tooltip title="手动触发一次断线（需引擎已启动并已安装模拟）">
          <Space.Compact>
            <InputNumber
              min={1}
              max={600}
              value={disconnectSec}
              onChange={(v) => setDisconnectSec(Number(v ?? 5))}
              addonAfter="秒"
              style={{ width: 140 }}
            />
            <Button
              icon={<DisconnectOutlined />}
              loading={disconnectMutation.isPending}
              onClick={() => void report(disconnectMutation.mutateAsync(disconnectSec))}
            >
              断线
            </Button>
          </Space.Compact>
        </Tooltip>
      </Space>

      {form ? (
        <Space wrap style={{ marginTop: 12 }}>
          <InputNumber
            prefix="延迟ms"
            min={0}
            value={form.delay_ms}
            onChange={(v) => setForm({ ...form, delay_ms: Number(v ?? 0) })}
          />
          <InputNumber
            prefix="丢包%"
            min={0}
            max={100}
            value={form.loss}
            onChange={(v) => setForm({ ...form, loss: Number(v ?? 0) })}
          />
          <InputNumber
            prefix="损坏%"
            min={0}
            max={100}
            value={form.corrupt}
            onChange={(v) => setForm({ ...form, corrupt: Number(v ?? 0) })}
          />
          <InputNumber
            prefix="乱序%"
            min={0}
            max={100}
            value={form.reorder}
            onChange={(v) => setForm({ ...form, reorder: Number(v ?? 0) })}
          />
          <InputNumber
            prefix="断线%"
            min={0}
            max={100}
            value={form.disconnect}
            onChange={(v) => setForm({ ...form, disconnect: Number(v ?? 0) })}
          />
          <InputNumber
            prefix="限速B/s"
            min={0}
            value={form.bandwidth_bps}
            onChange={(v) => setForm({ ...form, bandwidth_bps: Number(v ?? 0) })}
          />
          <Select
            style={{ width: 130 }}
            value={form.direction}
            options={DIRECTION_OPTIONS}
            onChange={(v) => setForm({ ...form, direction: v })}
          />
          <Button onClick={applyCustom} loading={setMutation.isPending}>
            应用自定义
          </Button>
        </Space>
      ) : null}

      <div style={{ marginTop: 10 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {status?.installed && status.stats
            ? `${statsLine('RX', status.stats, 'rx')} ｜ ${statsLine('TX', status.stats, 'tx')} ｜ 断线 ${
                status.stats.disconnects ?? 0
              }`
            : '未安装到引擎：先启用，再在主站/子站页连接或启动监听（启动时自动安装）。'}
        </Typography.Text>
      </div>
    </Card>
  )
}
