import { useEffect, useState } from 'react'

import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  ExpandableSection,
  Flex,
  Form,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Label,
  TextInput,
} from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs } from '../../api/queries'
import type { FileAction, OkResponse, ParamKind, Point, SetpointKind } from '../../api/types'
import { useT } from '../../i18n'
import { formatValue } from '../../lib/format'

interface NumProps {
  id: string
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  width?: number
}

/** 数字输入：PF `NumberInput` 的改动回调依赖步进按钮，这里统一用原生 number 输入以保持可控。 */
function NumField({ id, label, value, onChange, min, max, width = 180 }: NumProps) {
  return (
    <FormGroup label={label} fieldId={id} style={{ maxWidth: width }}>
      <TextInput
        id={id}
        type="number"
        min={min}
        max={max}
        value={String(value)}
        onChange={(_event, v) => {
          const n = Number(v)
          onChange(Number.isFinite(n) ? n : 0)
        }}
      />
    </FormGroup>
  )
}

interface Props {
  point: Point | null
  disabled?: boolean
}

/**
 * PatternFly 命令面板：覆盖 `api_contract.md` 的全部主站命令。
 *
 * YK（单/双、SBO 两段式与单帧直发、带时标）、设点（3 种）、升降、比特串、延时、
 * 参数（4 种）、总召唤（站 20 + 组 1–16）、累计量召唤、时钟同步、复位进程、测试命令、
 * 文件传输（目录/选择/请求）、读命令。
 *
 * 与旧面板的差异：结果反馈改用面板内联 Alert（不再用 antd message），保留最近一次结果。
 */
export function PfCommandPanel({ point, disabled = false }: Props) {
  const t = useT()
  const [ioa, setIoa] = useState(point?.ioa ?? 0)
  const [ykState, setYkState] = useState<'1' | '0'>(point?.ioa ? '1' : '1')
  const [ykDouble, setYkDouble] = useState(false)
  const [ykWithTime, setYkWithTime] = useState(false)
  const [ykSelected, setYkSelected] = useState(false)

  const [spKind, setSpKind] = useState<SetpointKind>('short_float')
  const [spValue, setSpValue] = useState(0)
  const [spSelect, setSpSelect] = useState(false)
  const [spWithTime, setSpWithTime] = useState(false)

  const [stepState, setStepState] = useState<'2' | '1'>('2')
  const [stepSelect, setStepSelect] = useState(false)
  const [bitValue, setBitValue] = useState(0)
  const [delayMs, setDelayMs] = useState(1000)

  const [paramKind, setParamKind] = useState<ParamKind>('float')
  const [paramValue, setParamValue] = useState(0)
  const [paramQualifier, setParamQualifier] = useState(1)

  const [giQoi, setGiQoi] = useState('20')
  const [fileAction, setFileAction] = useState<FileAction>('directory')
  const [fileName, setFileName] = useState(0)

  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)
  const [open, setOpen] = useState<Record<string, boolean>>({ yk: true })
  const section = (key: string) => ({
    isExpanded: Boolean(open[key]),
    onToggle: (_event: unknown, expanded: boolean) =>
      setOpen((prev) => ({ ...prev, [key]: expanded })),
  })

  // 选中行 → 目标 IOA 跟随；IOA 变化时旧 SBO 选择失效
  useEffect(() => {
    if (point) setIoa(point.ioa)
  }, [point?.ioa, point?.type])

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
    setLast({ ok: result.ok, text })
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

  const ykRequest = (select: boolean, deactivate = false) => ({
    ioa,
    state: Number(ykState) as 0 | 1,
    select,
    double: ykDouble,
    with_time: ykWithTime,
    ...(deactivate ? { deactivate: true } : {}),
  })

  const ykSelectSbo = (): void => {
    void run(
      t('cmd.yk.selectSbo'),
      yk.mutateAsync(ykRequest(true)).then((r) => {
        if (r.ok) setYkSelected(true)
        return r
      }),
    )
  }

  const ykExecute = (): void => {
    void run(
      t('cmd.yk.execute'),
      yk.mutateAsync(ykRequest(false)).then((r) => {
        if (r.ok) setYkSelected(false)
        return r
      }),
    )
  }

  const ykSelectThenExecute = async (): Promise<void> => {
    const selected = await yk.mutateAsync(ykRequest(true))
    if (!selected.ok) return run(t('cmd.yk.selectSbo'), Promise.resolve(selected))
    setYkSelected(true)
    const executed = await yk.mutateAsync(ykRequest(false))
    if (executed.ok) setYkSelected(false)
    return run(t('cmd.yk.twoStage'), Promise.resolve(executed))
  }

  const ykDeactivate = (): void => {
    void run(
      t('cmd.yk.deactivate'),
      yk.mutateAsync(ykRequest(true, true)).then((r) => {
        if (r.ok) setYkSelected(false)
        return r
      }),
    )
  }

  const giOptions = [
    { value: '20', label: t('cmd.gi.station') },
    ...Array.from({ length: 16 }, (_, i) => ({
      value: String(i + 1),
      label: t('cmd.gi.group', { n: i + 1 }),
    })),
  ]

  return (
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
          <span>{t('cmd.title')}</span>
          {point ? (
            <Label isCompact color="blue">
              {t('cmd.selected', { type: point.type, ioa: point.ioa })}
            </Label>
          ) : (
            <Label isCompact>{t('cmd.noPoint')}</Label>
          )}
        </Flex>
      </CardTitle>
      <CardBody>
        <Form onSubmit={(event) => event.preventDefault()}>
          <FormGroup label={t('cmd.targetIoa')} fieldId="pf-cmd-ioa" style={{ maxWidth: 220 }}>
            <TextInput
              id="pf-cmd-ioa"
              type="number"
              min={0}
              value={String(ioa)}
              onChange={(_event, v) => {
                setIoa(Number(v) || 0)
                setYkSelected(false)
              }}
            />
          </FormGroup>

          {point ? (
            <div style={{ opacity: 0.75, fontSize: 12, marginBottom: 8 }}>
              {t('cmd.currentValue', { name: point.name, value: formatValue(point.value) })}
            </div>
          ) : (
            <div style={{ opacity: 0.75, fontSize: 12, marginBottom: 8 }}>{t('cmd.pickHint')}</div>
          )}

          {disabled ? <Alert isInline variant="info" title={t('cmd.engineOff')} /> : null}
          {!disabled && noIoa ? <Alert isInline variant="warning" title={t('cmd.needIoa')} /> : null}
          {last ? (
            <Alert
              isInline
              variant={last.ok ? 'success' : 'danger'}
              title={last.text}
              style={{ marginTop: 8 }}
            />
          ) : null}

          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <ExpandableSection toggleText={t('cmd.yk.title')} {...section('yk')}>
              <Flex direction={{ default: 'column' }} gap={{ default: 'gapSm' }}>
                <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }}>
                  <FormGroup label={t('cmd.commandType')} fieldId="pf-yk-double">
                    <FormSelect
                      id="pf-yk-double"
                      value={ykDouble ? 'double' : 'single'}
                      onChange={(_e, v) => setYkDouble(v === 'double')}
                      aria-label={t('cmd.commandType')}
                    >
                      <FormSelectOption value="single" label={t('cmd.single')} />
                      <FormSelectOption value="double" label={t('cmd.double')} />
                    </FormSelect>
                  </FormGroup>
                  <FormGroup label={t('cmd.withTime')} fieldId="pf-yk-time">
                    <FormSelect
                      id="pf-yk-time"
                      value={ykWithTime ? 'yes' : 'no'}
                      onChange={(_e, v) => setYkWithTime(v === 'yes')}
                      aria-label={t('cmd.withTime')}
                    >
                      <FormSelectOption value="no" label={t('conn.off')} />
                      <FormSelectOption value="yes" label={t('conn.on')} />
                    </FormSelect>
                  </FormGroup>
                </Flex>
                <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
                  <FormGroup label={t('pcd.direction')} fieldId="pf-yk-state">
                    <FormSelect
                      id="pf-yk-state"
                      value={ykState}
                      onChange={(_e, v) => setYkState(v === '0' ? '0' : '1')}
                      aria-label={t('pcd.direction')}
                    >
                      <FormSelectOption value="1" label={t('cmd.on')} />
                      <FormSelectOption value="0" label={t('cmd.off')} />
                    </FormSelect>
                  </FormGroup>
                  <Button variant="secondary" isDisabled={noRun || noIoa || busy} onClick={ykSelectSbo}>
                    {t('cmd.yk.selectSbo')}
                  </Button>
                  <Button
                    variant="primary"
                    isDanger={ykState === '0'}
                    isDisabled={noRun || noIoa || busy}
                    onClick={ykExecute}
                  >
                    {t('cmd.yk.execute')}
                  </Button>
                  <Button
                    variant="primary"
                    isDanger={ykState === '0'}
                    isDisabled={noRun || noIoa || busy}
                    onClick={() => void ykSelectThenExecute()}
                  >
                    {t('cmd.yk.twoStage')}
                  </Button>
                  <Button variant="secondary" isDisabled={noRun || noIoa || busy} onClick={ykExecute}>
                    {t('cmd.yk.singleFrame')}
                  </Button>
                  <Button variant="danger" isDisabled={noRun || noIoa || busy || !ykSelected} onClick={ykDeactivate}>
                    {t('cmd.yk.deactivate')}
                  </Button>
                </Flex>
                <div style={{ opacity: 0.75, fontSize: 12 }}>{t('cmd.yk.hint')}</div>
              </Flex>
            </ExpandableSection>

            <ExpandableSection toggleText={t('cmd.sp.title')} {...section('sp')}>
              <Flex direction={{ default: 'column' }} gap={{ default: 'gapSm' }}>
                <FormGroup label={t('cmd.value')} fieldId="pf-sp-kind" style={{ maxWidth: 260 }}>
                  <FormSelect
                    id="pf-sp-kind"
                    value={spKind}
                    onChange={(_e, v) => setSpKind(v as SetpointKind)}
                    aria-label={t('cmd.value')}
                  >
                    <FormSelectOption value="short_float" label={t('cmd.sp.shortFloat')} />
                    <FormSelectOption value="normalized" label={t('cmd.sp.normalized')} />
                    <FormSelectOption value="scaled" label={t('cmd.sp.scaled')} />
                  </FormSelect>
                </FormGroup>
                <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
                  <NumField id="pf-sp-value" label={t('cmd.value')} value={spValue} onChange={setSpValue} />
                  <FormGroup label="SBO" fieldId="pf-sp-select">
                    <FormSelect
                      id="pf-sp-select"
                      value={spSelect ? 'yes' : 'no'}
                      onChange={(_e, v) => setSpSelect(v === 'yes')}
                      aria-label="SBO"
                    >
                      <FormSelectOption value="no" label={t('conn.off')} />
                      <FormSelectOption value="yes" label={t('conn.on')} />
                    </FormSelect>
                  </FormGroup>
                  <FormGroup label={t('cmd.withTime')} fieldId="pf-sp-time">
                    <FormSelect
                      id="pf-sp-time"
                      value={spWithTime ? 'yes' : 'no'}
                      onChange={(_e, v) => setSpWithTime(v === 'yes')}
                      aria-label={t('cmd.withTime')}
                    >
                      <FormSelectOption value="no" label={t('conn.off')} />
                      <FormSelectOption value="yes" label={t('conn.on')} />
                    </FormSelect>
                  </FormGroup>
                  <Button
                    variant="primary"
                    isDisabled={noRun || noIoa || busy}
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
                </Flex>
              </Flex>
            </ExpandableSection>

            <ExpandableSection toggleText={t('cmd.system.title')} {...section('system')}>
              <Flex direction={{ default: 'column' }} gap={{ default: 'gapSm' }}>
                <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }}>
                  <FormGroup label={t('cmd.gi.label')} fieldId="pf-gi-qoi" style={{ minWidth: 240 }}>
                    <FormSelect
                      id="pf-gi-qoi"
                      value={giQoi}
                      onChange={(_e, v) => setGiQoi(v)}
                      aria-label={t('cmd.gi.label')}
                    >
                      {giOptions.map((o) => (
                        <FormSelectOption key={o.value} value={o.value} label={o.label} />
                      ))}
                    </FormSelect>
                  </FormGroup>
                  <Button
                    variant="primary"
                    isDisabled={noRun || busy}
                    onClick={() => void run(t('cmd.gi.label'), gi.mutateAsync({ qoi: Number(giQoi) }))}
                  >
                    {t('cmd.gi.label')}
                  </Button>
                </Flex>
                <ActionGroup>
                  <Button variant="secondary" isDisabled={noRun || busy} onClick={() => void run(t('cmd.ci.label'), ci.mutateAsync())}>
                    {t('cmd.ci.label')}
                  </Button>
                  <Button variant="secondary" isDisabled={noRun || busy} onClick={() => void run(t('cmd.clock.label'), clock.mutateAsync())}>
                    {t('cmd.clock.label')}
                  </Button>
                  <Button variant="secondary" isDisabled={noRun || busy} onClick={() => void run(t('cmd.reset.label'), reset.mutateAsync())}>
                    {t('cmd.reset.label')}
                  </Button>
                  <Button variant="secondary" isDisabled={noRun || busy} onClick={() => void run(t('cmd.test.label'), test.mutateAsync())}>
                    {t('cmd.test.label')}
                  </Button>
                </ActionGroup>
              </Flex>
            </ExpandableSection>

            <ExpandableSection toggleText={t('cmd.misc.title')} {...section('misc')}>
              <Flex direction={{ default: 'column' }} gap={{ default: 'gapMd' }}>
                <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
                  <FormGroup label={t('cmd.step.title')} fieldId="pf-step-state">
                    <FormSelect
                      id="pf-step-state"
                      value={stepState}
                      onChange={(_e, v) => setStepState(v === '1' ? '1' : '2')}
                      aria-label={t('cmd.step.title')}
                    >
                      <FormSelectOption value="2" label={t('cmd.step.up')} />
                      <FormSelectOption value="1" label={t('cmd.step.down')} />
                    </FormSelect>
                  </FormGroup>
                  <FormGroup label="SBO" fieldId="pf-step-select">
                    <FormSelect
                      id="pf-step-select"
                      value={stepSelect ? 'yes' : 'no'}
                      onChange={(_e, v) => setStepSelect(v === 'yes')}
                      aria-label="SBO"
                    >
                      <FormSelectOption value="no" label={t('conn.off')} />
                      <FormSelectOption value="yes" label={t('conn.on')} />
                    </FormSelect>
                  </FormGroup>
                  <Button
                    variant="secondary"
                    isDisabled={noRun || noIoa || busy}
                    onClick={() =>
                      void run(
                        t('cmd.step.label'),
                        step.mutateAsync({ ioa, state: Number(stepState) as 1 | 2, select: stepSelect }),
                      )
                    }
                  >
                    {t('cmd.send')}
                  </Button>
                </Flex>

                <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }}>
                  <NumField id="pf-bit" label={t('cmd.bit.title')} value={bitValue} onChange={setBitValue} min={0} />
                  <Button
                    variant="secondary"
                    isDisabled={noRun || noIoa || busy}
                    onClick={() => void run(t('cmd.bit.label'), bitstring.mutateAsync({ ioa, value: bitValue }))}
                  >
                    {t('cmd.send')}
                  </Button>
                </Flex>

                <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }}>
                  <NumField
                    id="pf-delay"
                    label={`${t('cmd.delay.title')} (ms)`}
                    value={delayMs}
                    onChange={setDelayMs}
                    min={0}
                    max={60000}
                  />
                  <Button
                    variant="secondary"
                    isDisabled={noRun || busy}
                    onClick={() => void run(t('cmd.delay.label'), delay.mutateAsync({ delay_ms: delayMs }))}
                  >
                    {t('cmd.send')}
                  </Button>
                </Flex>

                <ActionGroup>
                  <Button
                    variant="secondary"
                    isDisabled={noRun || noIoa || busy}
                    onClick={() => void run(t('cmd.read.label'), read.mutateAsync({ ioa }))}
                  >
                    {t('cmd.read.button')}
                  </Button>
                </ActionGroup>
              </Flex>
            </ExpandableSection>

            <ExpandableSection toggleText={t('cmd.param.title')} {...section('param')}>
              <Flex direction={{ default: 'column' }} gap={{ default: 'gapSm' }}>
                <FormGroup label={t('cmd.param.title')} fieldId="pf-param-kind" style={{ maxWidth: 260 }}>
                  <FormSelect
                    id="pf-param-kind"
                    value={paramKind}
                    onChange={(_e, v) => setParamKind(v as ParamKind)}
                    aria-label={t('cmd.param.title')}
                  >
                    <FormSelectOption value="float" label={t('cmd.param.float')} />
                    <FormSelectOption value="normalized" label={t('cmd.param.normalized')} />
                    <FormSelectOption value="scaled" label={t('cmd.param.scaled')} />
                    <FormSelectOption value="activation" label={t('cmd.param.activation')} />
                  </FormSelect>
                </FormGroup>
                <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
                  <NumField id="pf-param-value" label={t('cmd.value')} value={paramValue} onChange={setParamValue} />
                  <NumField
                    id="pf-param-qualifier"
                    label={t('cmd.qualifier')}
                    value={paramQualifier}
                    onChange={setParamQualifier}
                    min={0}
                    max={255}
                  />
                  <Button
                    variant="primary"
                    isDisabled={noRun || noIoa || busy}
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
                </Flex>
              </Flex>
            </ExpandableSection>

            <ExpandableSection toggleText={t('cmd.file.title')} {...section('file')}>
              <Flex direction={{ default: 'column' }} gap={{ default: 'gapSm' }}>
                <FormGroup label={t('cmd.file.title')} fieldId="pf-file-action" style={{ maxWidth: 260 }}>
                  <FormSelect
                    id="pf-file-action"
                    value={fileAction}
                    onChange={(_e, v) => setFileAction(v as FileAction)}
                    aria-label={t('cmd.file.title')}
                  >
                    <FormSelectOption value="directory" label={t('cmd.file.directory')} />
                    <FormSelectOption value="select" label={t('cmd.file.select')} />
                    <FormSelectOption value="request" label={t('cmd.file.request')} />
                  </FormSelect>
                </FormGroup>
                <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }}>
                  <NumField id="pf-file-no" label={t('cmd.file.no')} value={fileName} onChange={setFileName} min={0} />
                  <Button
                    variant="secondary"
                    isDisabled={noRun || noIoa || busy}
                    onClick={() =>
                      void run(
                        t('cmd.file.label'),
                        file.mutateAsync({ action: fileAction, ioa, file_name: fileName }),
                      )
                    }
                  >
                    {t('cmd.send')}
                  </Button>
                </Flex>
                <div style={{ opacity: 0.75, fontSize: 12 }}>{t('cmd.file.hint')}</div>
              </Flex>
            </ExpandableSection>
          </div>
        </Form>
      </CardBody>
    </Card>
  )
}
