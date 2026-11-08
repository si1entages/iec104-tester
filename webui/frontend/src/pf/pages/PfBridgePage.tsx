import { useEffect, useState } from 'react'

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
  Form,
  FormGroup,
  Label,
  PageSection,
  TextInput,
} from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import { PfFrameViewer } from '../components/PfFrameViewer'

/**
 * 桥接观察页（T74，bridge 角色专用）：与 CarbonBridgePage 同构——
 * 桥接配置启停 + 运行统计 + 实时报文（复用 PfFrameViewer 的 WS 帧缓存）。
 */
export function PfBridgePage() {
  const t = useT()
  const { data: status } = useStatusQuery()
  const running = Boolean(status?.running)
  const started = Boolean(status?.started)
  const stats = status?.bridge_stats

  const [listenHost, setListenHost] = useState('0.0.0.0')
  const [listenPort, setListenPort] = useState('2404')
  const [upHost, setUpHost] = useState('127.0.0.1')
  const [upPort, setUpPort] = useState('2404')

  // 仅在运行态变化时回填一次表单（避免逐秒打字被 status 刷新覆盖）
  useEffect(() => {
    if (!status) return
    const cfg = status.bridge_cfg
    if (cfg) {
      setListenHost(cfg.listen_host ?? '0.0.0.0')
      setListenPort(String(cfg.listen_port ?? 2404))
      setUpHost(cfg.upstream_host ?? '127.0.0.1')
      setUpPort(String(cfg.upstream_port ?? 2404))
    } else {
      if (status.host) setUpHost(status.host)
      if (status.port) setUpPort(String(status.port))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.running])

  const start = useCommand(api.bridge.start)
  const stop = useCommandNoArgs(api.bridge.stop)
  const busy = start.isPending || stop.isPending
  const err = start.error ?? stop.error
  // 业务层失败（ok:false，如端口被占）：useCommand 只捕获网络/契约异常
  const [apiError, setApiError] = useState('')
  const showError = err instanceof Error ? err.message : err != null ? String(err) : apiError

  const doStart = (): void => {
    setApiError('')
    start.mutate(
      {
        listen_host: listenHost.trim() || '0.0.0.0',
        listen_port: Number(listenPort) || 2404,
        upstream_host: upHost.trim() || '127.0.0.1',
        upstream_port: Number(upPort) || 2404,
      },
      { onSuccess: (r) => setApiError(r.ok ? '' : (r.error ?? t('common.cmdFailed'))) },
    )
  }

  return (
    <>
      <PageSection variant="secondary">
        <Card>
          <CardTitle>
            <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
              <FlexItem>{t('bridge.cfgTitle')}</FlexItem>
              <FlexItem>
                <Label isCompact color={running ? 'green' : 'grey'}>
                  {running ? t('conn.connected') : t('conn.disconnected')}
                </Label>
              </FlexItem>
            </Flex>
          </CardTitle>
          <CardBody>
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
            <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 12 }}>{t('bridge.hint')}</div>
            <Form onSubmit={(e) => e.preventDefault()}>
              <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }}>
                <FormGroup label={t('bridge.listenHost')} fieldId="pf-br-lh">
                  <TextInput id="pf-br-lh" value={listenHost} isDisabled={running}
                             onChange={(_e, v) => setListenHost(v)} />
                </FormGroup>
                <FormGroup label={t('bridge.listenPort')} fieldId="pf-br-lp">
                  <TextInput id="pf-br-lp" type="number" value={listenPort} isDisabled={running}
                             onChange={(_e, v) => setListenPort(v)} />
                </FormGroup>
                <FormGroup label={t('bridge.upstreamHost')} fieldId="pf-br-uh">
                  <TextInput id="pf-br-uh" value={upHost} isDisabled={running}
                             onChange={(_e, v) => setUpHost(v)} />
                </FormGroup>
                <FormGroup label={t('bridge.upstreamPort')} fieldId="pf-br-up">
                  <TextInput id="pf-br-up" type="number" value={upPort} isDisabled={running}
                             onChange={(_e, v) => setUpPort(v)} />
                </FormGroup>
              </Flex>
              <Flex gap={{ default: 'gapSm' }} style={{ marginTop: 12 }}>
                <Button variant="primary" isDisabled={busy || running} onClick={doStart}>
                  {t('bridge.start')}
                </Button>
                <Button variant="danger" isDisabled={busy || !started}
                        onClick={() => { setApiError(''); stop.mutate(undefined, { onSuccess: (r: { ok: boolean; error?: string }) => setApiError(r.ok ? '' : (r.error ?? '')) }) }}>
                  {t('bridge.stop')}
                </Button>
              </Flex>
            </Form>
          </CardBody>
        </Card>
      </PageSection>

      <PageSection>
        <Card>
          <CardTitle>{t('bridge.statsTitle')}</CardTitle>
          <CardBody>
            <DescriptionList isHorizontal isFluid columnModifier={{ default: '1Col', md: '2Col' }}>
              {([
                ['bridge.statsFramesDn', stats?.frames_dn ?? 0],
                ['bridge.statsFramesUp', stats?.frames_up ?? 0],
                ['bridge.statsBytesDn', stats?.bytes_dn ?? 0],
                ['bridge.statsBytesUp', stats?.bytes_up ?? 0],
                ['bridge.statsClients', stats?.clients_total ?? 0],
                ['bridge.statsResyncs', stats?.resyncs ?? 0],
                ['bridge.statsUpstreamErrors', stats?.upstream_errors ?? 0],
              ] as const).map(([key, value]) => (
                <DescriptionListGroup key={key}>
                  <DescriptionListTerm>{t(key)}</DescriptionListTerm>
                  <DescriptionListDescription>
                    {value.toLocaleString()}
                  </DescriptionListDescription>
                </DescriptionListGroup>
              ))}
            </DescriptionList>
          </CardBody>
        </Card>
      </PageSection>

      {status?.compliance ? (
        <PageSection>
          <Card>
            <CardTitle>{t('compliance.title')}</CardTitle>
            <CardBody>
              <DescriptionList isHorizontal columnModifier={{ default: '1Col', md: '2Col' }}>
                <DescriptionListGroup>
                  <DescriptionListTerm>{t('compliance.total')}</DescriptionListTerm>
                  <DescriptionListDescription>{String(status.compliance.violation_total ?? 0)}</DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>{t('compliance.frames')}</DescriptionListTerm>
                  <DescriptionListDescription>{String(status.compliance.frames_seen ?? 0)}</DescriptionListDescription>
                </DescriptionListGroup>
              </DescriptionList>
              {status.compliance.violations && status.compliance.violations.length > 0 ? (
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 4 }}>
                    {t('compliance.violations')}
                  </div>
                  {status.compliance.violations.map((v, i) => (
                    <div key={i} style={{ fontSize: 12, fontFamily: 'var(--pf-t--global--font--family--mono)' }}>
                      {new Date((v.ts ?? 0) * 1000).toLocaleTimeString()} [{v.side}] {v.kind}: {v.detail}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ marginTop: 8, fontSize: 12, opacity: 0.7 }}>{t('compliance.none')}</div>
              )}
            </CardBody>
          </Card>
        </PageSection>
      ) : null}

      <PageSection>
        <PfFrameViewer />
      </PageSection>
    </>
  )
}
