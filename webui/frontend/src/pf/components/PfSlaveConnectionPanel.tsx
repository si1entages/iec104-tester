import { useEffect, useState } from 'react'

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
  Grid,
  GridItem,
  Label,
  TextInput,
} from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import { NumField } from './PfField'

/** 子站启动与状态：绑定地址/端口/公共地址、TLS、启停、客户端列表。 */
export function PfSlaveConnectionPanel() {
  const t = useT()
  const { data: status } = useStatusQuery()
  const running = Boolean(status?.running)

  const [host, setHost] = useState('0.0.0.0')
  const [port, setPort] = useState(2404)
  const [addr, setAddr] = useState(1)
  const [tlsEnabled, setTlsEnabled] = useState(false)
  const [tlsCert, setTlsCert] = useState('')
  const [tlsKey, setTlsKey] = useState('')
  const [tlsCa, setTlsCa] = useState('')
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const start = useCommand(api.slave.start)
  const stop = useCommandNoArgs(api.slave.stop)

  useEffect(() => {
    if (!status || status.role !== 'slave') return
    if (typeof status.host === 'string' && status.host) setHost(status.host)
    if (typeof status.port === 'number') setPort(status.port)
    if (typeof status.addr === 'number') setAddr(status.addr)
  }, [status?.role, status?.host, status?.port, status?.addr])

  const report = (label: string, result: { ok: boolean; error?: string }): void => {
    setLast(
      result.ok
        ? { ok: true, text: t('cmd.done', { label }) }
        : { ok: false, text: t('cmd.failed', { label, error: result.error ?? t('cmd.unknown') }) },
    )
  }

  const clients = status?.client_list ?? []

  return (
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
          <span>{t('scp.title')}</span>
          <Label isCompact color={running ? 'green' : 'grey'}>
            {running ? t('scp.listening') : t('scp.stopped')}
          </Label>
          {status ? (
            <span style={{ opacity: 0.75, fontSize: 12 }}>
              {t('status.points')} {status.points ?? 0} · {t('status.tx')} {status.tx ?? 0} ·{' '}
              {t('status.rx')} {status.rx ?? 0} · {t('conn.dropped')} {status.dropped ?? 0} ·{' '}
              {t('status.clients')} {clients.length}
            </span>
          ) : null}
        </Flex>
      </CardTitle>
      <CardBody>
        {last ? (
          <Alert
            isInline
            variant={last.ok ? 'success' : 'danger'}
            title={last.text}
            style={{ marginBottom: 12 }}
          />
        ) : null}
        <Form onSubmit={(event) => event.preventDefault()}>
          <Grid hasGutter>
            <GridItem span={12} md={4}>
              <FormGroup label={t('scp.bind')} fieldId="pf-scp-host">
                <TextInput id="pf-scp-host" value={host} onChange={(_e, v) => setHost(v)} />
              </FormGroup>
            </GridItem>
            <GridItem span={12} md={3}>
              <NumField id="pf-scp-port" label={t('status.port')} value={port} onChange={setPort} min={1} max={65535} />
            </GridItem>
            <GridItem span={12} md={3}>
              <NumField id="pf-scp-addr" label={t('status.addr')} value={addr} onChange={setAddr} min={0} />
            </GridItem>
            <GridItem span={12} md={2}>
              <FormGroup label="TLS" fieldId="pf-scp-tls">
                <Button
                  variant={tlsEnabled ? 'primary' : 'secondary'}
                  onClick={() => setTlsEnabled((v) => !v)}
                >
                  {tlsEnabled ? t('conn.on') : t('conn.off')}
                </Button>
              </FormGroup>
            </GridItem>
          </Grid>

          {tlsEnabled ? (
            <Grid hasGutter style={{ marginTop: 8 }}>
              <GridItem span={12} md={4}>
                <FormGroup label={t('scp.tlsCert')} fieldId="pf-tls-cert">
                  <TextInput id="pf-tls-cert" value={tlsCert} onChange={(_e, v) => setTlsCert(v)} />
                </FormGroup>
              </GridItem>
              <GridItem span={12} md={4}>
                <FormGroup label={t('scp.tlsKey')} fieldId="pf-tls-key">
                  <TextInput id="pf-tls-key" value={tlsKey} onChange={(_e, v) => setTlsKey(v)} />
                </FormGroup>
              </GridItem>
              <GridItem span={12} md={4}>
                <FormGroup label={t('scp.tlsCa')} fieldId="pf-tls-ca">
                  <TextInput
                    id="pf-tls-ca"
                    value={tlsCa}
                    onChange={(_e, v) => setTlsCa(v)}
                    placeholder={t('scp.tlsCaPlaceholder')}
                  />
                </FormGroup>
              </GridItem>
            </Grid>
          ) : null}

          <ActionGroup>
            <Button
              variant="primary"
              isDisabled={running || start.isPending}
              isLoading={start.isPending}
              onClick={() =>
                void start
                  .mutateAsync({
                    host,
                    port,
                    addr,
                    ...(tlsEnabled
                      ? {
                          tls: {
                            enabled: true,
                            ...(tlsCert ? { certfile: tlsCert } : {}),
                            ...(tlsKey ? { keyfile: tlsKey } : {}),
                            ...(tlsCa ? { cafile: tlsCa } : {}),
                          },
                        }
                      : {}),
                  })
                  .then((r) => report(t('scp.start'), r))
              }
            >
              {t('scp.start')}
            </Button>
            <Button
              variant="danger"
              isDisabled={!running || stop.isPending}
              isLoading={stop.isPending}
              onClick={() => void stop.mutateAsync().then((r) => report(t('scp.stop'), r))}
            >
              {t('scp.stop')}
            </Button>
          </ActionGroup>
        </Form>

        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 13, marginBottom: 4 }}>{t('scp.clientList')}</div>
          {clients.length === 0 ? (
            <div style={{ opacity: 0.7, fontSize: 12 }}>{t('scp.noClients')}</div>
          ) : (
            <ul style={{ margin: 0, paddingInlineStart: 18 }}>
              {clients.map((peer) => (
                <li key={peer} className="mono">
                  {peer}
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardBody>
    </Card>
  )
}
