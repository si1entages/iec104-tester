import { useEffect, useState } from 'react'

import { Button, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import { BoolField, Note, NumField, Panel, TextField } from './ui'

/** 子站启动与状态：绑定地址/端口/公共地址、TLS、启停、客户端列表。 */
export function CarbonSlaveConnectionPanel() {
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
    <Panel
      title={
        <span className="app-row">
          {t('scp.title')}
          <Tag size="sm" type={running ? 'green' : 'gray'}>
            {running ? t('scp.listening') : t('scp.stopped')}
          </Tag>
          {status ? (
            <span style={{ color: 'var(--cds-text-secondary)', fontSize: 12 }}>
              {t('status.points')} {status.points ?? 0} · {t('status.tx')} {status.tx ?? 0} ·{' '}
              {t('status.rx')} {status.rx ?? 0} · {t('conn.dropped')} {status.dropped ?? 0} ·{' '}
              {t('status.clients')} {clients.length}
            </span>
          ) : null}
        </span>
      }
    >
      {last ? <Note kind={last.ok ? 'success' : 'error'} title={last.text} style={{ marginBottom: 12 }} /> : null}

      <div className="app-row" style={{ alignItems: 'flex-end' }}>
        <TextField id="cb-scp-host" label={t('scp.bind')} value={host} onChange={setHost} width={220} />
        <NumField id="cb-scp-port" label={t('status.port')} value={port} onChange={setPort} min={1} max={65535} width={150} />
        <NumField id="cb-scp-addr" label={t('status.addr')} value={addr} onChange={setAddr} min={0} width={150} />
        <BoolField id="cb-scp-tls" label="TLS" value={tlsEnabled} onChange={setTlsEnabled} />
      </div>

      {tlsEnabled ? (
        <div className="app-row" style={{ marginTop: 8, alignItems: 'flex-end' }}>
          <TextField id="cb-tls-cert" label={t('scp.tlsCert')} value={tlsCert} onChange={setTlsCert} width={220} />
          <TextField id="cb-tls-key" label={t('scp.tlsKey')} value={tlsKey} onChange={setTlsKey} width={220} />
          <TextField
            id="cb-tls-ca"
            label={t('scp.tlsCa')}
            value={tlsCa}
            onChange={setTlsCa}
            width={220}
            placeholder={t('scp.tlsCaPlaceholder')}
          />
        </div>
      ) : null}

      <div className="app-row" style={{ marginTop: 12 }}>
        <Button
          kind="primary"
          disabled={running || start.isPending}
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
          kind="danger"
          disabled={!running || stop.isPending}
          onClick={() => void stop.mutateAsync().then((r) => report(t('scp.stop'), r))}
        >
          {t('scp.stop')}
        </Button>
      </div>

      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 13, marginBottom: 4 }}>{t('scp.clientList')}</div>
        {clients.length === 0 ? (
          <div style={{ color: 'var(--cds-text-secondary)', fontSize: 12 }}>{t('scp.noClients')}</div>
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
    </Panel>
  )
}
