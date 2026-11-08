import { useState } from 'react'

import { InfoCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { Alert, App as AntdApp, Button, Card, InputNumber, Segmented, Space, Tag, Tooltip, Typography } from 'antd'

import { api } from '../../api/endpoints'
import { useCommand, useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { useT } from '../../i18n'

interface Props {
  disabled?: boolean
  /** 点表当前选中行：scope=selected 时的 YX/YC 模拟目标（类型须匹配） */
  selected?: Point | null
}

type Scope = 'all' | 'selected'

/**
 * 模拟控制（T13）：对接 `POST /api/slave/sim`（后端 `start_simulation` / `stop_simulation`）。
 *
 * 第二批体验改造 ⑤：
 * - YX / YC 各自支持「全部点 / 选中点」两种范围模式（scope）；
 * - YC 取值改为**点表量程内随机**（[min, max] 均匀随机）；点表未声明量程的点
 *   回落「当前值 ± 浮动比例」（yc_change_range 仅对这些点生效）；
 * - `yx_change_rate` 语义为「每周期翻转概率」（0~1，每周期对范围内每点独立判定）。
 * 手动置数走独立的「手动置数」页签（ManualSetPanel），本面板不再有模式单选。
 */
export function SimulationPanel({ disabled = false, selected = null }: Props) {
  const t = useT()
  const { message } = AntdApp.useApp()
  const { data: status } = useStatusQuery()
  const backendOn = Boolean(status?.simulation)

  const [yxInterval, setYxInterval] = useState(5)
  const [ycInterval, setYcInterval] = useState(2)
  const [yxChangeRate, setYxChangeRate] = useState(0.1)
  const [ycChangeRange, setYcChangeRange] = useState(0.05)
  const [yxScope, setYxScope] = useState<Scope>('all')
  const [ycScope, setYcScope] = useState<Scope>('all')
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const sim = useCommand(api.slave.sim)

  const send = async (on: boolean): Promise<void> => {
    if (on) {
      if (yxScope === 'selected' && selected?.type !== 'YX') {
        message.warning(t('simPanel.needYx'))
        return
      }
      if (ycScope === 'selected' && selected?.type !== 'YC') {
        message.warning(t('simPanel.needYc'))
        return
      }
    }
    const result = await sim.mutateAsync({
      enabled: on,
      ...(on
        ? {
            yx_interval: yxInterval,
            yc_interval: ycInterval,
            yx_change_rate: yxChangeRate,
            yc_change_range: ycChangeRange,
            yx_scope: yxScope,
            yc_scope: ycScope,
            ...(yxScope === 'selected' && selected?.type === 'YX' ? { yx_ioas: [selected.ioa] } : {}),
            ...(ycScope === 'selected' && selected?.type === 'YC' ? { yc_ioas: [selected.ioa] } : {}),
          }
        : {}),
    })
    if (result.ok) {
      setLast({ ok: true, text: on ? t('simPanel.started') : t('simPanel.stopped') })
      message.success(on ? t('simPanel.started') : t('simPanel.stopped'))
    } else {
      const text = t('simPanel.failed', { error: result.error ?? t('cmd.unknown') })
      setLast({ ok: false, text })
      message.error(text)
    }
  }

  const noRun = disabled

  return (
    <Card
      size="small"
      title={
        <Space>
          <ThunderboltOutlined />
          <span>{t('simPanel.title')}</span>
          <Tag color={backendOn ? 'green' : 'default'}>
            {backendOn ? t('simPanel.running') : t('simPanel.idle')}
          </Tag>
        </Space>
      }
    >
      <Space orientation="vertical" size={10} style={{ width: '100%' }}>
        {disabled ? <Alert type="info" showIcon title={t('simPanel.slaveOff')} /> : null}
        {last ? (
          <Alert
            type={last.ok ? 'success' : 'error'}
            showIcon
            title={last.text}
            closable
            onClose={() => setLast(null)}
          />
        ) : null}

        <Space wrap>
          <span style={{ fontSize: 12 }}>{t('simPanel.yxInterval')}</span>
          <InputNumber
            min={0.1}
            max={600}
            step={0.5}
            style={{ width: 130 }}
            value={yxInterval}
            onChange={(v) => setYxInterval(Math.max(0.1, Number(v ?? 5)))}
          />
          <span style={{ fontSize: 12 }}>{t('simPanel.ycInterval')}</span>
          <InputNumber
            min={0.1}
            max={600}
            step={0.5}
            style={{ width: 130 }}
            value={ycInterval}
            onChange={(v) => setYcInterval(Math.max(0.1, Number(v ?? 2)))}
          />
        </Space>

        <Space wrap>
          <span style={{ fontSize: 12 }}>{t('simPanel.yxScope')}</span>
          <Segmented
            size="small"
            options={[
              { value: 'all', label: t('simPanel.scope.all') },
              { value: 'selected', label: t('simPanel.scope.selected') },
            ]}
            value={yxScope}
            onChange={(v) => setYxScope(v as Scope)}
          />
          <Tooltip title={t('simPanel.rateTip')}>
            <span style={{ fontSize: 12 }}>
              {t('simPanel.rate')} <InfoCircleOutlined style={{ color: 'inherit', opacity: 0.6 }} />
            </span>
          </Tooltip>
          <InputNumber
            min={0}
            max={1}
            step={0.05}
            style={{ width: 110 }}
            value={yxChangeRate}
            onChange={(v) => setYxChangeRate(Math.max(0, Math.min(1, Number(v ?? 0.1))))}
          />
        </Space>

        <Space wrap>
          <span style={{ fontSize: 12 }}>{t('simPanel.ycScope')}</span>
          <Segmented
            size="small"
            options={[
              { value: 'all', label: t('simPanel.scope.all') },
              { value: 'selected', label: t('simPanel.scope.selected') },
            ]}
            value={ycScope}
            onChange={(v) => setYcScope(v as Scope)}
          />
          <Tooltip title={t('simPanel.rangeTip')}>
            <span style={{ fontSize: 12 }}>
              {t('simPanel.range')} <InfoCircleOutlined style={{ color: 'inherit', opacity: 0.6 }} />
            </span>
          </Tooltip>
          <InputNumber
            min={0}
            step={0.01}
            style={{ width: 110 }}
            value={ycChangeRange}
            onChange={(v) => setYcChangeRange(Math.max(0, Number(v ?? 0.05)))}
          />
        </Space>

        {selected && (yxScope === 'selected' || ycScope === 'selected') ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('simPanel.selectedInfo', {
              key: `${selected.type}-${selected.ioa}`,
              name: selected.name,
            })}
            {((yxScope === 'selected' && selected.type !== 'YX') ||
              (ycScope === 'selected' && selected.type !== 'YC')) ? (
              <Typography.Text type="warning" style={{ fontSize: 12 }}>
                {t('simPanel.mismatch')}
              </Typography.Text>
            ) : null}
          </Typography.Text>
        ) : null}

        <Space wrap>
          <Button
            type="primary"
            loading={sim.isPending}
            disabled={noRun}
            onClick={() => void send(!backendOn)}
          >
            {backendOn ? t('simPanel.stop') : t('simPanel.start')}
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('simPanel.hint')}
          </Typography.Text>
        </Space>
      </Space>
    </Card>
  )
}
