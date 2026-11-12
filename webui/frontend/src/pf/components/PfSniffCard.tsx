import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  Label,
} from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useT } from '../../i18n'
import { useSniffer } from '../../lib/useSniffer'

/** 旁路真实网卡抓包（WP9）：PF 版。 */
export function PfSniffCard() {
  const t = useT()
  const s = useSniffer()
  const cap = s.capability

  return (
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}
          flexWrap={{ default: 'wrap' }}>
          <span>{t('sniff.title')}</span>
          {s.running ? <Label isCompact color="green">{t('sniff.running')}</Label> : null}
          {cap && !cap.available ? (
            <Label isCompact color="grey">{t('sniff.unavailable')}</Label>
          ) : null}
          <Button variant="link" isInline size="sm" onClick={s.refresh}
            data-testid="sniff-refresh">{t('sniff.refresh')}</Button>
          <Button variant="primary" size="sm" isDisabled={s.busy || s.running}
            onClick={s.actions.start} data-testid="sniff-start">{t('sniff.start')}</Button>
          <Button variant="danger" size="sm" isDisabled={s.busy || !s.running}
            onClick={s.actions.stop} data-testid="sniff-stop">{t('sniff.stop')}</Button>
          <a href={api.sniff.exportUrl()} download>{t('sniff.export')}</a>
        </Flex>
      </CardTitle>
      <CardBody>
        <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 12 }}>{t('sniff.hint')}</div>

        {s.error ? (
          <div style={{ marginBottom: 8 }}>
            <Label isCompact color="red">{s.error}</Label>
          </div>
        ) : null}
        {cap && !cap.available ? (
          <div style={{ marginBottom: 8 }}>
            <Label isCompact color="orange">{cap.reason}</Label>
          </div>
        ) : null}
        {cap && cap.available && !s.running ? (
          <div style={{ marginBottom: 8 }}>
            <Label isCompact color="blue">{cap.reason}</Label>
          </div>
        ) : null}
        {s.stats?.last_error ? (
          <div style={{ marginBottom: 8 }}>
            <Label isCompact color="red">
              {t('sniff.lastError', { error: s.stats.last_error })}
            </Label>
          </div>
        ) : null}

        {s.stats ? (
          <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }}>
            {([
              ['sniff.stat.apdus', s.stats.apdus],
              ['sniff.stat.packets', s.stats.packets],
              ['sniff.stat.bytes', s.stats.bytes],
              ['sniff.stat.dropped', s.stats.dropped],
            ] as const).map(([k, v]) => (
              <div key={k} style={{
                border: '1px solid var(--pf-t--global--border--color--default)',
                borderRadius: 8, padding: '10px 14px', minWidth: 140,
              }}>
                <div style={{ fontSize: 12, opacity: 0.7 }}>{t(k)}</div>
                <div style={{ fontSize: 18, fontWeight: 600 }}>{v}</div>
              </div>
            ))}
          </Flex>
        ) : null}

        <div style={{ marginTop: 10, fontSize: 12, opacity: 0.7 }}>
          {t('sniff.footer', {
            frames: s.frames, port: s.status?.port ?? '-',
            backend: cap?.backend || t('sniff.noBackend'),
          })}
        </div>
      </CardBody>
    </Card>
  )
}
