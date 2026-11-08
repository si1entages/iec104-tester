import { useState } from 'react'

import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  Form,
  FormGroup,
  FormSelect,
  FormSelectOption,
  TextInput,
} from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useCommand } from '../../api/queries'
import type { OkResponse } from '../../api/types'
import { useT } from '../../i18n'
import { NumField } from './PfField'

interface Props {
  disabled?: boolean
}

/** 测试注入：继保事件 M_EP（COT=3 突发）与成组单点 M_PS（1–8 位状态位串）。 */
export function PfTestInjectionPanel({ disabled = false }: Props) {
  const t = useT()
  const [epIoa, setEpIoa] = useState(5001)
  const [epValue, setEpValue] = useState('1')
  const [epWithTime, setEpWithTime] = useState(true)
  const [psIoa, setPsIoa] = useState(5101)
  const [psStates, setPsStates] = useState('1,0,1')
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const ep = useCommand(api.slave.ep)
  const ps = useCommand(api.slave.ps)

  const run = async (label: string, task: Promise<OkResponse>): Promise<void> => {
    const result = await task
    setLast(
      result.ok
        ? { ok: true, text: t('tip.sent', { label }) }
        : { ok: false, text: t('tip.failed', { label, error: result.error ?? t('cmd.unknown') }) },
    )
  }

  const sendEp = (): void => {
    void run(
      t('tip.epLabel'),
      ep.mutateAsync({ ioa: epIoa, event_value: Number(epValue) || 0, with_time: epWithTime }),
    )
  }

  const sendPs = (): void => {
    // 与旧页一致：仅接受 0/1，长度 1–8
    const states = psStates
      .split(/[,\s，]+/)
      .map(Number)
      .filter((v) => v === 0 || v === 1)
    if (states.length === 0 || states.length > 8) {
      setLast({ ok: false, text: t('tip.invalidStates') })
      return
    }
    void run(t('tip.psLabel', { n: states.length }), ps.mutateAsync({ ioa: psIoa, states }))
  }

  return (
    <Card>
      <CardTitle>{t('tip.title')}</CardTitle>
      <CardBody>
        {disabled ? <Alert isInline variant="info" title={t('tip.slaveOff')} /> : null}
        {last ? (
          <Alert
            isInline
            variant={last.ok ? 'success' : 'danger'}
            title={last.text}
            style={{ marginTop: 8 }}
          />
        ) : null}
        <div style={{ fontSize: 12, opacity: 0.7, margin: '8px 0' }}>{t('tip.hint')}</div>

        <Form onSubmit={(event) => event.preventDefault()}>
          <Flex gap={{ default: 'gapLg' }} flexWrap={{ default: 'wrap' }}>
            <div style={{ minWidth: 280, flex: 1 }}>
              <NumField id="pf-ep-ioa" label={t('tip.epIoa')} value={epIoa} onChange={setEpIoa} min={0} />
              <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }}>
                <FormGroup label={t('tip.epValue')} fieldId="pf-ep-value">
                  <FormSelect
                    id="pf-ep-value"
                    value={epValue}
                    onChange={(_e, v) => setEpValue(v)}
                    aria-label={t('tip.epValue')}
                  >
                    <FormSelectOption value="1" label="1" />
                    <FormSelectOption value="2" label="2" />
                    <FormSelectOption value="3" label="3" />
                  </FormSelect>
                </FormGroup>
                <FormGroup label={t('tip.withTime')} fieldId="pf-ep-time">
                  <FormSelect
                    id="pf-ep-time"
                    value={epWithTime ? 'yes' : 'no'}
                    onChange={(_e, v) => setEpWithTime(v === 'yes')}
                    aria-label={t('tip.withTime')}
                  >
                    <FormSelectOption value="yes" label={t('conn.on')} />
                    <FormSelectOption value="no" label={t('conn.off')} />
                  </FormSelect>
                </FormGroup>
              </Flex>
              <ActionGroup>
                <Button variant="primary" isDisabled={disabled || ep.isPending} onClick={sendEp}>
                  {t('tip.sendEp')}
                </Button>
              </ActionGroup>
            </div>

            <div style={{ minWidth: 280, flex: 1 }}>
              <NumField id="pf-ps-ioa" label={t('tip.psIoa')} value={psIoa} onChange={setPsIoa} min={0} />
              <FormGroup label={t('tip.psLabel', { n: psStates.split(',').filter(Boolean).length })} fieldId="pf-ps-states">
                <TextInput
                  id="pf-ps-states"
                  value={psStates}
                  onChange={(_e, v) => setPsStates(v)}
                  placeholder={t('tip.statesPlaceholder')}
                />
              </FormGroup>
              <ActionGroup>
                <Button variant="primary" isDisabled={disabled || ps.isPending} onClick={sendPs}>
                  {t('tip.sendPs')}
                </Button>
              </ActionGroup>
            </div>
          </Flex>
        </Form>
      </CardBody>
    </Card>
  )
}
