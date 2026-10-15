import { useState } from 'react'

import { ThunderboltOutlined } from '@ant-design/icons'
import { Alert, App as AntdApp, Button, Card, Input, InputNumber, Space, Switch, Tag, Typography } from 'antd'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { OkResponse } from '../../api/types'

/**
 * 测试报文注入（T19 补齐旧页能力④）：
 *  - 继保事件 M_EP（POST /api/slave/ep，COT=3 带时标突发）
 *  - 成组单点 M_PS（POST /api/slave/ps，状态位串 1-8 位 0/1）
 * 用于验证主站对非常规来报的处理。
 */
export function TestInjectionPanel({ disabled = false }: { disabled?: boolean }) {
  const { message } = AntdApp.useApp()

  const [epIoa, setEpIoa] = useState(5001)
  const [epValue, setEpValue] = useState(1)
  const [epWithTime, setEpWithTime] = useState(true)
  const [psIoa, setPsIoa] = useState(5101)
  const [psStates, setPsStates] = useState('1,0,1')

  const ep = useCommand(api.slave.ep)
  const ps = useCommand(api.slave.ps)

  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const run = (label: string, task: Promise<OkResponse>): void => {
    void task.then((r) => {
      setLast({ ok: r.ok, text: r.ok ? `${label} 已上送` : `${label} 失败：${r.error ?? '未知错误'}` })
      if (r.ok) message.success(`${label} 已上送`)
      else message.error(`${label} 失败：${r.error ?? '未知错误'}`)
    })
  }

  const sendEp = (): void => run('继保事件 (M_EP)', ep.mutateAsync({ ioa: epIoa, event_value: epValue, with_time: epWithTime }))

  const sendPs = (): void => {
    // 与旧页一致：仅接受 0/1，长度 1-8
    const states = psStates
      .split(/[,\s，]+/)
      .map(Number)
      .filter((v) => v === 0 || v === 1)
    if (states.length === 0) {
      message.warning('状态位须为 0/1，如 1,0,1')
      return
    }
    run(`成组单点 (M_PS, ${states.length} 点)`, ps.mutateAsync({ ioa: psIoa, states }))
  }

  return (
    <Card
      size="small"
      title={
        <Space>
          <ThunderboltOutlined />
          <span>测试报文注入</span>
          <Tag color="purple">COT=3 突发</Tag>
        </Space>
      }
      styles={{ body: { maxHeight: 620, overflowY: 'auto' } }}
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        {disabled ? <Alert type="info" showIcon message="子站未启动，注入不可下发" /> : null}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          用于验证主站对非常规来报（继保事件 / 成组单点）的处理。
        </Typography.Text>

        {last ? (
          <Alert type={last.ok ? 'success' : 'error'} showIcon message={last.text} closable onClose={() => setLast(null)} />
        ) : null}

        <Space wrap>
          <span style={{ fontSize: 12 }}>继保事件 IOA</span>
          <InputNumber min={0} value={epIoa} onChange={(v) => setEpIoa(Number(v ?? 0))} />
          <span style={{ fontSize: 12 }}>事件值</span>
          <InputNumber min={0} max={65535} value={epValue} onChange={(v) => setEpValue(Number(v ?? 0))} />
          <span style={{ fontSize: 12 }}>带时标</span>
          <Switch size="small" checked={epWithTime} onChange={setEpWithTime} />
          <Button type="primary" disabled={disabled} loading={ep.isPending} onClick={sendEp}>
            上送 M_EP
          </Button>
        </Space>

        <Space wrap>
          <span style={{ fontSize: 12 }}>成组单点 IOA</span>
          <InputNumber min={0} value={psIoa} onChange={(v) => setPsIoa(Number(v ?? 0))} />
          <Input
            style={{ width: 160 }}
            value={psStates}
            placeholder="状态位 1,0,1"
            onChange={(e) => setPsStates(e.target.value)}
          />
          <Button type="primary" disabled={disabled} loading={ps.isPending} onClick={sendPs}>
            上送 M_PS
          </Button>
        </Space>
      </Space>
    </Card>
  )
}
