import { useState } from 'react'

import { ThunderboltOutlined } from '@ant-design/icons'
import { Alert, App as AntdApp, Button, Card, InputNumber, Radio, Space, Tag, Typography } from 'antd'

import { api } from '../../api/endpoints'
import { useCommand, useStatusQuery } from '../../api/queries'

/** 置数方式：manual = 不自动变化（用「手动置数」）；auto = 随机自动变化 */
type SimMode = 'manual' | 'auto'

interface Props {
  disabled?: boolean
}

/**
 * 模拟控制（T13）：对接 `POST /api/slave/sim`（后端 `start_simulation` / `stop_simulation`）。
 *
 * 两种置数方式二选一：
 * - **随机变化**：开启自动模拟 → `start_simulation`，按 YX/YC 各自间隔随机变化
 *   （可调变化率 / 幅度）
 * - **手动**：`stop_simulation`，改用左侧「手动置数」逐个下发 YX / YC / YM / STEP
 *
 * 旧原生子站页只有「自动变化」一个开关（`#sim-on`），这里把变化率/幅度/间隔
 * 一并暴露（后端 `start_simulation` 本就支持）。
 */
export function SimulationPanel({ disabled = false }: Props) {
  const { message } = AntdApp.useApp()
  const { data: status } = useStatusQuery()
  const backendOn = Boolean(status?.simulation)

  // mode 为用户显式选择（null = 尚未选择，跟随后端当前状态）
  const [mode, setMode] = useState<SimMode | null>(null)
  const [yxInterval, setYxInterval] = useState(5)
  const [ycInterval, setYcInterval] = useState(2)
  const [yxChangeRate, setYxChangeRate] = useState(0.1)
  const [ycChangeRange, setYcChangeRange] = useState(0.05)
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const sim = useCommand(api.slave.sim)

  const effectiveMode: SimMode = mode ?? (backendOn ? 'auto' : 'manual')
  const wantOn = effectiveMode === 'auto'
  // 目标状态与后端当前状态一致 → 无需下发
  const settled = wantOn === backendOn

  const send = async (on: boolean): Promise<void> => {
    const result = await sim.mutateAsync({
      enabled: on,
      ...(on
        ? {
            yx_interval: yxInterval,
            yc_interval: ycInterval,
            yx_change_rate: yxChangeRate,
            yc_change_range: ycChangeRange,
          }
        : {}),
    })
    if (result.ok) {
      setLast({ ok: true, text: on ? '已启动自动模拟（start_simulation）' : '已切换到手动（stop_simulation）' })
      message.success(on ? '自动模拟已启动' : '已切换到手动置数')
    } else {
      setLast({ ok: false, text: `模拟控制失败：${result.error ?? '未知错误'}` })
      message.error(`模拟控制失败：${result.error ?? '未知错误'}`)
    }
  }

  const noRun = disabled

  return (
    <Card
      size="small"
      title={
        <Space>
          <ThunderboltOutlined />
          <span>模拟控制</span>
          <Tag color={backendOn ? 'green' : 'default'}>{backendOn ? '模拟中' : '未模拟'}</Tag>
        </Space>
      }
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        {disabled ? <Alert type="info" showIcon message="子站未启动，模拟不可用" /> : null}
        {last ? (
          <Alert
            type={last.ok ? 'success' : 'error'}
            showIcon
            message={last.text}
            closable
            onClose={() => setLast(null)}
          />
        ) : null}

        <Radio.Group
          value={effectiveMode}
          onChange={(e) => setMode(e.target.value as SimMode)}
          disabled={noRun}
        >
          <Radio value="manual">手动置数（不自动变化）</Radio>
          <Radio value="auto">随机变化（自动模拟）</Radio>
        </Radio.Group>

        {effectiveMode === 'auto' ? (
          <Space wrap>
            <span style={{ fontSize: 12 }}>YX 间隔 (s)</span>
            <InputNumber
              min={0.1}
              max={600}
              step={0.5}
              style={{ width: 150 }}
              value={yxInterval}
              onChange={(v) => setYxInterval(Math.max(0.1, Number(v ?? 5)))}
            />
            <span style={{ fontSize: 12 }}>YC 间隔 (s)</span>
            <InputNumber
              min={0.1}
              max={600}
              step={0.5}
              style={{ width: 150 }}
              value={ycInterval}
              onChange={(v) => setYcInterval(Math.max(0.1, Number(v ?? 2)))}
            />
            <span style={{ fontSize: 12 }}>YX 变化率</span>
            <InputNumber
              min={0}
              max={1}
              step={0.05}
              style={{ width: 130 }}
              value={yxChangeRate}
              onChange={(v) => setYxChangeRate(Math.max(0, Math.min(1, Number(v ?? 0.1))))}
            />
            <span style={{ fontSize: 12 }}>YC 变化幅度</span>
            <InputNumber
              min={0}
              step={0.01}
              style={{ width: 130 }}
              value={ycChangeRange}
              onChange={(v) => setYcChangeRange(Math.max(0, Number(v ?? 0.05)))}
            />
          </Space>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            手动模式：不自动变化，用「手动置数」逐个下发 YX / YC / YM / STEP。
          </Typography.Text>
        )}

        <Space wrap>
          <Button
            type="primary"
            loading={sim.isPending}
            disabled={noRun || settled}
            onClick={() => void send(wantOn)}
          >
            {wantOn ? '启动模拟' : '停止模拟'}
          </Button>
          <Typography.Text type={settled ? 'secondary' : 'warning'} style={{ fontSize: 12 }}>
            {settled
              ? '所选方式与后端当前状态一致，无需下发'
              : wantOn
                ? '将调用 start_simulation'
                : '将调用 stop_simulation'}
          </Typography.Text>
        </Space>
      </Space>
    </Card>
  )
}

