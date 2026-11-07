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
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

function setpointKinds(t: TFn) {
  return [
    { value: 'short_float' as SetpointKind, label: t('cmd.sp.shortFloat') },
    { value: 'normalized' as SetpointKind, label: t('cmd.sp.normalized') },
    { value: 'scaled' as SetpointKind, label: t('cmd.sp.scaled') },
  ]
}

function paramKinds(t: TFn) {
  return [
    { value: 'float' as ParamKind, label: t('cmd.param.float') },
    { value: 'normalized' as ParamKind, label: t('cmd.param.normalized') },
    { value: 'scaled' as ParamKind, label: t('cmd.param.scaled') },
    { value: 'activation' as ParamKind, label: t('cmd.param.activation') },
  ]
}

function fileActions(t: TFn) {
  return [
    { value: 'directory' as FileAction, label: t('cmd.file.directory') },
    { value: 'select' as FileAction, label: t('cmd.file.select') },
    { value: 'request' as FileAction, label: t('cmd.file.request') },
  ]
}

function giOptions(t: TFn) {
  return [
    { value: 20, label: t('cmd.gi.station') },
    ...Array.from({ length: 16 }, (_, i) => ({
      value: i + 1,
      label: t('cmd.gi.group', { n: i + 1 }),
    })),
  ]
}

interface Props {
  /** 当前选中的点位；未选中时仅能手动指定 IOA */
  point: Point | null
  disabled?: boolean
}

/**
 * 命令面板（T12）——**选中行 + 右侧面板下发命令**。
 *
 * T21 起定义表命令点还支持双击值直接下发（见 `PointCommandDialog`）；
 * 本面板仍是需要显式调参/撤销 SBO/系统命令时的完整入口。
 *
 * 覆盖 `api_contract.md` 的全部主站命令：
 * YK（单/双、SBO 两段式与单帧直发、带时标）、设点（3 种）、升降、比特串、延时、
 * 参数（4 种）、总召唤（站 20 + 组 1–16）、累计量召唤、时钟同步、复位进程、测试命令、
 * 文件传输（目录/选择/请求）、读命令。
 */
export function CommandPanel({ point, disabled = false }: Props) {
  const t = useT()
  const { message } = AntdApp.useApp()

  const [ioa, setIoa] = useState<number>(0)
  const [ykState, setYkState] = useState<0 | 1>(1)
  const [ykDouble, setYkDouble] = useState(false)
  const [ykWithTime, setYkWithTime] = useState(false)
  /** YK SBO 选择后的「已选择未执行」状态：此时可撤销（deactivate） */
  const [ykSelected, setYkSelected] = useState(false)

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

  // 目标 IOA 变化 → 旧 IOA 上的 SBO 选择不再适用，撤销入口复位
  useEffect(() => {
    setYkSelected(false)
  }, [ioa])

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
    if (!selected.ok) return run(t('cmd.yk.selectSbo'), Promise.resolve(selected))
    setYkSelected(true)
    const executed = await yk.mutateAsync({
      ioa,
      state: ykState,
      select: false,
      double: ykDouble,
      with_time: ykWithTime,
    })
    if (executed.ok) setYkSelected(false)
    return run(t('cmd.yk.twoStage'), Promise.resolve(executed))
  }

  /** SBO 选择成功 → 记录「已选择未执行」，解锁撤销按钮 */
  const ykSelectSbo = (): void => {
    void run(
      t('cmd.yk.selectSbo'),
      yk
        .mutateAsync({ ioa, state: ykState, select: true, double: ykDouble, with_time: ykWithTime })
        .then((r) => {
          if (r.ok) setYkSelected(true)
          return r
        }),
    )
  }

  /** 撤销 SBO 选择：发送 DEACT（COT=8），select 位与被撤销的选择帧一致 */
  const ykDeactivate = (): void => {
    void run(
      t('cmd.yk.deactivate'),
      yk
        .mutateAsync({
          ioa,
          state: ykState,
          select: true,
          double: ykDouble,
          with_time: ykWithTime,
          deactivate: true,
        })
        .then((r) => {
          if (r.ok) setYkSelected(false)
          return r
        }),
    )
  }

  const items = [
    {
      key: 'yk',
      label: t('cmd.yk.title'),
      children: (
        <Space orientation="vertical" size={8} style={{ width: '100%' }}>
          <Space wrap>
            <span>{t('cmd.commandType')}</span>
            <Switch
              checkedChildren={t('cmd.double')}
              unCheckedChildren={t('cmd.single')}
              checked={ykDouble}
              onChange={setYkDouble}
            />
            <span>{t('cmd.withTime')}</span>
            <Switch size="small" checked={ykWithTime} onChange={setYkWithTime} />
          </Space>
          <Space wrap>
            <Select
              style={{ width: 130 }}
              value={ykState}
              onChange={(v) => setYkState(v)}
              options={[
                { value: 1, label: t('cmd.on') },
                { value: 0, label: t('cmd.off') },
              ]}
            />
            <Button disabled={noRun || noIoa || busy} onClick={ykSelectSbo}>
              {t('cmd.yk.selectSbo')}
            </Button>
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() =>
                void run(
                  t('cmd.yk.execute'),
                  yk
                    .mutateAsync({ ioa, state: ykState, select: false, double: ykDouble, with_time: ykWithTime })
                    .then((r) => {
                      if (r.ok) setYkSelected(false)
                      return r
                    }),
                )
              }
            >
              {t('cmd.yk.execute')}
            </Button>
            <Button
              type="primary"
              disabled={noRun || noIoa || busy}
              onClick={() => void ykSelectThenExecute()}
            >
              {t('cmd.yk.twoStage')}
            </Button>
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() =>
                void run(
                  t('cmd.yk.singleFrame'),
                  yk
                    .mutateAsync({ ioa, state: ykState, select: false, double: ykDouble, with_time: ykWithTime })
                    .then((r) => {
                      if (r.ok) setYkSelected(false)
                      return r
                    }),
                )
              }
            >
              {t('cmd.yk.singleFrame')}
            </Button>
            <Button danger disabled={noRun || noIoa || busy || !ykSelected} onClick={ykDeactivate}>
              {t('cmd.yk.deactivate')}
            </Button>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('cmd.yk.hint')}
          </Typography.Text>
        </Space>
      ),
    },
    {
      key: 'setpoint',
      label: t('cmd.sp.title'),
      children: (
        <Space orientation="vertical" size={8} style={{ width: '100%' }}>
          <Select style={{ width: '100%' }} value={spKind} options={setpointKinds(t)} onChange={setSpKind} />
          <Space wrap>
            <InputNumber
              prefix={t('cmd.value')}
              value={spValue}
              onChange={(v) => setSpValue(Number(v ?? 0))}
            />
            <span>SBO</span>
            <Switch size="small" checked={spSelect} onChange={setSpSelect} />
            <span>{t('cmd.withTime')}</span>
            <Switch size="small" checked={spWithTime} onChange={setSpWithTime} />
            <Button
              type="primary"
              disabled={noRun || noIoa || busy}
              onClick={() =>
                void run(
                  t('cmd.sp.send'),
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
              {t('cmd.sp.send')}
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      key: 'system',
      label: t('cmd.system.title'),
      children: (
        <Space orientation="vertical" size={8} style={{ width: '100%' }}>
          <Space wrap>
            <Select style={{ width: 210 }} value={giQoi} options={giOptions(t)} onChange={setGiQoi} />
            <Button
              type="primary"
              disabled={noRun || busy}
              onClick={() => void run(t('cmd.gi.label'), gi.mutateAsync({ qoi: giQoi }))}
            >
              {t('cmd.gi.label')}
            </Button>
          </Space>
          <Space wrap>
            <Button disabled={noRun || busy} onClick={() => void run(t('cmd.ci.label'), ci.mutateAsync())}>
              {t('cmd.ci.label')}
            </Button>
            <Button disabled={noRun || busy} onClick={() => void run(t('cmd.clock.label'), clock.mutateAsync())}>
              {t('cmd.clock.label')}
            </Button>
            <Button disabled={noRun || busy} onClick={() => void run(t('cmd.reset.label'), reset.mutateAsync())}>
              {t('cmd.reset.label')}
            </Button>
            <Button disabled={noRun || busy} onClick={() => void run(t('cmd.test.label'), test.mutateAsync())}>
              {t('cmd.test.label')}
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      key: 'step',
      label: t('cmd.misc.title'),
      children: (
        <Space orientation="vertical" size={10} style={{ width: '100%' }}>
          <Space wrap>
            <span>{t('cmd.step.title')}</span>
            <Select
              style={{ width: 110 }}
              value={stepState}
              onChange={setStepState}
              options={[
                { value: 2, label: t('cmd.step.up') },
                { value: 1, label: t('cmd.step.down') },
              ]}
            />
            <span>SBO</span>
            <Switch size="small" checked={stepSelect} onChange={setStepSelect} />
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() =>
                void run(t('cmd.step.label'), step.mutateAsync({ ioa, state: stepState, select: stepSelect }))
              }
            >
              {t('cmd.send')}
            </Button>
          </Space>
          <Space wrap>
            <span>{t('cmd.bit.title')}</span>
            <InputNumber
              min={0}
              value={bitValue}
              onChange={(v) => setBitValue(Number(v ?? 0))}
              style={{ width: 150 }}
            />
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() => void run(t('cmd.bit.label'), bitstring.mutateAsync({ ioa, value: bitValue }))}
            >
              {t('cmd.send')}
            </Button>
          </Space>
          <Space wrap>
            <span>{t('cmd.delay.title')}</span>
            <InputNumber
              min={0}
              max={60000}
              value={delayMs}
              onChange={(v) => setDelayMs(Number(v ?? 0))}
              suffix="ms"
              style={{ width: 190 }}
            />
            <Button
              disabled={noRun || busy}
              onClick={() => void run(t('cmd.delay.label'), delay.mutateAsync({ delay_ms: delayMs }))}
            >
              {t('cmd.send')}
            </Button>
          </Space>
          <Space wrap>
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() => void run(t('cmd.read.label'), read.mutateAsync({ ioa }))}
            >
              {t('cmd.read.button')}
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      key: 'param',
      label: t('cmd.param.title'),
      children: (
        <Space orientation="vertical" size={8} style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            value={paramKind}
            options={paramKinds(t)}
            onChange={setParamKind}
          />
          <Space wrap>
            <InputNumber
              prefix={t('cmd.value')}
              value={paramValue}
              onChange={(v) => setParamValue(Number(v ?? 0))}
            />
            <InputNumber
              prefix={t('cmd.qualifier')}
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
                  t('cmd.param.send'),
                  param.mutateAsync({
                    kind: paramKind,
                    ioa,
                    value: paramValue,
                    qualifier: paramQualifier,
                  }),
                )
              }
            >
              {t('cmd.param.send')}
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      key: 'file',
      label: t('cmd.file.title'),
      children: (
        <Space orientation="vertical" size={8} style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            value={fileAction}
            options={fileActions(t)}
            onChange={setFileAction}
          />
          <Space wrap>
            <InputNumber
              prefix={t('cmd.file.no')}
              min={0}
              value={fileName}
              onChange={(v) => setFileName(Number(v ?? 0))}
            />
            <Button
              disabled={noRun || noIoa || busy}
              onClick={() =>
                void run(t('cmd.file.label'), file.mutateAsync({ action: fileAction, ioa, file_name: fileName }))
              }
            >
              {t('cmd.send')}
            </Button>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('cmd.file.hint')}
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
          <span>{t('cmd.title')}</span>
          {point ? (
            <Tag color="gold">{t('cmd.selected', { type: point.type, ioa: point.ioa })}</Tag>
          ) : (
            <Tag>{t('cmd.noPoint')}</Tag>
          )}
        </Space>
      }
      styles={{ body: { maxHeight: 620, overflowY: 'auto' } }}
    >
      <Space orientation="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap>
          <InputNumber
            prefix={t('cmd.targetIoa')}
            aria-label={t('cmd.targetIoa')}
            min={0}
            value={ioa}
            style={{ width: 190 }}
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

        {disabled ? <Alert type="info" showIcon title={t('cmd.engineOff')} /> : null}
        {!disabled && noIoa ? (
          <Alert type="warning" showIcon title={t('cmd.needIoa')} />
        ) : null}
        {last ? (
          <Alert
            type={last.ok ? 'success' : 'error'}
            showIcon
            title={last.text}
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
