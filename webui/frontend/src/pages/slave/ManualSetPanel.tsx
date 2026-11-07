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
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'
import { formatValue } from '../../lib/format'

/** 可手动置数的点位类别（与 `PointSnapshot.type` 一致） */
type SetKind = 'YX' | 'YC' | 'YM' | 'STEP'

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

function kinds(t: TFn) {
  return [
    { value: 'YX' as SetKind, label: t('msp.kind.yx'), hint: t('msp.kind.yxHint') },
    { value: 'YC' as SetKind, label: t('msp.kind.yc'), hint: t('msp.kind.ycHint') },
    { value: 'YM' as SetKind, label: t('msp.kind.ym'), hint: t('msp.kind.ymHint') },
    { value: 'STEP' as SetKind, label: t('msp.kind.step'), hint: t('msp.kind.stepHint') },
  ]
}

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
  const t = useT()
  const { message } = AntdApp.useApp()
  const kindOptions = kinds(t)

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
    const text = result.ok
      ? t('cmd.done', { label })
      : t('cmd.failed', { label, error: result.error ?? t('cmd.unknown') })
    if (result.ok) {
      setLast({ ok: true, text })
      message.success(text)
    } else {
      setLast({ ok: false, text })
      message.error(text)
    }
  }

  const noRun = disabled
  const noIoa = ioa <= 0

  /** 选中点与当前置数类别不一致时给软提示（不阻断：跨类别置数是合法操作） */
  const mismatch = Boolean(point && point.type !== kind)

  const send = (): void => {
    if (kind === 'YX') void run(t('msp.kind.yx'), yxCmd.mutateAsync({ ioa, value: yx }))
    else if (kind === 'YC') void run(t('msp.kind.yc'), ycCmd.mutateAsync({ ioa, value: yc }))
    else if (kind === 'YM') void run(t('msp.kind.ym'), ymCmd.mutateAsync({ ioa, value: ym }))
    else void run(t('msp.kind.step'), stepCmd.mutateAsync({ ioa, value: step }))
  }

  const valueEditor = () => {
    switch (kind) {
      case 'YX':
        return (
          <Space>
            <span>{t('msp.value')}</span>
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
            prefix={t('msp.value')}
            aria-label={t('msp.value')}
            step={0.001}
            style={{ width: 200 }}
            value={yc}
            onChange={(v) => setYc(Number(v ?? 0))}
          />
        )
      case 'YM':
        return (
          <InputNumber
            prefix={t('msp.value')}
            aria-label={t('msp.value')}
            step={1}
            style={{ width: 200 }}
            value={ym}
            onChange={(v) => setYm(Math.trunc(Number(v ?? 0)))}
          />
        )
      case 'STEP':
        return (
          <InputNumber
            prefix={t('msp.value')}
            aria-label={t('msp.value')}
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
          <span>{t('msp.title')}</span>
          {point ? (
            <Tag color="gold">{t('cmd.selected', { type: point.type, ioa: point.ioa })}</Tag>
          ) : (
            <Tag>{t('cmd.noPoint')}</Tag>
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
          options={kindOptions.map((k) => ({ value: k.value, label: k.label }))}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {kindOptions.find((k) => k.value === kind)?.hint}
        </Typography.Text>

        <Space wrap>
          <InputNumber
            prefix={t('cmd.targetIoa')}
            aria-label={t('cmd.targetIoa')}
            min={0}
            style={{ width: 190 }}
            value={ioa}
            onChange={(v) => setIoa(Number(v ?? 0))}
          />
          {point ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('cmd.currentValue', { name: point.name, value: formatValue(point.value) })}
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('cmd.pickHint')}
            </Typography.Text>
          )}
        </Space>

        {disabled ? <Alert type="info" showIcon message={t('msp.slaveOff')} /> : null}
        {!disabled && noIoa ? (
          <Alert type="warning" showIcon message={t('cmd.needIoa')} />
        ) : null}
        {!disabled && mismatch ? (
          <Alert
            type="warning"
            showIcon
            message={t('msp.mismatch', { point: point?.type ?? '', kind })}
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
            {t('msp.send')}
          </Button>
        </Space>

        <Collapse
          size="small"
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: 'help',
              label: t('msp.help'),
              children: (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  <div>{t('msp.helpLine', { type: 'YX', endpoint: 'POST /api/slave/yx {ioa, value: bool}' })}</div>
                  <div>{t('msp.helpLine', { type: 'YC', endpoint: 'POST /api/slave/yc {ioa, value: number}' })}</div>
                  <div>{t('msp.helpLine', { type: 'YM', endpoint: 'POST /api/slave/ym {ioa, value: int}' })}</div>
                  <div>{t('msp.helpLine', { type: 'STEP', endpoint: 'POST /api/slave/step {ioa, value: -64..63}' })}</div>
                </Typography.Text>
              ),
            },
          ]}
        />
      </Space>
    </Card>
  )
}
