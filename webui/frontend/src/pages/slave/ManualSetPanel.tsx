import { useEffect, useState } from 'react'

import { EditOutlined } from '@ant-design/icons'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Collapse,
  Divider,
  InputNumber,
  Segmented,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { OkResponse, Point } from '../../api/types'
import { formatValue } from '../../lib/format'

/** 可手动置数的点位类别（与 `PointSnapshot.type` 一致） */
type SetKind = 'YX' | 'YC' | 'YM' | 'STEP'

const KINDS: { value: SetKind; label: string; hint: string }[] = [
  { value: 'YX', label: '遥信 YX', hint: '单点遥信，ON / OFF（M_SP_NA_1）' },
  { value: 'YC', label: '遥测 YC', hint: '短浮点遥测（M_ME_NC_1）' },
  { value: 'YM', label: '电度 YM', hint: '累计量 / 电度（整数）' },
  { value: 'STEP', label: '步位置 STEP', hint: '步位置信息，取值 -64..63（M_ST_TB_1）' },
]

interface Props {
  /** 点表选中行；用于带入 IOA 与类别 */
  point: Point | null
  disabled?: boolean
}

/**
 * 手动置数面板（T13）。
 *
 * 覆盖四类子站点位的**手动**置数（区别于模拟控制的自动变化）：
 * - YX 遥信单点：`POST /api/slave/yx` `{ioa, value: bool}`
 * - YC 遥测短浮点：`POST /api/slave/yc` `{ioa, value: number}`
 * - YM 电度：`POST /api/slave/ym` `{ioa, value: int}`
 * - STEP 步位置：`POST /api/slave/step` `{ioa, value: -64..63}`（T09 建模）
 */
export function ManualSetPanel({ point, disabled = false }: Props) {
  const { message } = AntdApp.useApp()

  const [kind, setKind] = useState<SetKind>('YX')
  const [ioa, setIoa] = useState<number>(0)
  const [yx, setYx] = useState(true)
  const [yc, setYc] = useState<number>(0)
  const [ym, setYm] = useState<number>(0)
  const [step, setStep] = useState<number>(0)
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  // 选中行 → 面板目标 IOA / 类别自动跟随（点表里就是 YX/YC/YM/STEP 四类）
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
    if (result.ok) {
      setLast({ ok: true, text: `${label} 已下发` })
      message.success(`${label} 已下发`)
    } else {
      setLast({ ok: false, text: `${label} 失败：${result.error ?? '未知错误'}` })
      message.error(`${label} 失败：${result.error ?? '未知错误'}`)
    }
  }

  const noRun = disabled
  const noIoa = ioa <= 0

  /** 选中点与当前置数类别不一致时给软提示（不阻断：跨类别置数是合法操作） */
  const mismatch = Boolean(point && point.type !== kind)

  const send = (): void => {
    if (kind === 'YX') void run('遥信置数', yxCmd.mutateAsync({ ioa, value: yx }))
    else if (kind === 'YC') void run('遥测置数', ycCmd.mutateAsync({ ioa, value: yc }))
    else if (kind === 'YM') void run('电度置数', ymCmd.mutateAsync({ ioa, value: ym }))
    else void run('步位置置数', stepCmd.mutateAsync({ ioa, value: step }))
  }

  const valueEditor = () => {
    switch (kind) {
      case 'YX':
        return (
          <Space>
            <span>值</span>
            <Switch
              checkedChildren="ON"
              unCheckedChildren="OFF"
              checked={yx}
              onChange={setYx}
            />
          </Space>
        )
      case 'YC':
        return (
          <InputNumber
            prefix="值"
            step={0.001}
            style={{ width: 200 }}
            value={yc}
            onChange={(v) => setYc(Number(v ?? 0))}
          />
        )
      case 'YM':
        return (
          <InputNumber
            prefix="值"
            step={1}
            style={{ width: 200 }}
            value={ym}
            onChange={(v) => setYm(Math.trunc(Number(v ?? 0)))}
          />
        )
      case 'STEP':
        return (
          <InputNumber
            prefix="值"
            min={-64}
            max={63}
            step={1}
            style={{ width: 200 }}
            value={step}
            onChange={(v) => setStep(Math.max(-64, Math.min(63, Math.trunc(Number(v ?? 0)))))}
          />
        )
      default:
        return null
    }
  }

  return (
    <Card
      size="small"
      title={
        <Space>
          <EditOutlined />
          <span>手动置数</span>
          {point ? (
            <Tag color="gold">
              已选 {point.type}-{point.ioa}
            </Tag>
          ) : (
            <Tag>未选点</Tag>
          )}
        </Space>
      }
      styles={{ body: { maxHeight: 620, overflowY: 'auto' } }}
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Segmented
          block
          value={kind}
          onChange={(v) => setKind(v as SetKind)}
          options={KINDS.map((k) => ({ value: k.value, label: k.label }))}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {KINDS.find((k) => k.value === kind)?.hint}
        </Typography.Text>

        <Space wrap>
          <InputNumber
            prefix="目标 IOA"
            min={0}
            style={{ width: 190 }}
            value={ioa}
            onChange={(v) => setIoa(Number(v ?? 0))}
          />
          {point ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {point.name} · 当前值 {formatValue(point.value)}
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              在左侧点表单击一行即可带入
            </Typography.Text>
          )}
        </Space>

        {disabled ? <Alert type="info" showIcon message="子站未启动，置数不可下发" /> : null}
        {!disabled && noIoa ? <Alert type="warning" showIcon message="请先选择点位或填写目标 IOA" /> : null}
        {!disabled && mismatch ? (
          <Alert
            type="warning"
            showIcon
            message={`选中点是 ${point?.type}，当前按 ${kind} 置数——两者类别不一致，请确认`}
          />
        ) : null}
        {last ? (
          <Alert
            type={last.ok ? 'success' : 'error'}
            showIcon
            message={last.text}
            closable
            onClose={() => setLast(null)}
          />
        ) : null}

        <Divider style={{ margin: '4px 0' }} />
        <Space wrap>
          {valueEditor()}
          <Button type="primary" loading={busy} disabled={noRun || noIoa} onClick={send}>
            下发置数
          </Button>
        </Space>

        <Collapse
          size="small"
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: 'help',
              label: '各类别对应的 REST 端点',
              children: (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  <div>YX：POST /api/slave/yx {'{ioa, value: bool}'}</div>
                  <div>YC：POST /api/slave/yc {'{ioa, value: number}'}</div>
                  <div>YM：POST /api/slave/ym {'{ioa, value: int}'}</div>
                  <div>STEP：POST /api/slave/step {'{ioa, value: -64..63}'}</div>
                </Typography.Text>
              ),
            },
          ]}
        />
      </Space>
    </Card>
  )
}
