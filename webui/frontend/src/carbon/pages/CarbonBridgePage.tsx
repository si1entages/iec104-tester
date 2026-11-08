import { useEffect, useState } from 'react'

import { Button, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import { CarbonConditionCard } from '../components/CarbonConditionCard'
import { CarbonFrameViewer } from '../components/CarbonFrameViewer'
import { Note, NumField, Panel, KvList, TextField } from '../components/ui'

/**
 * 桥接观察页（T74，bridge 角色专用）：桥接配置启停 + 运行统计 + 实时报文.
 *
 * 帧视图复用 CarbonFrameViewer（WS `frame` 事件喂同一缓存）；统计随
 * bridge-stats 节流事件重拉 status 而刷新（1Hz 上限）。
 */
export function CarbonBridgePage() {
  const t = useT()
  const { data: status } = useStatusQuery()
  const running = Boolean(status?.running)
  const started = Boolean(status?.started)
  const stats = status?.bridge_stats

  const [listenHost, setListenHost] = useState('0.0.0.0')
  const [listenPort, setListenPort] = useState('2404')
  const [upHost, setUpHost] = useState('127.0.0.1')
  const [upPort, setUpPort] = useState('2404')

  // 仅在运行态变化时回填一次表单（running 时用 bridge_cfg；停止时
  // status.host/port 是 CLI --upstream-* 的预填），避免逐秒打字被覆盖
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
    <div className="app-gap">
      <Panel
        title={
          <span className="app-row">
            {t('bridge.cfgTitle')}
            <Tag size="sm" type={running ? 'green' : 'gray'}>
              {running ? t('conn.connected') : t('conn.disconnected')}
            </Tag>
          </span>
        }
      >
        {showError ? (
          <Note kind="error" title={t('common.cmdFailed')} style={{ marginBottom: 12 }}>
            {showError}
          </Note>
        ) : null}
        <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 12 }}>{t('bridge.hint')}</div>
        <form onSubmit={(e) => e.preventDefault()}>
          <div className="app-row" style={{ alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <TextField id="cb-br-lh" label={t('bridge.listenHost')} value={listenHost}
                       onChange={setListenHost} width={200} disabled={running} />
            <NumField id="cb-br-lp" label={t('bridge.listenPort')} value={Number(listenPort) || 0}
                      onChange={(v) => setListenPort(String(v))} width={140} min={1} max={65535} disabled={running} />
            <TextField id="cb-br-uh" label={t('bridge.upstreamHost')} value={upHost}
                       onChange={setUpHost} width={200} disabled={running} />
            <NumField id="cb-br-up" label={t('bridge.upstreamPort')} value={Number(upPort) || 0}
                      onChange={(v) => setUpPort(String(v))} width={140} min={1} max={65535} disabled={running} />
          </div>
          <div className="app-row" style={{ marginTop: 12 }}>
            <Button kind="primary" disabled={busy || running} onClick={doStart}>
              {t('bridge.start')}
            </Button>
            <Button kind="danger" disabled={busy || !started}
                    onClick={() => { setApiError(''); stop.mutate(undefined, { onSuccess: (r: { ok: boolean; error?: string }) => setApiError(r.ok ? '' : (r.error ?? '')) }) }}>
              {t('bridge.stop')}
            </Button>
          </div>
        </form>
      </Panel>

      <Panel title={t('bridge.statsTitle')}>
        <KvList items={[
          { term: t('bridge.statsFramesDn'), value: stats?.frames_dn ?? 0 },
          { term: t('bridge.statsFramesUp'), value: stats?.frames_up ?? 0 },
          { term: t('bridge.statsBytesDn'), value: stats?.bytes_dn ?? 0 },
          { term: t('bridge.statsBytesUp'), value: stats?.bytes_up ?? 0 },
          { term: t('bridge.statsClients'), value: stats?.clients_total ?? 0 },
          { term: t('bridge.statsResyncs'), value: stats?.resyncs ?? 0 },
          { term: t('bridge.statsUpstreamErrors'), value: stats?.upstream_errors ?? 0 },
        ]} />
      </Panel>

      <CarbonConditionCard />

      {status?.compliance ? (
        <Panel title={t('compliance.title')}>
          <KvList items={[
            { term: t('compliance.total'), value: String(status.compliance.violation_total ?? 0) },
            { term: t('compliance.frames'), value: String(status.compliance.frames_seen ?? 0) },
          ]} />
          {status.compliance.violations && status.compliance.violations.length > 0 ? (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 4 }}>
                {t('compliance.violations')}
              </div>
              {status.compliance.violations.map((v, i) => (
                <div key={i} style={{ fontSize: 12, fontFamily: 'var(--cds-code-01, monospace)' }}>
                  {new Date((v.ts ?? 0) * 1000).toLocaleTimeString()} [{v.side}] {v.kind}: {v.detail}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ marginTop: 8, fontSize: 12, opacity: 0.7 }}>{t('compliance.none')}</div>
          )}
        </Panel>
      ) : null}

      <CarbonFrameViewer />
    </div>
  )
}
