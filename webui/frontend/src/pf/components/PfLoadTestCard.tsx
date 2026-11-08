import { useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Flex,
  FlexItem,
  FormGroup,
  TextInput,
} from '@patternfly/react-core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { useT } from '../../i18n'
import { useUiStore } from '../../store/uiStore'

/**
 * 压测卡（T76，PF）：与 CarbonLoadTestCard 同构——仅双角色部署显示，
 * 状态运行中 1s 轮询，服务端业务错误显形。
 */
export function PfLoadTestCard() {
  const t = useT()
  const availableRoles = useUiStore((s) => s.availableRoles)
  const queryClient = useQueryClient()
  const isDual = availableRoles.includes('master') && availableRoles.includes('slave')

  const [duration, setDuration] = useState('60')
  const [eps, setEps] = useState('100')

  const st = useQuery({
    queryKey: ['loadtest'],
    queryFn: () => api.loadtest.status(),
    enabled: isDual,
    refetchInterval: (query) => ((query.state.data as { running?: boolean } | undefined)?.running
      ? 1000 : false),
  })
  const data = st.data as Record<string, unknown> | undefined
  const running = Boolean(data?.running)

  const start = useMutation({
    mutationFn: () =>
      api.loadtest.start({
        duration_s: Number(duration) || 60,
        events_per_s: Number(eps) || 100,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['loadtest'] })
    },
  })
  const stop = useMutation({
    mutationFn: () => api.loadtest.stop(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['loadtest'] })
    },
  })
  const busy = start.isPending || stop.isPending
  const err = start.error ?? stop.error
  const apiErr = (start.data && start.data.ok === false && start.data.error) as string | undefined

  if (!isDual) return null

  const summary = (data?.summary ?? null) as Record<string, unknown> | null
  const showError = err instanceof Error ? err.message : err != null ? String(err) : apiErr

  return (
    <Card style={{ marginTop: 16 }}>
      <CardTitle>{t('loadtest.title')}</CardTitle>
      <CardBody>
        <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 12 }}>
          {t('loadtest.hint')}
        </div>
        {showError ? (
          <div
            role="alert"
            style={{
              marginBottom: 12,
              padding: '8px 12px',
              borderRadius: 4,
              fontSize: 13,
              border: '1px solid var(--pf-t--global--color--status--danger--default)',
              color: 'var(--pf-t--global--text--color--status--danger--default)',
            }}
          >
            {showError}
          </div>
        ) : null}
        <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }}>
          <FormGroup label={t('loadtest.duration')} fieldId="pf-lt-dur">
            <TextInput id="pf-lt-dur" type="number" value={duration} isDisabled={running}
                       onChange={(_e, v) => setDuration(v)} />
          </FormGroup>
          <FormGroup label={t('loadtest.eps')} fieldId="pf-lt-eps">
            <TextInput id="pf-lt-eps" type="number" value={eps} isDisabled={running}
                       onChange={(_e, v) => setEps(v)} />
          </FormGroup>
          <FlexItem>
            <Button variant="primary" isDisabled={busy || running} onClick={() => start.mutate()}>
              {t('loadtest.start')}
            </Button>
          </FlexItem>
          <FlexItem>
            <Button variant="danger" isDisabled={busy || !running} onClick={() => stop.mutate()}>
              {t('loadtest.stop')}
            </Button>
          </FlexItem>
        </Flex>
        <DescriptionList isHorizontal columnModifier={{ default: '1Col', md: '2Col' }}
                         style={{ marginTop: 16 }}>
          {([
            ['loadtest.elapsed', data?.elapsed_s ?? '—'],
            ['loadtest.sent', data?.events_sent ?? '—'],
            ['loadtest.rx', data?.rx_frames ?? '—'],
            ['loadtest.fps', data?.fps ?? '—'],
          ] as const).map(([key, value]) => (
            <DescriptionListGroup key={key}>
              <DescriptionListTerm>{t(key)}</DescriptionListTerm>
              <DescriptionListDescription>{String(value)}</DescriptionListDescription>
            </DescriptionListGroup>
          ))}
        </DescriptionList>
        {summary ? (
          <div style={{ marginTop: 8, fontSize: 12, opacity: 0.8 }}>
            {t('loadtest.summary')}: {JSON.stringify(summary)}
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}
