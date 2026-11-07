import { useEffect, useState } from 'react'

import {
  Alert,
  App as AntdApp,
  Descriptions,
  InputNumber,
  Modal,
  Radio,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { Point, SetpointKind } from '../../api/types'
import { formatValue } from '../../lib/format'
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'
import {
  buildSetpointRequest,
  buildStepRequest,
  buildYkRequest,
  directCommandKind,
  isDoubleCommand,
  setpointKindOf,
} from '../../lib/pointCommand'

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

function setpointKinds(t: TFn) {
  return [
    { value: 'short_float' as SetpointKind, label: t('cmd.sp.shortFloat') },
    { value: 'normalized' as SetpointKind, label: t('cmd.sp.normalized') },
    { value: 'scaled' as SetpointKind, label: t('cmd.sp.scaled') },
  ]
}

interface Props {
  /** 双击的值单元格对应点位；null 时弹窗关闭 */
  point: Point | null
  /** 引擎未运行时禁止下发（弹窗仍展示，说明原因） */
  disabled?: boolean
  onClose: () => void
}

/**
 * 定义表「双击值直接发命令」确认弹窗（T21）。
 *
 * 双击只负责**带入点位并预填命令参数**，真正下发前必须在这里二次确认：
 * - YK：单/双命令与分/合方向；SBO 点位由后端自动先选择、确认后再执行
 * - YC：设点类型与目标值
 * - STEP：升/降一步
 *
 * 弹窗不直接复用右侧命令面板的本地状态，避免「双击值」受面板里上一次
 * 编辑的 IOA/参数影响；命令参数完全由当前点位与本次输入决定。
 */
export function PointCommandDialog({ point, disabled = false, onClose }: Props) {
  const t = useT()
  const { message } = AntdApp.useApp()

  const [ykOn, setYkOn] = useState<'on' | 'off'>('on')
  const [spKind, setSpKind] = useState<SetpointKind>('short_float')
  const [spValue, setSpValue] = useState<number>(0)
  const [stepUp, setStepUp] = useState(true)

  // 换点位时重置本次输入；同一 IOA 的实时值刷新不打断用户编辑
  useEffect(() => {
    if (!point) return
    setYkOn('on')
    setSpKind(setpointKindOf(point))
    setSpValue(typeof point.value === 'number' ? point.value : 0)
    setStepUp(true)
  }, [point?.ioa, point?.type, point?.subtype])

  const yk = useCommand(api.master.yk)
  const setpoint = useCommand(api.master.setpoint)
  const step = useCommand(api.master.step)
  const busy = yk.isPending || setpoint.isPending || step.isPending

  const kind = point ? directCommandKind(point) : null

  const handleOk = async (): Promise<void> => {
    if (!point || !kind) return
    try {
      if (kind === 'yk') {
        const on = ykOn === 'on'
        const result = await yk.mutateAsync(buildYkRequest(point, on))
        if (result.ok) {
          message.success(t('pcd.ykSent', { dir: on ? t('pcd.on') : t('pcd.off') }))
          onClose()
        } else {
          message.error(
            t('pcd.ykFailed', { error: result.error ?? t('cmd.unknown') }),
          )
        }
        return
      }
      if (kind === 'setpoint') {
        const result = await setpoint.mutateAsync(buildSetpointRequest(point, spValue, spKind))
        if (result.ok) {
          message.success(t('pcd.spSent', { value: spValue }))
          onClose()
        } else {
          message.error(
            t('pcd.spFailed', { error: result.error ?? t('cmd.unknown') }),
          )
        }
        return
      }
      const result = await step.mutateAsync(buildStepRequest(point, stepUp))
      if (result.ok) {
        message.success(t('pcd.stepSent', { dir: stepUp ? t('pcd.up') : t('pcd.down') }))
        onClose()
      } else {
        message.error(
          t('pcd.stepFailed', { error: result.error ?? t('cmd.unknown') }),
        )
      }
    } catch (err) {
      const text = err instanceof Error ? err.message : String(err)
      message.error(t('pcd.sendFailed', { error: text }))
    }
  }

  if (!point || !kind) return null

  const double = isDoubleCommand(point)
  const titleText =
    kind === 'yk'
      ? t('pcd.title.yk')
      : kind === 'setpoint'
        ? t('pcd.title.sp')
        : t('pcd.title.step')
  const commandSummary =
    kind === 'yk'
      ? t('pcd.summary.yk', {
          kind: double ? t('cmd.double') : t('cmd.single'),
          dir: ykOn === 'on' ? t('pcd.on') : t('pcd.off'),
        })
      : kind === 'setpoint'
        ? t('pcd.summary.sp', { kind: spKind, value: spValue })
        : stepUp
          ? t('pcd.up')
          : t('pcd.down')

  return (
    <Modal
      open
      title={
        <Space wrap>
          <span>{titleText}</span>
          <Tag color="gold">
            {point.type}-{point.ioa}
          </Tag>
        </Space>
      }
      okText={t('pcd.ok')}
      cancelText={t('pcd.cancel')}
      okButtonProps={{ danger: true, disabled }}
      cancelButtonProps={{ disabled: busy }}
      confirmLoading={busy}
      mask={{ closable: !busy }}
      closable={!busy}
      keyboard={!busy}
      onOk={() => void handleOk()}
      onCancel={onClose}
      width={540}
    >
      <Space orientation="vertical" size={12} style={{ width: '100%' }}>
        <Descriptions
          size="small"
          column={2}
          items={[
            { key: 'name', label: t('pcd.name'), children: point.name || '—' },
            { key: 'value', label: t('pcd.current'), children: formatValue(point.value) },
            {
              key: 'type',
              label: t('pcd.pointType'),
              children: point.subtype ? `${point.type} / ${point.subtype}` : point.type,
            },
            { key: 'cmd', label: t('pcd.command'), children: commandSummary },
          ]}
        />

        {kind === 'yk' ? (
          <>
            <Space wrap>
              <Typography.Text>{t('pcd.direction')}</Typography.Text>
              <Radio.Group
                value={ykOn}
                onChange={(e) => setYkOn(e.target.value as 'on' | 'off')}
                optionType="button"
                buttonStyle="solid"
              >
                <Radio.Button value="on">{t('pcd.on')}</Radio.Button>
                <Radio.Button value="off">{t('pcd.off')}</Radio.Button>
              </Radio.Group>
              <Tag color={double ? 'purple' : 'blue'}>
                {double ? t('cmd.double') : t('cmd.single')}
              </Tag>
              {point.sbo ? <Tag color="orange">{t('pcd.sboTag')}</Tag> : null}
            </Space>
            {point.sbo ? (
              <Alert
                type="warning"
                showIcon
                title={t('pcd.sboTitle')}
                description={t('pcd.sboDesc')}
              />
            ) : null}
          </>
        ) : null}

        {kind === 'setpoint' ? (
          <Space wrap>
            <Select
              style={{ width: 260 }}
              value={spKind}
              options={setpointKinds(t)}
              onChange={setSpKind}
            />
            <InputNumber
              prefix={t('pcd.target')}
              value={spValue}
              onChange={(v) => setSpValue(Number(v ?? 0))}
              style={{ width: 160 }}
            />
          </Space>
        ) : null}

        {kind === 'step' ? (
          <Space wrap>
            <Typography.Text>{t('pcd.direction')}</Typography.Text>
            <Radio.Group
              value={stepUp ? 'up' : 'down'}
              onChange={(e) => setStepUp(e.target.value === 'up')}
              optionType="button"
              buttonStyle="solid"
            >
              <Radio.Button value="up">{t('cmd.step.up')}</Radio.Button>
              <Radio.Button value="down">{t('cmd.step.down')}</Radio.Button>
            </Radio.Group>
          </Space>
        ) : null}

        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {t('pcd.hint')}
        </Typography.Text>
        {disabled ? (
          <Alert type="info" showIcon title={t('cmd.engineOff')} />
        ) : null}
      </Space>
    </Modal>
  )
}
