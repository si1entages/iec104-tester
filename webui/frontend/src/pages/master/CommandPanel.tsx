import { useEffect, useState } from 'react'

import { SendOutlined } from '@ant-design/icons'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Collapse,
  Divider,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs } from '../../api/queries'
import type { FileAction, OkResponse, ParamKind, Point, SetpointKind } from '../../api/types'
import { formatValue } from '../../lib/format'

const SETPOINT_KINDS: { value: SetpointKind; label: string }[] = [
  { value: 'short_float', label: 'short_float 短浮点 (C_SE_NC_1)' },
  { value: 'normalized', label: 'normalized 归一化 (C_SE_NA_1)' },
  { value: 'scaled', label: 'scaled 标度化 (C_SE_NB_1)' },
]

const PARAM_KINDS: { value: ParamKind; label: string }[] = [
  { value: 'float', label: 'float 短浮点' },
  { value: 'normalized', label: 'normalized 归一化' },
  { value: 'scaled', label: 'scaled 标度化' },
  { value: 'activation', label: 'activation 参数激活' },
]

const FILE_ACTIONS: { value: FileAction; label: string }[] = [
  { value: 'directory', label: 'directory 召唤目录' },
  { value: 'select', label: 'select 选择文件' },
  { value: 'request', label: 'request 召唤文件' },
]

const GI_OPTIONS = [
  { value: 20, label: '站召唤 (QOI=20)' },
  ...Array.from({ length: 16 }, (_, i) => ({
    value: i + 1,
    label: `组召唤 第${i + 1}组 (QOI=${i + 1})`,
  })),
]

interface Props {
  /** 当前选中的点位；未选中时仅能手动指定 IOA */
  point: Point | null
  disabled?: boolean
}

/**
 * 命令面板（T12）——**选中行 + 右侧面板下发命令**，替代旧的「双击值直接发命令」。
 *
 * 覆盖 `api_contract.md` 的全部主站命令：
 * YK（单/双、SBO 两段式与单帧直发、带时标）、设点（3 种）、升降、比特串、延时、
 * 参数（4 种）、总召唤（站 20 + 组 1–16）、累计量召唤、时钟同步、复位进程、测试命令、
 * 文件传输（目录/选择/请求）、读命令。
 */
export function CommandPanel({ point, disabled = false }: Props) {
  const { message } = AntdApp.useApp()

  const [ioa, setIoa] = useState<number>(0)
  const [ykState, setYkState] = useState<0 | 1>(1)
  const [ykDouble, setYkDouble] = useState(false)
  const [ykWithTime, setYkWithTime] = useState(false)

  const [spKind, setSpKind] = useState<SetpointKind>('short_float')
  const [spValue, setSpValue] = useState<number>(0)
  const [spSelect, setSpSelect] = useState(false)
  const [spWithTime, setSpWithTime] = useState(false)

  const [stepState, setStepState] = useState<1 | 2>(2)
  const [stepSelect, setStepSelect] = useState(false)
  const [bitValue, setBitValue] = useState<number>(0)
  const [delayMs, setDelayMs] = useState<number>(1000)

  const [paramKind, setParamKind] = useState<ParamKind>('float')
  const [paramValue, setParamValue] = useState<number>(0)
  const [paramQualifier, setParamQualifier] = useState<number>(1)

  const [giQoi, setGiQoi] = useState<number>(20)
  const [fileAction, setFileAction] = useState<FileAction>('directory')
  const [fileName, setFileName] = useState<number>(0)

  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  // 选中行 → 面板目标 IOA 自动跟随
  useEffect(() => {
    if (point) setIoa(point.ioa)
  }, [point?.ioa, point?.type])

  const yk = useCommand(api.master.yk)
  const setpoint = useCommand(api.master.setpoint)
  const step = useCommand(api.master.step)
  const bitstring = useCommand(api.master.bitstring)
  const delay = useCommand(api.master.delay)
  const param = useCommand(api.master.param)
  const file = useCommand(api.master.file)
  const read = useCommand(api.master.read)
  const gi = useCommand(api.master.gi)
  const ci = useCommandNoArgs(api.master.ci)
  const clock = useCommandNoArgs(api.master.clock)
  const reset = useCommandNoArgs(api.master.reset)
  const test = useCommandNoArgs(api.master.test)

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
  const busy =
    yk.isPending ||
    setpoint.isPending ||
    step.isPending ||
    bitstring.isPending ||
    delay.isPending ||
    param.isPending ||
    file.isPending ||
    read.isPending ||
    gi.isPending

  /** 两段式：先选择（select=true）再执行（select=false） */
  const ykSelectThenExecute = async (): Promise<void> => {
    const selected = await yk.mutateAsync({
      ioa,
      state: ykState,
      select: true,
      double: ykDouble,
      with_time: ykWithTime,
    })
    if (!selected.ok) return run('YK 选择(SBO)', Promise.resolve(selected))
    const executed = await yk.mutateAsync({
      ioa,
      state: ykState,
      select: false,
      double: ykDouble,
      with_time: ykWithTime,
    })
    return run('YK 两段式(选择+执行)', Promise.resolve(executed))
  }

  const items = [
    {
      key: 'yk',
      label: '遥控 YK',
      children: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space wrap>
            <span>命令类型</span>
            <Switch
              checkedChildren="双命令"
              unCheckedChildren="单命令"
              checked={ykDouble}
              onChange={setYkDouble}
            />
            <span>带时标</span>
            <Switch size="small" checked={ykWithTime} onChange={setYkWithTime} />
          </Space>
          <Space wrap>
            <Select
              style={{ width: 130 }}
              value={ykState}
              onChange={(v) => setYkState(v)}
              options={[
                { value: 1, label: '合闸 / ON' },
                { value: 0, label: '分闸 / OFF' },
              ]}
            />
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() => void run('YK 选择(SBO)', yk.mutateAsync({ ioa, state: ykState, select: true, double: ykDouble, with_time: ykWithTime }))}
            >
              选择 (SBO)
            </Button>
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() => void run('YK 执行', yk.mutateAsync({ ioa, state: ykState, select: false, double: ykDouble, with_time: ykWithTime }))}
            >
              执行
            </Button>
            <Button
              type="primary"
              disabled={noRun || noIoa || busy}
              onClick={() => void ykSelectThenExecute()}
            >
              两段式连发
            </Button>
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() => void run('YK 单帧直发', yk.mutateAsync({ ioa, state: ykState, select: false, double: ykDouble, with_time: ykWithTime }))}
            >
              单帧直发
            </Button>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            两段式 = 选择(select=true) + 执行(select=false)；单帧直发只发执行帧，
            若该点声明 SBO，由后端自动补选择。
          </Typography.Text>
        </Space>
      ),
    },
    {
      key: 'setpoint',
      label: '设点命令',
      children: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            value={spKind}
            options={SETPOINT_KINDS}
            onChange={setSpKind}
          />
          <Space wrap>
            <InputNumber
              prefix="值"
              value={spValue}
              onChange={(v) => setSpValue(Number(v ?? 0))}
            />
            <span>SBO</span>
            <Switch size="small" checked={spSelect} onChange={setSpSelect} />
            <span>带时标</span>
            <Switch size="small" checked={spWithTime} onChange={setSpWithTime} />
            <Button
              type="primary"
              disabled={noRun || noIoa || busy}
              onClick={() =>
                void run(
                  '设点',
                  setpoint.mutateAsync({
                    ioa,
                    value: spValue,
                    kind: spKind,
                    select: spSelect,
                    with_time: spWithTime,
                  }),
                )
              }
            >
              下发设点
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      key: 'step',
      label: '升降 / 比特串 / 延时 / 读',
      children: (
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Space wrap>
            <span>升降</span>
            <Select
              style={{ width: 110 }}
              value={stepState}
              onChange={setStepState}
              options={[
                { value: 2, label: '升一步 (2)' },
                { value: 1, label: '降一步 (1)' },
              ]}
            />
            <span>SBO</span>
            <Switch size="small" checked={stepSelect} onChange={setStepSelect} />
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() =>
                void run('升降命令', step.mutateAsync({ ioa, state: stepState, select: stepSelect }))
              }
            >
              下发
            </Button>
          </Space>
          <Space wrap>
            <span>比特串</span>
            <InputNumber
              min={0}
              value={bitValue}
              onChange={(v) => setBitValue(Number(v ?? 0))}
              style={{ width: 150 }}
            />
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() => void run('比特串命令', bitstring.mutateAsync({ ioa, value: bitValue }))}
            >
              下发
            </Button>
          </Space>
          <Space wrap>
            <span>延时获得</span>
            <InputNumber
              min={0}
              max={60000}
              value={delayMs}
              onChange={(v) => setDelayMs(Number(v ?? 0))}
              addonAfter="ms"
              style={{ width: 190 }}
            />
            <Button
              disabled={noRun || busy}
              onClick={() => void run('延时命令', delay.mutateAsync({ delay_ms: delayMs }))}
            >
              下发
            </Button>
          </Space>
          <Space wrap>
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() => void run('读命令', read.mutateAsync({ ioa }))}
            >
              读命令 (C_RD_NA_1)
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      key: 'param',
      label: '参数命令',
      children: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            value={paramKind}
            options={PARAM_KINDS}
            onChange={setParamKind}
          />
          <Space wrap>
            <InputNumber prefix="值" value={paramValue} onChange={(v) => setParamValue(Number(v ?? 0))} />
            <InputNumber
              prefix="限定词"
              min={0}
              max={255}
              value={paramQualifier}
              onChange={(v) => setParamQualifier(Number(v ?? 1))}
            />
            <Button
              type="primary"
              disabled={noRun || noIoa || busy}
              onClick={() =>
                void run(
                  '参数命令',
                  param.mutateAsync({
                    kind: paramKind,
                    ioa,
                    value: paramValue,
                    qualifier: paramQualifier,
                  }),
                )
              }
            >
              下发参数
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      key: 'system',
      label: '系统召唤 / 对时 / 复位',
      children: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space wrap>
            <Select
              style={{ width: 210 }}
              value={giQoi}
              options={GI_OPTIONS}
              onChange={setGiQoi}
            />
            <Button
              type="primary"
              disabled={noRun || busy}
              onClick={() => void run('总召唤', gi.mutateAsync({ qoi: giQoi }))}
            >
              总召唤
            </Button>
          </Space>
          <Space wrap>
            <Button disabled={noRun || busy} onClick={() => void run('累计量召唤', ci.mutateAsync())}>
              累计量召唤
            </Button>
            <Button disabled={noRun || busy} onClick={() => void run('时钟同步', clock.mutateAsync())}>
              时钟同步
            </Button>
            <Button disabled={noRun || busy} onClick={() => void run('复位进程', reset.mutateAsync())}>
              复位进程
            </Button>
            <Button disabled={noRun || busy} onClick={() => void run('测试命令', test.mutateAsync())}>
              测试命令
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      key: 'file',
      label: '文件传输',
      children: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            value={fileAction}
            options={FILE_ACTIONS}
            onChange={setFileAction}
          />
          <Space wrap>
            <InputNumber
              prefix="文件号"
              min={0}
              value={fileName}
              onChange={(v) => setFileName(Number(v ?? 0))}
            />
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() =>
                void run('文件传输', file.mutateAsync({ action: fileAction, ioa, file_name: fileName }))
              }
            >
              下发
            </Button>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            文件传输使用目标 IOA（选择文件/召唤文件时通常为 0）。
          </Typography.Text>
        </Space>
      ),
    },
  ]

  return (
    <Card
      size="small"
      title={
        <Space>
          <SendOutlined />
          <span>命令面板</span>
          {point ? <Tag color="gold">已选 {point.type}-{point.ioa}</Tag> : <Tag>未选点</Tag>}
        </Space>
      }
      styles={{ body: { maxHeight: 620, overflowY: 'auto' } }}
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap>
          <InputNumber
            prefix="目标 IOA"
            min={0}
            value={ioa}
            style={{ width: 190 }}
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

        {disabled ? (
          <Alert type="info" showIcon message="引擎未连接，命令不可下发" />
        ) : null}
        {!disabled && noIoa ? (
          <Alert type="warning" showIcon message="请先选择点位或填写目标 IOA" />
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
        <Collapse
          size="small"
          defaultActiveKey={['yk']}
          items={items}
          bordered={false}
          style={{ background: 'transparent' }}
        />
      </Space>
    </Card>
  )
}
