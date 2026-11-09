import { useState } from 'react'

import { Button } from '@carbon/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { useT } from '../../i18n'
import { useUiStore } from '../../store/uiStore'
import { KvList, Note, NumField, Panel } from './ui'

/**
 * 压测卡（T76，Carbon）：仅双角色部署显示（单角色/桥应用无编排服务，404）。
 * 状态在运行中 1s 轮询（refetchInterval 按 data 驱动）；停止后展示汇总。
 * 引擎未运行时直接启动 → 服务端返回干净的业务错误（此处显形）。
 */
export function CarbonLoadTestCard() {
  const t = useT()
  const availableRoles = useUiStore((s) => s.availableRoles)
  const queryClient = useQueryClient()
  const isDual = availableRoles.includes('master') && availableRoles.includes('slave')

  const [duration, setDuration] = useState('60')
  const [eps, setEps] = useState('100')
  const [connections, setConnections] = useState('1')

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
        connections: Number(connections) || 1,
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

  return (
    <Panel title={t('loadtest.title')} style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginBottom: 12 }}>
        {t('loadtest.hint')}
      </div>
      {err || apiErr ? (
        <Note kind="error" title={t('common.cmdFailed')} style={{ marginBottom: 12 }}>
          {apiErr ?? (err instanceof Error ? err.message : String(err))}
        </Note>
      ) : null}
      <div className="app-row" style={{ alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <NumField id="cb-lt-dur" label={t('loadtest.duration')} value={Number(duration) || 0}
                  onChange={(v) => setDuration(String(v))} width={140} min={1} max={3600}
                  disabled={running} />
        <NumField id="cb-lt-eps" label={t('loadtest.eps')} value={Number(eps) || 0}
                  onChange={(v) => setEps(String(v))} width={160} min={1} max={10000}
                  disabled={running} />
        <NumField id="cb-lt-conn" label={t('loadtest.connections')} value={Number(connections) || 1}
                  onChange={(v) => setConnections(String(v))} width={140} min={1} max={8}
                  disabled={running} />
        <Button kind="primary" size="sm" disabled={busy || running} onClick={() => start.mutate()}>
          {t('loadtest.start')}
        </Button>
        <Button kind="danger" size="sm" disabled={busy || !running} onClick={() => stop.mutate()}>
          {t('loadtest.stop')}
        </Button>
      </div>
      <div style={{ marginTop: 12 }}>
        <KvList items={[
          { term: t('loadtest.elapsed'), value: String(data?.elapsed_s ?? '—') },
          { term: t('loadtest.sent'), value: String(data?.events_sent ?? '—') },
          { term: t('loadtest.rx'), value: String(data?.rx_frames ?? '—') },
          { term: t('loadtest.fps'), value: String(data?.fps ?? '—') },
        ]} />
        {Array.isArray(data?.per_connection) && (data!.per_connection as Array<{ connection: number; frames_received: number; errors: number }>).length > 1 ? (
          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--cds-text-secondary)' }}>
            {(data!.per_connection as Array<{ connection: number; frames_received: number; errors: number }>).map((row) => (
              <div key={row.connection}>
                {t('loadtest.conn', {
                  n: row.connection,
                  frames: row.frames_received,
                  err: row.errors > 0 ? t('loadtest.connErr', { errors: row.errors }) : '',
                })}
              </div>
            ))}
          </div>
        ) : null}
      </div>
      {summary ? (
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--cds-text-secondary)' }}>
          {t('loadtest.summary')}: {JSON.stringify(summary)}
        </div>
      ) : null}
    </Panel>
  )
}
