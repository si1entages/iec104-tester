import { useMemo, useState } from 'react'

import { Button, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useMultiStatusQuery, useMultiSummaryQuery } from '../../api/queries'
import { useT } from '../../i18n'
import type { DraftStation } from '../../lib/stationDraft'
import { newStation, toStationConfigs, validateDraft } from '../../lib/stationDraft'
import { CheckField, Note, NumField, Panel, TableFrame, TextField } from '../components/ui'

export function CarbonMultiPage() {
  const t = useT()
  const statusQuery = useMultiStatusQuery()
  const summaryQuery = useMultiSummaryQuery()
  const running = Boolean(summaryQuery.data?.running ?? statusQuery.data?.running)

  const COUNT_KEY = { yx_count: 'sc.yxCount', yc_count: 'sc.ycCount', yk_count: 'sc.ykCount', ym_count: 'sc.ymCount' } as const

  const [draft, setDraft] = useState<DraftStation[]>(() => [newStation(1), newStation(2)])
  const [excluded, setExcluded] = useState<string[]>([])
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const start = useCommand(api.multi.start)
  const stop = useCommandNoArgs(api.multi.stop)
  const busy = start.isPending || stop.isPending

  const effective = useMemo(
    () => draft.map((s) => ({ ...s, enabled: !excluded.includes(s.station_id) })),
    [draft, excluded],
  )
  const issues = useMemo(() => validateDraft(effective), [effective])

  const patch = (index: number, next: Partial<DraftStation>): void => {
    setDraft((prev) => prev.map((s, i) => (i === index ? { ...s, ...next } : s)))
  }

  const runStart = async (): Promise<void> => {
    const payload = toStationConfigs(effective)
    if (payload.length === 0) {
      setLast({ ok: false, text: t('multi.noEnabled') })
      return
    }
    try {
      const r = await start.mutateAsync({ stations: payload })
      setLast(
        r.ok
          ? { ok: true, text: t('multi.started', { n: r.stations ?? payload.length }) }
          : { ok: false, text: t('multi.startFailed', { error: r.error ?? t('cmd.unknown') }) },
      )
    } catch (e) {
      setLast({ ok: false, text: t('multi.startFailed', { error: (e as Error).message }) })
    }
  }

  const runStop = async (): Promise<void> => {
    try {
      const r = await stop.mutateAsync()
      setLast(
        r.ok
          ? { ok: true, text: t('multi.stoppedAll') }
          : { ok: false, text: t('multi.stopFailed', { error: r.error ?? t('cmd.unknown') }) },
      )
    } catch (e) {
      setLast({ ok: false, text: t('multi.stopFailed', { error: (e as Error).message }) })
    }
  }

  const summary = summaryQuery.data
  const stations = statusQuery.data?.stations ?? []

  return (
    <div className="app-gap">
      <Panel
        title={
          <span className="app-row">
            {t('msv.title')}
            <Tag size="sm" type={running ? 'green' : 'gray'}>
              {running ? t('msv.running') : t('msv.notRunning')}
            </Tag>
            {summary ? (
              <>
                <Tag size="sm" type="gray">{`${t('msv.stationCount')} ${summary.station_count}`}</Tag>
                <Tag size="sm" type="gray">{`${t('msv.totalClients')} ${summary.total_clients}`}</Tag>
                <Tag size="sm" type="gray">{`${t('msv.uptime')} ${Math.round(summary.uptime)}s`}</Tag>
              </>
            ) : null}
            {running ? <Tag size="sm" type="magenta">{t('multi.runningFrozen')}</Tag> : null}
          </span>
        }
      >
        <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 8 }}>{t('multi.roleNoteDesc')}</div>
        {last ? <Note kind={last.ok ? 'success' : 'error'} title={last.text} style={{ marginBottom: 8 }} /> : null}
        {issues.length > 0 ? (
          <Note kind="warning" title={t('multi.validationIssues', { n: issues.length })} style={{ marginBottom: 8 }}>
            <ul style={{ margin: 0, paddingInlineStart: 18 }}>
              {issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </Note>
        ) : null}

        <div className="app-tiles" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
          {draft.map((station, index) => {
            const enabled = !excluded.includes(station.station_id)
            return (
              <div key={`${station.station_id}-${index}`} data-testid="multi-card" className="app-stack">
                <div className="app-row">
                  <strong>{`${t('multi.draftTitle')} #${index + 1} · ${station.station_id}`}</strong>
                  <Tag size="sm" type={enabled ? 'blue' : 'gray'}>
                    {enabled ? t('sc.include') : t('msv.rowStopped')}
                  </Tag>
                </div>
                <CheckField
                  id={`cb-multi-en-${index}`}
                  label={t('sc.include')}
                  checked={enabled}
                  disabled={running}
                  onChange={(checked) =>
                    setExcluded((prev) =>
                      checked
                        ? prev.filter((id) => id !== station.station_id)
                        : [...prev, station.station_id],
                    )
                  }
                />
                <TextField
                  id={`cb-multi-id-${index}`}
                  label={t('sc.stationId')}
                  placeholder={t('sc.stationIdPlaceholder')}
                  value={station.station_id ?? ''}
                  disabled={running}
                  onChange={(v) => patch(index, { station_id: v })}
                />
                <TextField
                  id={`cb-multi-name-${index}`}
                  label={t('sc.stationName')}
                  value={station.station_name ?? ''}
                  disabled={running}
                  onChange={(v) => patch(index, { station_name: v })}
                />
                <div className="app-row" style={{ alignItems: 'flex-end' }}>
                  <NumField
                    id={`cb-multi-port-${index}`}
                    label={t('msv.col.port')}
                    value={station.port ?? 0}
                    onChange={(v) => patch(index, { port: v })}
                    min={1}
                    max={65535}
                    width={120}
                  />
                  <NumField
                    id={`cb-multi-ca-${index}`}
                    label={t('msv.col.addr')}
                    value={station.common_addr ?? 0}
                    onChange={(v) => patch(index, { common_addr: v })}
                    min={0}
                    width={110}
                  />
                  <NumField
                    id={`cb-multi-conn-${index}`}
                    label={t('sc.maxConn')}
                    value={station.max_connections ?? 0}
                    onChange={(v) => patch(index, { max_connections: v })}
                    min={1}
                    width={120}
                  />
                </div>
                <CheckField
                  id={`cb-multi-auto-${index}`}
                  label={t('sc.autoGen')}
                  checked={station.auto_generate ?? false}
                  disabled={running}
                  onChange={(checked) => patch(index, { auto_generate: checked })}
                />
                {station.auto_generate ? (
                  <div className="app-row" style={{ alignItems: 'flex-end' }}>
                    {(['yx_count', 'yc_count', 'yk_count', 'ym_count'] as const).map((key) => (
                      <NumField
                        key={key}
                        id={`cb-multi-${key}-${index}`}
                        label={t(COUNT_KEY[key])}
                        value={station[key] ?? 0}
                        onChange={(v) => patch(index, { [key]: v } as Partial<DraftStation>)}
                        min={0}
                        width={90}
                      />
                    ))}
                  </div>
                ) : null}
                <div>
                  <Button
                    kind="danger"
                    size="sm"
                    aria-label={`${t('sc.delete')}-${station.station_id}`}
                    disabled={running}
                    onClick={() => setDraft((prev) => prev.filter((_s, i) => i !== index))}
                  >
                    {t('sc.delete')}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>

        <div className="app-row" style={{ marginTop: 16 }}>
          <Button
            kind="secondary"
            disabled={running}
            onClick={() => setDraft((prev) => [...prev, newStation(prev.length + 1)])}
          >
            {t('multi.addStation')}
          </Button>
          <Button kind="primary" disabled={running || busy || issues.length > 0} onClick={() => void runStart()}>
            {t('multi.startAll')}
          </Button>
          <Button kind="danger" disabled={!running || busy} onClick={() => void runStop()}>
            {t('multi.stopAll')}
          </Button>
        </div>
      </Panel>

      {stations.length > 0 ? (
        <Panel title={t('msv.title')}>
          <TableFrame>
            <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
              <thead>
                <tr>
                  <th style={{ width: 150, minWidth: 150 }}><span className="cds--table-header-label">{t('msv.col.id')}</span></th>
                  <th style={{ width: 160, minWidth: 160 }}><span className="cds--table-header-label">{t('msv.col.name')}</span></th>
                  <th style={{ width: 80, minWidth: 80 }}><span className="cds--table-header-label">{t('msv.col.port')}</span></th>
                  <th style={{ width: 90, minWidth: 90 }}><span className="cds--table-header-label">{t('msv.col.addr')}</span></th>
                  <th style={{ width: 90, minWidth: 90 }}><span className="cds--table-header-label">{t('msv.col.running')}</span></th>
                  <th style={{ width: 90, minWidth: 90 }}><span className="cds--table-header-label">{t('msv.col.clients')}</span></th>
                  <th style={{ width: 170, minWidth: 170 }}><span className="cds--table-header-label">{t('msv.col.points')}</span></th>
                </tr>
              </thead>
              <tbody>
                {stations.map((row) => (
                  <tr key={row.station_id}>
                    <td className="mono">{row.station_id}</td>
                    <td>{row.station_name}</td>
                    <td className="mono">{row.port}</td>
                    <td className="mono">{row.common_addr}</td>
                    <td>
                      <Tag size="sm" type={row.running ? 'green' : 'gray'}>
                        {row.running ? t('msv.rowRunning') : t('msv.rowStopped')}
                      </Tag>
                    </td>
                    <td>{row.client_count}</td>
                    <td className="mono">
                      {row.yx_count}/{row.yc_count}/{row.yk_count}/{row.ym_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
        </Panel>
      ) : null}
    </div>
  )
}
