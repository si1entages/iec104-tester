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
import {
  buildSetpointRequest,
  buildStepRequest,
  buildYkRequest,
  directCommandKind,
  isDoubleCommand,
  setpointKindOf,
} from '../../lib/pointCommand'

const SETPOINT_KINDS: { value: SetpointKind; label: string }[] = [
  { value: 'short_float', label: 'short_float 短浮点 (C_SE_NC_1)' },
  { value: 'normalized', label: 'normalized 归一化 (C_SE_NA_1)' },
  { value: 'scaled', label: 'scaled 标度化 (C_SE_NB_1)' },
]

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
          message.success(`遥控命令已下发（${on ? '合闸 ON' : '分闸 OFF'}）`)
          onClose()
        } else {
          message.error(`遥控命令失败：${result.error ?? '未知错误'}`)
        }
        return
      }
      if (kind === 'setpoint') {
        const result = await setpoint.mutateAsync(buildSetpointRequest(point, spValue, spKind))
        if (result.ok) {
          message.success(`设点命令已下发（目标值 ${spValue}）`)
          onClose()
        } else {
          message.error(`设点命令失败：${result.error ?? '未知错误'}`)
        }
        return
      }
      const result = await step.mutateAsync(buildStepRequest(point, stepUp))
      if (result.ok) {
        message.success(`升降命令已下发（${stepUp ? '升一步' : '降一步'}）`)
        onClose()
      } else {
        message.error(`升降命令失败：${result.error ?? '未知错误'}`)
      }
    } catch (err) {
      const text = err instanceof Error ? err.message : String(err)
      message.error(`命令下发失败：${text}`)
    }
  }

  if (!point || !kind) return null

  const double = isDoubleCommand(point)
  const titleText =
    kind === 'yk' ? '下发遥控命令' : kind === 'setpoint' ? '下发设点命令' : '下发升降命令'
  const commandSummary =
    kind === 'yk'
      ? `${double ? '双命令' : '单命令'} · ${ykOn === 'on' ? '合闸 ON' : '分闸 OFF'}`
      : kind === 'setpoint'
        ? `${spKind} · 目标值 ${spValue}`
        : stepUp
          ? '升一步'
          : '降一步'

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
      okText="确认下发"
      cancelText="取消"
      okButtonProps={{ danger: true, disabled }}
      cancelButtonProps={{ disabled: busy }}
      confirmLoading={busy}
      maskClosable={!busy}
      closable={!busy}
      keyboard={!busy}
      onOk={() => void handleOk()}
      onCancel={onClose}
      width={540}
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Descriptions
          size="small"
          column={2}
          items={[
            { key: 'name', label: '名称', children: point.name || '—' },
            { key: 'value', label: '当前值', children: formatValue(point.value) },
            {
              key: 'type',
              label: '点位类型',
              children: point.subtype ? `${point.type} / ${point.subtype}` : point.type,
            },
            { key: 'cmd', label: '下发命令', children: commandSummary },
          ]}
        />

        {kind === 'yk' ? (
          <>
            <Space wrap>
              <Typography.Text>操作方向</Typography.Text>
              <Radio.Group
                value={ykOn}
                onChange={(e) => setYkOn(e.target.value as 'on' | 'off')}
                optionType="button"
                buttonStyle="solid"
              >
                <Radio.Button value="on">合闸 ON</Radio.Button>
                <Radio.Button value="off">分闸 OFF</Radio.Button>
              </Radio.Group>
              <Tag color={double ? 'purple' : 'blue'}>{double ? '双命令' : '单命令'}</Tag>
              {point.sbo ? <Tag color="orange">SBO 选择-执行</Tag> : null}
            </Space>
            {point.sbo ? (
              <Alert
                type="warning"
                showIcon
                message="该点配置了选择-执行（SBO）"
                description="确认后主站自动先发送选择帧并等待肯定确认；选择被拒或超时不会发送执行帧。"
              />
            ) : null}
          </>
        ) : null}

        {kind === 'setpoint' ? (
          <Space wrap>
            <Select
              style={{ width: 260 }}
              value={spKind}
              options={SETPOINT_KINDS}
              onChange={setSpKind}
            />
            <InputNumber
              prefix="目标值"
              value={spValue}
              onChange={(v) => setSpValue(Number(v ?? 0))}
              style={{ width: 160 }}
            />
          </Space>
        ) : null}

        {kind === 'step' ? (
          <Space wrap>
            <Typography.Text>操作方向</Typography.Text>
            <Radio.Group
              value={stepUp ? 'up' : 'down'}
              onChange={(e) => setStepUp(e.target.value === 'up')}
              optionType="button"
              buttonStyle="solid"
            >
              <Radio.Button value="up">升一步 (2)</Radio.Button>
              <Radio.Button value="down">降一步 (1)</Radio.Button>
            </Radio.Group>
          </Space>
        ) : null}

        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          请核对点位与操作方向；命令下发后将立即生效。
        </Typography.Text>
        {disabled ? (
          <Alert type="info" showIcon message="引擎未连接，命令不可下发" />
        ) : null}
      </Space>
    </Modal>
  )
}
