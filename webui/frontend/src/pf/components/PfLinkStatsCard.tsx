import {
  Card,
  CardBody,
  CardTitle,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Flex,
  Label,
} from '@patternfly/react-core'

import type { Status } from '../../api/types'
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'
import {
  lastErrorText, lastErrorWhen, linkCards, stateTone, timeline, timerRows,
} from '../../lib/linkPanel'

const LABEL_COLOR = {
  green: 'green', blue: 'blue', orange: 'orange', red: 'red', gray: 'grey',
} as const

/** 链路参数可观测面板（WP6）：PF 版。 */
export function PfLinkStatsCard({ status }: { status: Status | undefined }) {
  const t = useT()
  const link = status?.link
  if (!link) return null
  const st = link.state
  const tp = link.transport
  const cards = linkCards(status, (k) => t(k))
  const rows = timerRows((k) => t(k))
  const events = timeline(status, (k) => t(k))

  return (
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}
          flexWrap={{ default: 'wrap' }}>
          <span>{t('link.title')}</span>
          <Label isCompact color={st ? LABEL_COLOR[stateTone(st.state)] : 'grey'}>
            {st ? t(`link.state.${st.state}` as MessageKey) : t('link.noEngine')}
          </Label>
        </Flex>
      </CardTitle>
      <CardBody>
        <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 12 }}>{t('link.hint')}</div>

        {!st ? (
          <div style={{ marginBottom: 10 }}>
            <Label isCompact color="blue">{t('link.engineOff')}</Label>
          </div>
        ) : null}
        {tp?.last_error ? (
          <div style={{ marginBottom: 10 }}>
            <Label isCompact color="red">
              {t('link.lastError', {
                error: lastErrorText(status), when: lastErrorWhen(status),
              })}
            </Label>
          </div>
        ) : null}

        <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }} style={{ marginBottom: 14 }}>
          {cards.map((c) => (
            <div key={c.label as string} style={{
              border: '1px solid var(--pf-t--global--border--color--default)',
              borderRadius: 8, padding: '10px 14px', minWidth: 150,
            }}>
              <div style={{ fontSize: 12, opacity: 0.7 }}>{t(c.label)}</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: c.warn ? 'var(--pf-t--global--text--color--status--danger--default)' : undefined }}>
                {c.value}
              </div>
            </div>
          ))}
        </Flex>

        <Flex gap={{ default: 'gapLg' }} flexWrap={{ default: 'wrap' }}>
          <div style={{ minWidth: 260 }}>
            <DescriptionList isHorizontal isCompact>
              {rows.map((r) => (
                <DescriptionListGroup key={r.name}>
                  <DescriptionListTerm>{r.label}</DescriptionListTerm>
                  <DescriptionListDescription>
                    {st ? r.text(st.timers[r.name]) : '—'}
                  </DescriptionListDescription>
                </DescriptionListGroup>
              ))}
            </DescriptionList>
          </div>
          <div style={{ minWidth: 280, flex: '1 1 320px' }}>
            <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>{t('link.timeline')}</div>
            {events.length === 0 ? (
              <div style={{ fontSize: 12, opacity: 0.7 }}>{t('link.timelineEmpty')}</div>
            ) : (
              <ol style={{ margin: 0, paddingInlineStart: 18, fontSize: 12 }}>
                {events.map((e, i) => (
                  <li key={`${e.ts}-${i}`}>{e.ts} · {e.text}</li>
                ))}
              </ol>
            )}
          </div>
        </Flex>

        {tp ? (
          <div style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>
            {t('link.transportLine', {
              target: tp.target || '—',
              tls: tp.tls ? 'TLS' : t('link.plain'),
              interval: tp.reconnect_interval ? `${tp.reconnect_interval}s` : '—',
              ever: tp.ever_connected ? t('link.everYes') : t('link.everNo'),
            })}
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}