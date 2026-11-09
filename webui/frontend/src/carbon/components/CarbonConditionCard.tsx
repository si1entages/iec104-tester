import { useState } from 'react'

import { Button } from '@carbon/react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import { KvList, Note, NumField, Panel } from './ui'

/** 0~100 的百分比输入 → 0~1 概率（T85 条件卡） */
const pctFields = [
  { key: 'loss_rate', label: 'bridge.loss' },
  { key: 'duplicate_rate', label: 'bridge.dup' },
  { key: 'corrupt_rate', label: 'bridge.corrupt' },
  { key: 'reorder_rate', label: 'bridge.reorder' },
  { key: 'disconnect_rate', label: 'bridge.disconnect' },
] as const

/**
 * 桥网络条件卡（T85）：把网络异常注入到转发路径，主动制造劣质链路。
 * 统计随 status 刷新（bridge-stats 节流事件），条件描述也由 status 带出。
 */
export function CarbonConditionCard() {
  const t = useT()
  const queryClient = useQueryClient()
  const { data: status } = useStatusQuery()
  const [values, setValues] = useState<Record<string, string>>({})

  const apply = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.bridge.condition(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['status'] })
    },
  })

  const set = (key: string, v: string): void => {
    setValues((prev) => ({ ...prev, [key]: v }))
  }

  const doApply = (): void => {
    const body: Record<string, unknown> = {}
    for (const { key } of pctFields) {
      body[key] = Math.min(100, Math.max(0, Number(values[key] ?? 0))) / 100
    }
    body.delay_ms = Math.max(0, Number(values.delay_ms ?? 0))
    body.active = true
    apply.mutate(body)
  }

  const doClear = (): void => {
    setValues({})
    apply.mutate({ active: false })
  }

  const injection = status?.injection as Record<string, number> | undefined

  return (
    <Panel title={t('bridge.conditionTitle')}>
      <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginBottom: 12 }}>
        {t('bridge.conditionHint')}
      </div>
      {apply.error ? (
        <Note kind="error" title={t('common.cmdFailed')} style={{ marginBottom: 12 }}>
          {apply.error instanceof Error ? apply.error.message : String(apply.error)}
        </Note>
      ) : null}
      <div className="app-row" style={{ alignItems: 'flex-end', flexWrap: 'wrap' }}>
        {pctFields.map(({ key, label }) => (
          <NumField
            key={key}
            id={`cb-cond-${key}`}
            label={t(label)}
            value={Number(values[key] ?? 0)}
            onChange={(v) => set(key, String(v))}
            width={130}
            min={0}
            max={100}
          />
        ))}
        <NumField
          id="cb-cond-delay"
          label={t('bridge.delay')}
          value={Number(values.delay_ms ?? 0)}
          onChange={(v) => set('delay_ms', String(v))}
          width={130}
          min={0}
          max={5000}
        />
        <Button kind="primary" size="sm" onClick={doApply} disabled={apply.isPending}>
          {t('bridge.condApply')}
        </Button>
        <Button kind="secondary" size="sm" onClick={doClear} disabled={apply.isPending}>
          {t('bridge.condClear')}
        </Button>
      </div>
      {status?.condition_active ? (
        <div style={{ marginTop: 8, fontSize: 12 }}>
          {t('bridge.condActive')}: <span className="mono">{status.condition}</span>
        </div>
      ) : null}
      {injection && injection.total > 0 ? (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginBottom: 4 }}>{t('bridge.injTitle')}</div>
          <KvList items={Object.entries(injection).map(([k, v]) => ({ term: k, value: v }))} />
        </div>
      ) : null}
    </Panel>
  )
}
