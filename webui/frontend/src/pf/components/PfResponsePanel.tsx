import { useState } from 'react'

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
} from '@patternfly/react-core'

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
import { BoolField, NumField } from './PfField'

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
export function PfResponsePanel({ disabled = false }: Props) {
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
    isExpanded: Boolean(open[key]),
    onToggle: (_event: unknown, expanded: boolean) =>
      setOpen((prev) => ({ ...prev, [key]: expanded })),
  })

  return (
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          <span>{t('rp.title')}</span>
          {activeInjections.length === 0 ? (
            <Label isCompact color="green">
              {t('rp.normal')}
            </Label>
          ) : (
            activeInjections.map((item) => (
              <Label key={item} isCompact color="orange">
                {item}
              </Label>
            ))
          )}
        </Flex>
      </CardTitle>
      <CardBody>
        {disabled ? <Alert isInline variant="info" title={t('rp.slaveOff')} /> : null}
        {last ? (
          <Alert
            isInline
            variant={last.ok ? 'success' : 'danger'}
            title={last.text}
            style={{ marginTop: 8 }}
          />
        ) : null}
        <div style={{ fontSize: 12, opacity: 0.7, margin: '8px 0' }}>{t('rp.hint')}</div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <ExpandableSection toggleText={t('rp.group.errors')} {...section('errors')}>
            <Form onSubmit={(event) => event.preventDefault()}>
              <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }}>
                <BoolField
                  id="pf-rp-drop"
                  label={t('rp.toggle.dropFrames')}
                  value={cfg.errors.drop_frames}
                  onChange={(v) => patch('errors', 'drop_frames', v)}
                />
                <BoolField
                  id="pf-rp-wrongcot"
                  label={t('rp.toggle.wrongCot')}
                  hint={t('rp.toggle.wrongCotTitle')}
                  value={cfg.errors.wrong_cot}
                  onChange={(v) => patch('errors', 'wrong_cot', v)}
                />
                <BoolField
                  id="pf-rp-noresp"
                  label={t('rp.toggle.noResponse')}
                  value={cfg.errors.no_response}
                  onChange={(v) => patch('errors', 'no_response', v)}
                />
                <BoolField
                  id="pf-rp-corrupt"
                  label={t('rp.toggle.corrupt')}
                  value={cfg.errors.corrupt}
                  onChange={(v) => patch('errors', 'corrupt', v)}
                />
                <NumField
                  id="pf-rp-droprate"
                  label={t('rp.dropRate')}
                  value={cfg.errors.drop_rate}
                  onChange={(v) => patch('errors', 'drop_rate', Math.max(0, Math.min(1, v)))}
                  min={0}
                  max={1}
                  step={0.01}
                  width={150}
                />
              </Flex>
              <div style={{ fontSize: 12, opacity: 0.7 }}>{t('rp.dropRateHint')}</div>
            </Form>
          </ExpandableSection>

          <ExpandableSection toggleText={t('rp.group.delays')} {...section('delays')}>
            <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }}>
              <NumField
                id="pf-rp-d-command"
                label={t('rp.delay.command')}
                value={cfg.delays.command}
                onChange={(v) => patch('delays', 'command', Math.max(0, v))}
                min={0}
                step={0.1}
              />
              <NumField
                id="pf-rp-d-gi"
                label={t('rp.delay.gi')}
                value={cfg.delays.gi}
                onChange={(v) => patch('delays', 'gi', Math.max(0, v))}
                min={0}
                step={0.1}
              />
              <NumField
                id="pf-rp-d-data"
                label={t('rp.delay.data')}
                value={cfg.delays.data}
                onChange={(v) => patch('delays', 'data', Math.max(0, v))}
                min={0}
                step={0.1}
              />
            </Flex>
          </ExpandableSection>

          <ExpandableSection toggleText={t('rp.group.quality')} {...section('quality')}>
            <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }}>
              <BoolField
                id="pf-rp-q-iv"
                label={t('rp.q.invalid')}
                value={cfg.quality.invalid}
                onChange={(v) => patch('quality', 'invalid', v)}
              />
              <BoolField
                id="pf-rp-q-nt"
                label={t('rp.q.nt')}
                value={cfg.quality.not_topical}
                onChange={(v) => patch('quality', 'not_topical', v)}
              />
              <BoolField
                id="pf-rp-q-sb"
                label={t('rp.q.sb')}
                value={cfg.quality.substituted}
                onChange={(v) => patch('quality', 'substituted', v)}
              />
              <BoolField
                id="pf-rp-q-bl"
                label={t('rp.q.blocked')}
                value={cfg.quality.blocked}
                onChange={(v) => patch('quality', 'blocked', v)}
              />
              <BoolField
                id="pf-rp-q-ov"
                label={t('rp.q.ov')}
                value={cfg.quality.overflow}
                onChange={(v) => patch('quality', 'overflow', v)}
              />
            </Flex>
          </ExpandableSection>

          <ExpandableSection toggleText={t('rp.group.connection')} {...section('connection')}>
            <Form onSubmit={(event) => event.preventDefault()}>
              <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }}>
                <BoolField
                  id="pf-rp-c-reject"
                  label={t('rp.c.rejectStartdt')}
                  value={cfg.connection.reject_startdt}
                  onChange={(v) => patch('connection', 'reject_startdt', v)}
                />
                <BoolField
                  id="pf-rp-c-autostop"
                  label={t('rp.c.autoStopdt')}
                  value={cfg.connection.auto_stopdt}
                  onChange={(v) => patch('connection', 'auto_stopdt', v)}
                />
                <BoolField
                  id="pf-rp-c-testfr"
                  label={t('rp.c.sendTestfr')}
                  value={cfg.connection.send_testfr}
                  onChange={(v) => patch('connection', 'send_testfr', v)}
                />
                <FormGroup label={t('rp.c.testfrInterval')} fieldId="pf-rp-c-interval" style={{ maxWidth: 160 }}>
                  <FormSelect
                    id="pf-rp-c-interval"
                    value={String(cfg.connection.testfr_interval)}
                    onChange={(_e, v) => patch('connection', 'testfr_interval', Number(v))}
                    aria-label={t('rp.c.testfrInterval')}
                  >
                    {[5, 10, 15, 20, 30, 60].map((n) => (
                      <FormSelectOption key={n} value={String(n)} label={`${n}s`} />
                    ))}
                  </FormSelect>
                </FormGroup>
              </Flex>
            </Form>
          </ExpandableSection>
        </div>

        <ActionGroup>
          <Button
            variant="primary"
            isDisabled={disabled || apply.isPending}
            isLoading={apply.isPending}
            onClick={() => void send(cfg, t('rp.label.config'))}
          >
            {t('rp.apply')}
          </Button>
          <Button
            variant="secondary"
            isDisabled={disabled || apply.isPending}
            onClick={() => {
              const reset = structuredClone(DEFAULTS)
              setCfg(reset)
              void send(reset, t('rp.label.reset'))
            }}
          >
            {t('rp.resetApply')}
          </Button>
        </ActionGroup>
      </CardBody>
    </Card>
  )
}
