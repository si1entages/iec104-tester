import { useState } from 'react'

import { ExperimentOutlined } from '@ant-design/icons'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Collapse,
  Divider,
  InputNumber,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'

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

/** 面板内部使用：四组配置均填满（缺省值取后端 `ResponseBehavior` 默认） */
type FullBehavior = {
  delays: Required<SlaveDelays>
  errors: Required<SlaveErrors>
  quality: Required<SlaveQuality>
  connection: Required<SlaveConnectionBehavior>
}

/** 后端 `ResponseBehavior` 的默认值（`core/engine/slave_response.py`） */
const DEFAULTS: FullBehavior = {
  delays: { gi: 0, command: 0, data: 0 },
  errors: { drop_frames: false, drop_rate: 0, corrupt: false, no_response: false, wrong_cot: false },
  quality: { invalid: false, blocked: false, substituted: false, not_topical: false, overflow: false },
  connection: { reject_startdt: false, auto_stopdt: false, send_testfr: false, testfr_interval: 20 },
}

interface Props {
  disabled?: boolean
}

interface ToggleProps {
  label: string
  /** 悬浮解释（用于说明该注入项对主站的影响） */
  title?: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}

function Toggle({ label, title, checked, onChange, disabled }: ToggleProps) {
  return (
    <span title={title}>
      <Switch
        size="small"
        aria-label={label}
        checked={checked}
        disabled={disabled}
        onChange={onChange}
      />{' '}
      <Typography.Text style={{ fontSize: 12 }}>{label}</Typography.Text>
    </span>
  )
}

/**
 * 应答行为配置（T13）：对接 `POST /api/slave/response`（`set_response_behavior`）。
 *
 * 覆盖 `ResponseBehavior` 全部四组：延迟 / 错误注入 / 品质注入 / 连接行为。
 * 其中「返回错误 COT」（`errors.wrong_cot`）、「丢帧比例」（`errors.drop_rate`）、
 * 「命令延时」（`delays.command`）保留自旧原生子站页（`#wrong-cot` / `#drop-rate` /
 * `#cmd-delay`），是主站严格性校验的关键注入项。
 *
 * 注意：契约只提供写入端点（无 GET），因此面板显示的「当前配置」是**本会话最后
 * 一次成功下发的配置**，不是从后端读回的状态；重启后端后需重新应用。
 */
export function ResponsePanel({ disabled = false }: Props) {
  const t = useT()
  const { message } = AntdApp.useApp()
  const [cfg, setCfg] = useState<FullBehavior>(() => structuredClone(DEFAULTS))
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const apply = useCommand(api.slave.response)

  const patch = <G extends keyof FullBehavior>(
    group: G,
    key: keyof FullBehavior[G],
    value: unknown,
  ): void => {
    setCfg((prev) => {
      const group$ = { ...(prev[group] as Record<string, unknown>), [key as string]: value }
      return { ...prev, [group]: group$ } as FullBehavior
    })
  }

  const send = async (payload: SlaveResponseBehavior, label: string): Promise<void> => {
    const result = await apply.mutateAsync(payload as Record<string, unknown>)
    const text = result.ok
      ? t('rp.applied', { label })
      : t('rp.failed', { label, error: result.error ?? t('cmd.unknown') })
    if (result.ok) {
      setLast({ ok: true, text })
      message.success(text)
    } else {
      setLast({ ok: false, text })
      message.error(text)
    }
  }

  const activeInjections: string[] = []
  if (cfg.errors.wrong_cot) activeInjections.push(t('rp.inj.wrongCot'))
  if (cfg.errors.no_response) activeInjections.push(t('rp.inj.noResponse'))
  if (cfg.errors.corrupt) activeInjections.push(t('rp.inj.corrupt'))
  if (cfg.errors.drop_frames) activeInjections.push(t('rp.inj.drop'))
  if (cfg.errors.drop_rate > 0) {
    activeInjections.push(t('rp.inj.dropRate', { n: cfg.errors.drop_rate }))
  }

  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <ExperimentOutlined />
          <span>{t('rp.title')}</span>
          {activeInjections.length > 0 ? (
            <Tag color="warning">{activeInjections.join(' / ')}</Tag>
          ) : (
            <Tag color="green">{t('rp.normal')}</Tag>
          )}
        </Space>
      }
      styles={{ body: { maxHeight: 620, overflowY: 'auto' } }}
    >
      <Space orientation="vertical" size={10} style={{ width: '100%' }}>
        {disabled ? <Alert type="info" showIcon title={t('rp.slaveOff')} /> : null}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {t('rp.hint')}
        </Typography.Text>

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
          bordered={false}
          defaultActiveKey={['errors']}
          style={{ background: 'transparent' }}
          items={[
            {
              key: 'errors',
              label: t('rp.group.errors'),
              children: (
                <Space orientation="vertical" size={8} style={{ width: '100%' }}>
                  <Space wrap size={16}>
                    <Toggle
                      label={t('rp.toggle.dropFrames')}
                      checked={cfg.errors.drop_frames}
                      onChange={(v) => patch('errors', 'drop_frames', v)}
                    />
                    <Toggle
                      label={t('rp.toggle.wrongCot')}
                      title={t('rp.toggle.wrongCotTitle')}
                      checked={cfg.errors.wrong_cot}
                      onChange={(v) => patch('errors', 'wrong_cot', v)}
                    />
                  </Space>
                  <Space wrap size={16}>
                    <Toggle
                      label={t('rp.toggle.noResponse')}
                      checked={cfg.errors.no_response}
                      onChange={(v) => patch('errors', 'no_response', v)}
                    />
                    <Toggle
                      label={t('rp.toggle.corrupt')}
                      checked={cfg.errors.corrupt}
                      onChange={(v) => patch('errors', 'corrupt', v)}
                    />
                  </Space>
                  <Space wrap>
                    <span style={{ fontSize: 12 }}>{t('rp.dropRate')}</span>
                    <InputNumber
                      min={0}
                      max={1}
                      step={0.05}
                      style={{ width: 140 }}
                      value={cfg.errors.drop_rate}
                      onChange={(v) => patch('errors', 'drop_rate', Math.max(0, Math.min(1, Number(v ?? 0))))}
                    />
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {t('rp.dropRateHint')}
                    </Typography.Text>
                  </Space>
                </Space>
              ),
            },
            {
              key: 'delays',
              label: t('rp.group.delays'),
              children: (
                <Space orientation="vertical" size={8} style={{ width: '100%' }}>
                  <Space wrap>
                    <span style={{ fontSize: 12 }}>{t('rp.delay.command')}</span>
                    <InputNumber
                      min={0}
                      max={60}
                      step={0.1}
                      style={{ width: 160 }}
                      value={cfg.delays.command}
                      onChange={(v) => patch('delays', 'command', Math.max(0, Number(v ?? 0)))}
                    />
                    <span style={{ fontSize: 12 }}>{t('rp.delay.gi')}</span>
                    <InputNumber
                      min={0}
                      max={60}
                      step={0.1}
                      style={{ width: 160 }}
                      value={cfg.delays.gi}
                      onChange={(v) => patch('delays', 'gi', Math.max(0, Number(v ?? 0)))}
                    />
                    <span style={{ fontSize: 12 }}>{t('rp.delay.data')}</span>
                    <InputNumber
                      min={0}
                      max={60}
                      step={0.1}
                      style={{ width: 160 }}
                      value={cfg.delays.data}
                      onChange={(v) => patch('delays', 'data', Math.max(0, Number(v ?? 0)))}
                    />
                  </Space>
                </Space>
              ),
            },
            {
              key: 'quality',
              label: t('rp.group.quality'),
              children: (
                <Space wrap size={16}>
                  <Toggle
                    label={t('rp.q.invalid')}
                    checked={cfg.quality.invalid}
                    onChange={(v) => patch('quality', 'invalid', v)}
                  />
                  <Toggle
                    label={t('rp.q.blocked')}
                    checked={cfg.quality.blocked}
                    onChange={(v) => patch('quality', 'blocked', v)}
                  />
                  <Toggle
                    label={t('rp.q.nt')}
                    checked={cfg.quality.not_topical}
                    onChange={(v) => patch('quality', 'not_topical', v)}
                  />
                  <Toggle
                    label={t('rp.q.ov')}
                    checked={cfg.quality.overflow}
                    onChange={(v) => patch('quality', 'overflow', v)}
                  />
                </Space>
              ),
            },
            {
              key: 'connection',
              label: t('rp.group.connection'),
              children: (
                <Space orientation="vertical" size={8} style={{ width: '100%' }}>
                  <Space wrap size={16}>
                    <Toggle
                      label={t('rp.c.rejectStartdt')}
                      checked={cfg.connection.reject_startdt}
                      onChange={(v) => patch('connection', 'reject_startdt', v)}
                    />
                    <Toggle
                      label={t('rp.c.autoStopdt')}
                      checked={cfg.connection.auto_stopdt}
                      onChange={(v) => patch('connection', 'auto_stopdt', v)}
                    />
                    <Toggle
                      label={t('rp.c.sendTestfr')}
                      checked={cfg.connection.send_testfr}
                      onChange={(v) => patch('connection', 'send_testfr', v)}
                    />
                  </Space>
                  <Space wrap>
                    <span style={{ fontSize: 12 }}>{t('rp.c.testfrInterval')}</span>
                    <InputNumber
                      min={5}
                      max={600}
                      step={1}
                      style={{ width: 160 }}
                      value={cfg.connection.testfr_interval}
                      onChange={(v) => patch('connection', 'testfr_interval', Number(v ?? 20))}
                    />
                  </Space>
                </Space>
              ),
            },
          ]}
        />

        <Space wrap>
          <Button
            type="primary"
            loading={apply.isPending}
            onClick={() => void send(cfg, t('rp.label.config'))}
          >
            {t('rp.apply')}
          </Button>
          <Button
            onClick={() => {
              const reset = structuredClone(DEFAULTS)
              setCfg(reset)
              void send(reset, t('rp.label.reset'))
            }}
          >
            {t('rp.resetApply')}
          </Button>
        </Space>
      </Space>
    </Card>
  )
}
