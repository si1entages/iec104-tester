import { useState } from 'react'

import { ThunderboltOutlined } from '@ant-design/icons'
import { Alert, App as AntdApp, Button, Card, Input, InputNumber, Space, Switch, Tag, Typography } from 'antd'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { OkResponse } from '../../api/types'
import { useT } from '../../i18n'

/**
 * 测试报文注入（T19 补齐旧页能力④）：
 *  - 继保事件 M_EP（POST /api/slave/ep，COT=3 带时标突发）
 *  - 成组单点 M_PS（POST /api/slave/ps，状态位串 1-8 位 0/1）
 * 用于验证主站对非常规来报的处理。
 */
export function TestInjectionPanel({ disabled = false }: { disabled?: boolean }) {
  const t = useT()
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
      const text = r.ok
        ? t('tip.sent', { label })
        : t('tip.failed', { label, error: r.error ?? t('cmd.unknown') })
      setLast({ ok: r.ok, text })
      if (r.ok) message.success(text)
      else message.error(text)
    })
  }

  const sendEp = (): void =>
    run(t('tip.epLabel'), ep.mutateAsync({ ioa: epIoa, event_value: epValue, with_time: epWithTime }))

  const sendPs = (): void => {
    // 与旧页一致：仅接受 0/1，长度 1-8
    const states = psStates
      .split(/[,\s，]+/)
      .map(Number)
      .filter((v) => v === 0 || v === 1)
    if (states.length === 0) {
      message.warning(t('tip.invalidStates'))
      return
    }
    run(t('tip.psLabel', { n: states.length }), ps.mutateAsync({ ioa: psIoa, states }))
  }

  return (
    <Card
      size="small"
      title={
        <Space>
          <ThunderboltOutlined />
          <span>{t('tip.title')}</span>
          <Tag color="purple">{t('tip.cotTag')}</Tag>
        </Space>
      }
      styles={{ body: { maxHeight: 620, overflowY: 'auto' } }}
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        {disabled ? <Alert type="info" showIcon message={t('tip.slaveOff')} /> : null}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {t('tip.hint')}
        </Typography.Text>

        {last ? (
          <Alert type={last.ok ? 'success' : 'error'} showIcon message={last.text} closable onClose={() => setLast(null)} />
        ) : null}

        <Space wrap>
          <span style={{ fontSize: 12 }}>{t('tip.epIoa')}</span>
          <InputNumber min={0} value={epIoa} onChange={(v) => setEpIoa(Number(v ?? 0))} />
          <span style={{ fontSize: 12 }}>{t('tip.epValue')}</span>
          <InputNumber min={0} max={65535} value={epValue} onChange={(v) => setEpValue(Number(v ?? 0))} />
          <span style={{ fontSize: 12 }}>{t('tip.withTime')}</span>
          <Switch size="small" checked={epWithTime} onChange={setEpWithTime} />
          <Button type="primary" disabled={disabled} loading={ep.isPending} onClick={sendEp}>
            {t('tip.sendEp')}
          </Button>
        </Space>

        <Space wrap>
          <span style={{ fontSize: 12 }}>{t('tip.psIoa')}</span>
          <InputNumber min={0} value={psIoa} onChange={(v) => setPsIoa(Number(v ?? 0))} />
          <Input
            style={{ width: 160 }}
            value={psStates}
            placeholder={t('tip.statesPlaceholder')}
            onChange={(e) => setPsStates(e.target.value)}
          />
          <Button type="primary" disabled={disabled} loading={ps.isPending} onClick={sendPs}>
            {t('tip.sendPs')}
          </Button>
        </Space>
      </Space>
    </Card>
  )
}
