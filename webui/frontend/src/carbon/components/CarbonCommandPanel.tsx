import { useEffect, useState } from 'react'

import { Accordion, AccordionItem, Button, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs } from '../../api/queries'
import type { FileAction, OkResponse, ParamKind, Point, SetpointKind } from '../../api/types'
import { useT } from '../../i18n'
import { formatValue } from '../../lib/format'
import { Note, NumField, Panel, SelectField, TextField } from './ui'

interface Props {
  point: Point | null
  disabled?: boolean
}

/**
 * Carbon 命令面板：覆盖 `api_contract.md` 的全部主站命令。
 *
 * YK（单/双、SBO 两段式与单帧直发、带时标）、设点（3 种）、升降、比特串、延时、
 * 参数（4 种）、总召唤（站 20 + 组 1–16）、累计量召唤、时钟同步、复位进程、测试命令、
 * 文件传输（目录/选择/请求）、读命令。
 */
export function CarbonCommandPanel({ point, disabled = false }: Props) {
  const t = useT()
  const [ioa, setIoa] = useState(point?.ioa ?? 0)
  const [ykState, setYkState] = useState<'1' | '0'>('1')
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
    open: Boolean(open[key]),
    onHeadingClick: ({ isOpen }: { isOpen: boolean }) =>
      setOpen((prev) => ({ ...prev, [key]: isOpen })),
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
  const clockOffset = useCommand(api.master.clockOffset)
  const clockOffsetResult = clockOffset.data as
    | { ok: boolean; error?: string; avg_ms?: number; min_ms?: number; max_ms?: number; count?: number }
    | undefined
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
    <Panel
      title={
        <span className="app-row">
          {t('cmd.title')}
          {point ? (
            <Tag size="sm" type="blue">
              {t('cmd.selected', { type: point.type, ioa: point.ioa })}
            </Tag>
          ) : (
            <Tag size="sm" type="gray">
              {t('cmd.noPoint')}
            </Tag>
          )}
        </span>
      }
    >
      <div style={{ maxWidth: 220 }}>
        <TextField
          id="cb-cmd-ioa"
          label={t('cmd.targetIoa')}
          type="number"
          min={0}
          value={String(ioa)}
          onChange={(v) => {
            setIoa(Number(v) || 0)
            setYkSelected(false)
          }}
        />
      </div>

      {point ? (
        <div style={{ opacity: 0.75, fontSize: 12, margin: '8px 0' }}>
          {t('cmd.currentValue', { name: point.name, value: formatValue(point.value) })}
        </div>
      ) : (
        <div style={{ opacity: 0.75, fontSize: 12, margin: '8px 0' }}>{t('cmd.pickHint')}</div>
      )}

      {disabled ? <Note kind="info" title={t('cmd.engineOff')} /> : null}
      {!disabled && noIoa ? <Note kind="warning" title={t('cmd.needIoa')} /> : null}
      {last ? <Note kind={last.ok ? 'success' : 'error'} title={last.text} style={{ marginTop: 8 }} /> : null}

      <div style={{ marginTop: 12 }}>
      <Accordion>
        <AccordionItem title={t('cmd.yk.title')} {...section('yk')}>
          <div className="app-stack">
            <div className="app-row">
              <SelectField
                id="cb-yk-double"
                label={t('cmd.commandType')}
                width={170}
                value={ykDouble ? 'double' : 'single'}
                onChange={(v) => setYkDouble(v === 'double')}
                options={[
                  { value: 'single', label: t('cmd.single') },
                  { value: 'double', label: t('cmd.double') },
                ]}
              />
              <SelectField
                id="cb-yk-time"
                label={t('cmd.withTime')}
                width={140}
                value={ykWithTime ? 'yes' : 'no'}
                onChange={(v) => setYkWithTime(v === 'yes')}
                options={[
                  { value: 'no', label: t('conn.off') },
                  { value: 'yes', label: t('conn.on') },
                ]}
              />
            </div>
            <div className="app-row" style={{ alignItems: 'flex-end' }}>
              <SelectField
                id="cb-yk-state"
                label={t('pcd.direction')}
                width={140}
                value={ykState}
                onChange={(v) => setYkState(v === '0' ? '0' : '1')}
                options={[
                  { value: '1', label: t('cmd.on') },
                  { value: '0', label: t('cmd.off') },
                ]}
              />
              <Button kind="secondary" disabled={noRun || noIoa || busy} onClick={ykSelectSbo}>
                {t('cmd.yk.selectSbo')}
              </Button>
              <Button
                kind={ykState === '0' ? 'danger' : 'primary'}
                disabled={noRun || noIoa || busy}
                onClick={ykExecute}
              >
                {t('cmd.yk.execute')}
              </Button>
              <Button
                kind={ykState === '0' ? 'danger' : 'primary'}
                disabled={noRun || noIoa || busy}
                onClick={() => void ykSelectThenExecute()}
              >
                {t('cmd.yk.twoStage')}
              </Button>
              <Button kind="secondary" disabled={noRun || noIoa || busy} onClick={ykExecute}>
                {t('cmd.yk.singleFrame')}
              </Button>
              <Button kind="danger" disabled={noRun || noIoa || busy || !ykSelected} onClick={ykDeactivate}>
                {t('cmd.yk.deactivate')}
              </Button>
            </div>
            <div style={{ opacity: 0.75, fontSize: 12 }}>{t('cmd.yk.hint')}</div>
          </div>
          {clockOffsetResult && clockOffsetResult.ok && clockOffsetResult.avg_ms !== undefined ? (
            <div style={{ marginTop: 8, fontSize: 12, opacity: 0.85 }}>
              {t('cmd.clockOffset.done', {
                avg: String(clockOffsetResult.avg_ms),
                count: String(clockOffsetResult.count ?? 0),
                min: String(clockOffsetResult.min_ms ?? 0),
                max: String(clockOffsetResult.max_ms ?? 0),
              })}
            </div>
          ) : null}
        </AccordionItem>

        <AccordionItem title={t('cmd.sp.title')} {...section('sp')}>
          <div className="app-stack">
            <div style={{ maxWidth: 260 }}>
              <SelectField
                id="cb-sp-kind"
                label={t('cmd.value')}
                value={spKind}
                onChange={(v) => setSpKind(v as SetpointKind)}
                options={[
                  { value: 'short_float', label: t('cmd.sp.shortFloat') },
                  { value: 'normalized', label: t('cmd.sp.normalized') },
                  { value: 'scaled', label: t('cmd.sp.scaled') },
                ]}
              />
            </div>
            <div className="app-row" style={{ alignItems: 'flex-end' }}>
              <NumField id="cb-sp-value" label={t('cmd.value')} value={spValue} onChange={setSpValue} />
              <SelectField
                id="cb-sp-select"
                label="SBO"
                width={140}
                value={spSelect ? 'yes' : 'no'}
                onChange={(v) => setSpSelect(v === 'yes')}
                options={[
                  { value: 'no', label: t('conn.off') },
                  { value: 'yes', label: t('conn.on') },
                ]}
              />
              <SelectField
                id="cb-sp-time"
                label={t('cmd.withTime')}
                width={140}
                value={spWithTime ? 'yes' : 'no'}
                onChange={(v) => setSpWithTime(v === 'yes')}
                options={[
                  { value: 'no', label: t('conn.off') },
                  { value: 'yes', label: t('conn.on') },
                ]}
              />
              <Button
                kind="primary"
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
            </div>
          </div>
        </AccordionItem>

        <AccordionItem title={t('cmd.system.title')} {...section('system')}>
          <div className="app-stack">
            <div className="app-row" style={{ alignItems: 'flex-end' }}>
              <div style={{ width: 240, minWidth: 240 }}>
                <SelectField
                  id="cb-gi-qoi"
                  label={t('cmd.gi.label')}
                  value={giQoi}
                  onChange={setGiQoi}
                  options={giOptions}
                />
              </div>
              <Button
                kind="primary"
                disabled={noRun || busy}
                onClick={() => void run(t('cmd.gi.label'), gi.mutateAsync({ qoi: Number(giQoi) }))}
              >
                {t('cmd.gi.label')}
              </Button>
            </div>
            <div className="app-row">
              <Button kind="secondary" disabled={noRun || busy} onClick={() => void run(t('cmd.ci.label'), ci.mutateAsync())}>
                {t('cmd.ci.label')}
              </Button>
              <Button kind="secondary" disabled={noRun || busy} onClick={() => void run(t('cmd.clock.label'), clock.mutateAsync())}>
                {t('cmd.clock.label')}
              </Button>
              <Button
                kind="secondary"
                disabled={noRun || busy}
                onClick={() => void run(t('cmd.clockOffset.label'), clockOffset.mutateAsync(5))}
              >
                {t('cmd.clockOffset.label')}
              </Button>
              <Button kind="secondary" disabled={noRun || busy} onClick={() => void run(t('cmd.reset.label'), reset.mutateAsync())}>
                {t('cmd.reset.label')}
              </Button>
              <Button kind="secondary" disabled={noRun || busy} onClick={() => void run(t('cmd.test.label'), test.mutateAsync())}>
                {t('cmd.test.label')}
              </Button>
            </div>
          </div>
        </AccordionItem>

        <AccordionItem title={t('cmd.misc.title')} {...section('misc')}>
          <div className="app-stack">
            <div className="app-row" style={{ alignItems: 'flex-end' }}>
              <SelectField
                id="cb-step-state"
                label={t('cmd.step.title')}
                width={170}
                value={stepState}
                onChange={(v) => setStepState(v === '1' ? '1' : '2')}
                options={[
                  { value: '2', label: t('cmd.step.up') },
                  { value: '1', label: t('cmd.step.down') },
                ]}
              />
              <SelectField
                id="cb-step-select"
                label="SBO"
                width={140}
                value={stepSelect ? 'yes' : 'no'}
                onChange={(v) => setStepSelect(v === 'yes')}
                options={[
                  { value: 'no', label: t('conn.off') },
                  { value: 'yes', label: t('conn.on') },
                ]}
              />
              <Button
                kind="secondary"
                disabled={noRun || noIoa || busy}
                onClick={() =>
                  void run(
                    t('cmd.step.label'),
                    step.mutateAsync({ ioa, state: Number(stepState) as 1 | 2, select: stepSelect }),
                  )
                }
              >
                {t('cmd.send')}
              </Button>
            </div>

            <div className="app-row" style={{ alignItems: 'flex-end' }}>
              <NumField id="cb-bit" label={t('cmd.bit.title')} value={bitValue} onChange={setBitValue} min={0} />
              <Button
                kind="secondary"
                disabled={noRun || noIoa || busy}
                onClick={() => void run(t('cmd.bit.label'), bitstring.mutateAsync({ ioa, value: bitValue }))}
              >
                {t('cmd.send')}
              </Button>
            </div>

            <div className="app-row" style={{ alignItems: 'flex-end' }}>
              <NumField
                id="cb-delay"
                label={`${t('cmd.delay.title')} (ms)`}
                value={delayMs}
                onChange={setDelayMs}
                min={0}
                max={60000}
              />
              <Button
                kind="secondary"
                disabled={noRun || busy}
                onClick={() => void run(t('cmd.delay.label'), delay.mutateAsync({ delay_ms: delayMs }))}
              >
                {t('cmd.send')}
              </Button>
            </div>

            <div className="app-row">
              <Button
                kind="secondary"
                disabled={noRun || noIoa || busy}
                onClick={() => void run(t('cmd.read.label'), read.mutateAsync({ ioa }))}
              >
                {t('cmd.read.button')}
              </Button>
            </div>
          </div>
        </AccordionItem>

        <AccordionItem title={t('cmd.param.title')} {...section('param')}>
          <div className="app-stack">
            <div style={{ maxWidth: 260 }}>
              <SelectField
                id="cb-param-kind"
                label={t('cmd.param.title')}
                value={paramKind}
                onChange={(v) => setParamKind(v as ParamKind)}
                options={[
                  { value: 'float', label: t('cmd.param.float') },
                  { value: 'normalized', label: t('cmd.param.normalized') },
                  { value: 'scaled', label: t('cmd.param.scaled') },
                  { value: 'activation', label: t('cmd.param.activation') },
                ]}
              />
            </div>
            <div className="app-row" style={{ alignItems: 'flex-end' }}>
              <NumField id="cb-param-value" label={t('cmd.value')} value={paramValue} onChange={setParamValue} />
              <NumField
                id="cb-param-qualifier"
                label={t('cmd.qualifier')}
                value={paramQualifier}
                onChange={setParamQualifier}
                min={0}
                max={255}
              />
              <Button
                kind="primary"
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
            </div>
          </div>
        </AccordionItem>

        <AccordionItem title={t('cmd.file.title')} {...section('file')}>
          <div className="app-stack">
            <div style={{ maxWidth: 260 }}>
              <SelectField
                id="cb-file-action"
                label={t('cmd.file.title')}
                value={fileAction}
                onChange={(v) => setFileAction(v as FileAction)}
                options={[
                  { value: 'directory', label: t('cmd.file.directory') },
                  { value: 'select', label: t('cmd.file.select') },
                  { value: 'request', label: t('cmd.file.request') },
                ]}
              />
            </div>
            <div className="app-row" style={{ alignItems: 'flex-end' }}>
              <NumField id="cb-file-no" label={t('cmd.file.no')} value={fileName} onChange={setFileName} min={0} />
              <Button
                kind="secondary"
                disabled={noRun || noIoa || busy}
                onClick={() =>
                  void run(
                    t('cmd.file.label'),
                    file.mutateAsync({ action: fileAction, ioa, file_name: fileName }),
                  )
                }
              >
                {t('cmd.send')}
              </Button>
            </div>
            <div style={{ opacity: 0.75, fontSize: 12 }}>{t('cmd.file.hint')}</div>
          </div>
        </AccordionItem>
      </Accordion>
      </div>
    </Panel>
  )
}
