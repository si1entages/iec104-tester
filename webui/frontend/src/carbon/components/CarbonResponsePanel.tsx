import { useState } from 'react'

import { Accordion, AccordionItem, Button, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type {
  SlaveConnectionBehavior,
  SlaveDelays,
  SlaveErrors,
  SlaveQuality,
  SlaveResponseBehavior,
} from '../../api/types'
import { useT } from '../../i18n'
import { BoolField, Note, NumField, Panel, SelectField } from './ui'

type FullBehavior = {
  delays: Required<SlaveDelays>
  errors: Required<SlaveErrors>
  quality: Required<SlaveQuality>
  connection: Required<SlaveConnectionBehavior>
}

const DEFAULTS: FullBehavior = {
  delays: { gi: 0, command: 0, data: 0 },
  errors: { drop_frames: false, drop_rate: 0, corrupt: false, no_response: false, wrong_cot: false },
  quality: { invalid: false, blocked: false, substituted: false, not_topical: false, overflow: false },
  connection: { reject_startdt: false, auto_stopdt: false, send_testfr: false, testfr_interval: 20 },
}

type Group = keyof FullBehavior

interface Props {
  disabled?: boolean
}

/** 子站应答行为：延迟 / 错误注入 / 品质注入（5 位）/ 连接行为。 */
export function CarbonResponsePanel({ disabled = false }: Props) {
  const t = useT()
  const [cfg, setCfg] = useState<FullBehavior>(() => structuredClone(DEFAULTS))
  const [open, setOpen] = useState<Record<string, boolean>>({ errors: true })
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const apply = useCommand(api.slave.response)

  const patch = <G extends Group>(group: G, key: keyof FullBehavior[G], value: unknown): void => {
    setCfg((prev) => {
      const next = { ...(prev[group] as Record<string, unknown>), [key as string]: value }
      return { ...prev, [group]: next } as FullBehavior
    })
  }

  const send = async (payload: SlaveResponseBehavior, label: string): Promise<void> => {
    const result = await apply.mutateAsync(payload as Record<string, unknown>)
    setLast(
      result.ok
        ? { ok: true, text: t('rp.applied', { label }) }
        : { ok: false, text: t('rp.failed', { label, error: result.error ?? t('cmd.unknown') }) },
    )
  }

  const activeInjections: string[] = []
  if (cfg.errors.wrong_cot) activeInjections.push(t('rp.inj.wrongCot'))
  if (cfg.errors.no_response) activeInjections.push(t('rp.inj.noResponse'))
  if (cfg.errors.corrupt) activeInjections.push(t('rp.inj.corrupt'))
  if (cfg.errors.drop_frames) activeInjections.push(t('rp.inj.drop'))
  if (cfg.errors.drop_rate > 0) activeInjections.push(t('rp.inj.dropRate', { n: cfg.errors.drop_rate }))

  const section = (key: string) => ({
    open: Boolean(open[key]),
    onHeadingClick: ({ isOpen }: { isOpen: boolean }) =>
      setOpen((prev) => ({ ...prev, [key]: isOpen })),
  })

  return (
    <Panel
      title={
        <span className="app-row">
          {t('rp.title')}
          {activeInjections.length === 0 ? (
            <Tag size="sm" type="green">
              {t('rp.normal')}
            </Tag>
          ) : (
            activeInjections.map((item) => (
              <Tag key={item} size="sm" type="magenta">
                {item}
              </Tag>
            ))
          )}
        </span>
      }
    >
      {disabled ? <Note kind="info" title={t('rp.slaveOff')} /> : null}
      {last ? <Note kind={last.ok ? 'success' : 'error'} title={last.text} style={{ marginTop: 8 }} /> : null}
      <div style={{ fontSize: 12, opacity: 0.7, margin: '8px 0' }}>{t('rp.hint')}</div>

      <Accordion>
        <AccordionItem title={t('rp.group.errors')} {...section('errors')}>
          <div className="app-row" style={{ alignItems: 'flex-start' }}>
            <BoolField
              id="cb-rp-drop"
              label={t('rp.toggle.dropFrames')}
              value={cfg.errors.drop_frames}
              onChange={(v) => patch('errors', 'drop_frames', v)}
            />
            <BoolField
              id="cb-rp-wrongcot"
              label={t('rp.toggle.wrongCot')}
              hint={t('rp.toggle.wrongCotTitle')}
              value={cfg.errors.wrong_cot}
              onChange={(v) => patch('errors', 'wrong_cot', v)}
            />
            <BoolField
              id="cb-rp-noresp"
              label={t('rp.toggle.noResponse')}
              value={cfg.errors.no_response}
              onChange={(v) => patch('errors', 'no_response', v)}
            />
            <BoolField
              id="cb-rp-corrupt"
              label={t('rp.toggle.corrupt')}
              value={cfg.errors.corrupt}
              onChange={(v) => patch('errors', 'corrupt', v)}
            />
            <NumField
              id="cb-rp-droprate"
              label={t('rp.dropRate')}
              value={cfg.errors.drop_rate}
              onChange={(v) => patch('errors', 'drop_rate', Math.max(0, Math.min(1, v)))}
              min={0}
              max={1}
              step={0.01}
              width={150}
            />
          </div>
          <div style={{ fontSize: 12, opacity: 0.7 }}>{t('rp.dropRateHint')}</div>
        </AccordionItem>

        <AccordionItem title={t('rp.group.delays')} {...section('delays')}>
          <div className="app-row" style={{ alignItems: 'flex-end' }}>
            <NumField
              id="cb-rp-d-command"
              label={t('rp.delay.command')}
              value={cfg.delays.command}
              onChange={(v) => patch('delays', 'command', Math.max(0, v))}
              min={0}
              step={0.1}
            />
            <NumField
              id="cb-rp-d-gi"
              label={t('rp.delay.gi')}
              value={cfg.delays.gi}
              onChange={(v) => patch('delays', 'gi', Math.max(0, v))}
              min={0}
              step={0.1}
            />
            <NumField
              id="cb-rp-d-data"
              label={t('rp.delay.data')}
              value={cfg.delays.data}
              onChange={(v) => patch('delays', 'data', Math.max(0, v))}
              min={0}
              step={0.1}
            />
          </div>
        </AccordionItem>

        <AccordionItem title={t('rp.group.quality')} {...section('quality')}>
          <div className="app-row" style={{ alignItems: 'flex-start' }}>
            <BoolField
              id="cb-rp-q-iv"
              label={t('rp.q.invalid')}
              value={cfg.quality.invalid}
              onChange={(v) => patch('quality', 'invalid', v)}
            />
            <BoolField
              id="cb-rp-q-nt"
              label={t('rp.q.nt')}
              value={cfg.quality.not_topical}
              onChange={(v) => patch('quality', 'not_topical', v)}
            />
            <BoolField
              id="cb-rp-q-sb"
              label={t('rp.q.sb')}
              value={cfg.quality.substituted}
              onChange={(v) => patch('quality', 'substituted', v)}
            />
            <BoolField
              id="cb-rp-q-bl"
              label={t('rp.q.blocked')}
              value={cfg.quality.blocked}
              onChange={(v) => patch('quality', 'blocked', v)}
            />
            <BoolField
              id="cb-rp-q-ov"
              label={t('rp.q.ov')}
              value={cfg.quality.overflow}
              onChange={(v) => patch('quality', 'overflow', v)}
            />
          </div>
        </AccordionItem>

        <AccordionItem title={t('rp.group.connection')} {...section('connection')}>
          <div className="app-row" style={{ alignItems: 'flex-end' }}>
            <BoolField
              id="cb-rp-c-reject"
              label={t('rp.c.rejectStartdt')}
              value={cfg.connection.reject_startdt}
              onChange={(v) => patch('connection', 'reject_startdt', v)}
            />
            <BoolField
              id="cb-rp-c-autostop"
              label={t('rp.c.autoStopdt')}
              value={cfg.connection.auto_stopdt}
              onChange={(v) => patch('connection', 'auto_stopdt', v)}
            />
            <BoolField
              id="cb-rp-c-testfr"
              label={t('rp.c.sendTestfr')}
              value={cfg.connection.send_testfr}
              onChange={(v) => patch('connection', 'send_testfr', v)}
            />
            <SelectField
              id="cb-rp-c-interval"
              label={t('rp.c.testfrInterval')}
              width={160}
              value={String(cfg.connection.testfr_interval)}
              onChange={(v) => patch('connection', 'testfr_interval', Number(v))}
              options={[5, 10, 15, 20, 30, 60].map((n) => ({ value: String(n), label: `${n}s` }))}
            />
          </div>
        </AccordionItem>
      </Accordion>

      <div className="app-row" style={{ marginTop: 12 }}>
        <Button
          kind="primary"
          disabled={disabled || apply.isPending}
          onClick={() => void send(cfg, t('rp.label.config'))}
        >
          {t('rp.apply')}
        </Button>
        <Button
          kind="secondary"
          disabled={disabled || apply.isPending}
          onClick={() => {
            const reset = structuredClone(DEFAULTS)
            setCfg(reset)
            void send(reset, t('rp.label.reset'))
          }}
        >
          {t('rp.resetApply')}
        </Button>
      </div>
    </Panel>
  )
}
