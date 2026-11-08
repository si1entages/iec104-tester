import { useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FlexItem,
  FormGroup,
  TextInput,
} from '@patternfly/react-core'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'

/** 0~100 的百分比输入 → 0~1 概率（T85 条件卡） */
const pctFields = [
  { key: 'loss_rate', label: 'bridge.loss' },
  { key: 'duplicate_rate', label: 'bridge.dup' },
  { key: 'corrupt_rate', label: 'bridge.corrupt' },
  { key: 'reorder_rate', label: 'bridge.reorder' },
  { key: 'disconnect_rate', label: 'bridge.disconnect' },
] as const

/** 桥网络条件卡（T85，PF）：与 CarbonConditionCard 同构. */
export function PfConditionCard() {
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
    <Card style={{ marginTop: 16 }}>
      <CardTitle>{t('bridge.conditionTitle')}</CardTitle>
      <CardBody>
        <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 12 }}>
          {t('bridge.conditionHint')}
        </div>
        {apply.error ? (
          <div role="alert" style={{ marginBottom: 12, fontSize: 13,
            color: 'var(--pf-t--global--text--color--status--danger--default)' }}>
            {apply.error instanceof Error ? apply.error.message : String(apply.error)}
          </div>
        ) : null}
        <Flex gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          {pctFields.map(({ key, label }) => (
            <FlexItem key={key}>
              <FormGroup label={t(label)} fieldId={`pf-cond-${key}`}>
                <TextInput id={`pf-cond-${key}`} type="number" min={0} max={100}
                           value={values[key] ?? '0'} onChange={(_e, v) => set(key, v)} />
              </FormGroup>
            </FlexItem>
          ))}
          <FlexItem>
            <FormGroup label={t('bridge.delay')} fieldId="pf-cond-delay">
              <TextInput id="pf-cond-delay" type="number" min={0} max={5000}
                         value={values.delay_ms ?? '0'} onChange={(_e, v) => set('delay_ms', v)} />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <Button variant="primary" onClick={doApply} isDisabled={apply.isPending}>
              {t('bridge.condApply')}
            </Button>
          </FlexItem>
          <FlexItem>
            <Button variant="secondary" onClick={doClear} isDisabled={apply.isPending}>
              {t('bridge.condClear')}
            </Button>
          </FlexItem>
        </Flex>
        {status?.condition_active ? (
          <div style={{ marginTop: 8, fontSize: 12 }}>
            {t('bridge.condActive')}: <span className="mono">{status.condition}</span>
          </div>
        ) : null}
        {injection && injection.total > 0 ? (
          <div style={{ marginTop: 12, fontSize: 12 }}>
            <div style={{ opacity: 0.75, marginBottom: 4 }}>{t('bridge.injTitle')}</div>
            {Object.entries(injection).map(([k, v]) => (
              <div key={k}>{k}: {v}</div>
            ))}
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}
