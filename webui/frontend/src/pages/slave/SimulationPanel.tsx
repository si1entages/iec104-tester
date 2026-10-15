import { useState } from 'react'

import { InfoCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { Alert, App as AntdApp, Button, Card, InputNumber, Segmented, Space, Tag, Tooltip, Typography } from 'antd'

import { api } from '../../api/endpoints'
import { useCommand, useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'

interface Props {
  disabled?: boolean
  /** 点表当前选中行：scope=selected 时的 YX/YC 模拟目标（类型须匹配） */
  selected?: Point | null
}

type Scope = 'all' | 'selected'

/**
 * 模拟控制（T13）：对接 `POST /api/slave/sim`（后端 `start_simulation` / `stop_simulation`）。
 *
 * 第二批体验改造 ⑤：
 * - YX / YC 各自支持「全部点 / 选中点」两种范围模式（scope）；
 * - YC 取值改为**点表量程内随机**（[min, max] 均匀随机）；点表未声明量程的点
 *   回落「当前值 ± 浮动比例」（yc_change_range 仅对这些点生效）；
 * - `yx_change_rate` 语义为「每周期翻转概率」（0~1，每周期对范围内每点独立判定）。
 * 手动置数走独立的「手动置数」页签（ManualSetPanel），本面板不再有模式单选。
 */
export function SimulationPanel({ disabled = false, selected = null }: Props) {
  const { message } = AntdApp.useApp()
  const { data: status } = useStatusQuery()
  const backendOn = Boolean(status?.simulation)

  const [yxInterval, setYxInterval] = useState(5)
  const [ycInterval, setYcInterval] = useState(2)
  const [yxChangeRate, setYxChangeRate] = useState(0.1)
  const [ycChangeRange, setYcChangeRange] = useState(0.05)
  const [yxScope, setYxScope] = useState<Scope>('all')
  const [ycScope, setYcScope] = useState<Scope>('all')
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const sim = useCommand(api.slave.sim)

  const send = async (on: boolean): Promise<void> => {
    if (on) {
      if (yxScope === 'selected' && selected?.type !== 'YX') {
        message.warning('YX 范围为「选中点」时，请先在点表选中一个 YX 点')
        return
      }
      if (ycScope === 'selected' && selected?.type !== 'YC') {
        message.warning('YC 范围为「选中点」时，请先在点表选中一个 YC 点')
        return
      }
    }
    const result = await sim.mutateAsync({
      enabled: on,
      ...(on
        ? {
            yx_interval: yxInterval,
            yc_interval: ycInterval,
            yx_change_rate: yxChangeRate,
            yc_change_range: ycChangeRange,
            yx_scope: yxScope,
            yc_scope: ycScope,
            ...(yxScope === 'selected' && selected?.type === 'YX' ? { yx_ioas: [selected.ioa] } : {}),
            ...(ycScope === 'selected' && selected?.type === 'YC' ? { yc_ioas: [selected.ioa] } : {}),
          }
        : {}),
    })
    if (result.ok) {
      setLast({ ok: true, text: on ? '已启动自动模拟（start_simulation）' : '已停止模拟（stop_simulation）' })
      message.success(on ? '自动模拟已启动' : '模拟已停止')
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

        <Space wrap>
          <span style={{ fontSize: 12 }}>YX 间隔 (s)</span>
          <InputNumber
            min={0.1}
            max={600}
            step={0.5}
            style={{ width: 130 }}
            value={yxInterval}
            onChange={(v) => setYxInterval(Math.max(0.1, Number(v ?? 5)))}
          />
          <span style={{ fontSize: 12 }}>YC 间隔 (s)</span>
          <InputNumber
            min={0.1}
            max={600}
            step={0.5}
            style={{ width: 130 }}
            value={ycInterval}
            onChange={(v) => setYcInterval(Math.max(0.1, Number(v ?? 2)))}
          />
        </Space>

        <Space wrap>
          <span style={{ fontSize: 12 }}>YX 范围</span>
          <Segmented
            size="small"
            options={[
              { value: 'all', label: '全部点' },
              { value: 'selected', label: '选中点' },
            ]}
            value={yxScope}
            onChange={(v) => setYxScope(v as Scope)}
          />
          <Tooltip title="每周期对范围内的每个 YX 点独立掷一次概率，命中即翻转（0~1）">
            <span style={{ fontSize: 12 }}>
              每周期翻转概率 <InfoCircleOutlined style={{ color: 'inherit', opacity: 0.6 }} />
            </span>
          </Tooltip>
          <InputNumber
            min={0}
            max={1}
            step={0.05}
            style={{ width: 110 }}
            value={yxChangeRate}
            onChange={(v) => setYxChangeRate(Math.max(0, Math.min(1, Number(v ?? 0.1))))}
          />
        </Space>

        <Space wrap>
          <span style={{ fontSize: 12 }}>YC 范围</span>
          <Segmented
            size="small"
            options={[
              { value: 'all', label: '全部点' },
              { value: 'selected', label: '选中点' },
            ]}
            value={ycScope}
            onChange={(v) => setYcScope(v as Scope)}
          />
          <Tooltip title="YC 取值在点表声明的 [min, max] 量程内均匀随机；未声明量程的点按此比例在当前值 ± 比例内浮动">
            <span style={{ fontSize: 12 }}>
              无量程点浮动比例 <InfoCircleOutlined style={{ color: 'inherit', opacity: 0.6 }} />
            </span>
          </Tooltip>
          <InputNumber
            min={0}
            step={0.01}
            style={{ width: 110 }}
            value={ycChangeRange}
            onChange={(v) => setYcChangeRange(Math.max(0, Number(v ?? 0.05)))}
          />
        </Space>

        {selected && (yxScope === 'selected' || ycScope === 'selected') ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            选中点：{selected.type}-{selected.ioa} {selected.name}
            {((yxScope === 'selected' && selected.type !== 'YX') ||
              (ycScope === 'selected' && selected.type !== 'YC')) ? (
              <Typography.Text type="warning" style={{ fontSize: 12 }}>
                （类型与所选范围不匹配，启动前请改选对应类型的点）
              </Typography.Text>
            ) : null}
          </Typography.Text>
        ) : null}

        <Space wrap>
          <Button
            type="primary"
            loading={sim.isPending}
            disabled={noRun}
            onClick={() => void send(!backendOn)}
          >
            {backendOn ? '停止模拟' : '启动模拟'}
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            切到模拟控制页签即为随机模拟；单个点位手动改值请用「手动置数」页签。
          </Typography.Text>
        </Space>
      </Space>
    </Card>
  )
}
