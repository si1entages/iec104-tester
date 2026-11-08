import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Checkbox,
  Flex,
  FormGroup,
  Grid,
  GridItem,
  Label,
  TextInput,
} from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useMultiStatusQuery, useMultiSummaryQuery } from '../../api/queries'
import { useT } from '../../i18n'
import type { DraftStation } from '../../lib/stationDraft'
import { newStation, toStationConfigs, validateDraft } from '../../lib/stationDraft'
import { NumField } from '../components/PfField'

export function PfMultiPage() {
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
    <>
      <PageSectionLike>
        <Card>
          <CardTitle>
            <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
              <span>{t('msv.title')}</span>
              <Label isCompact color={running ? 'green' : 'grey'}>
                {running ? t('msv.running') : t('msv.notRunning')}
              </Label>
              {summary ? (
                <>
                  <Label isCompact>{`${t('msv.stationCount')} ${summary.station_count}`}</Label>
                  <Label isCompact>{`${t('msv.totalClients')} ${summary.total_clients}`}</Label>
                  <Label isCompact>{`${t('msv.uptime')} ${Math.round(summary.uptime)}s`}</Label>
                </>
              ) : null}
              {running ? <Label isCompact color="orange">{t('multi.runningFrozen')}</Label> : null}
            </Flex>
          </CardTitle>
          <CardBody>
            <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 8 }}>{t('multi.roleNoteDesc')}</div>
            {last ? (
              <Alert
                isInline
                variant={last.ok ? 'success' : 'danger'}
                title={last.text}
                style={{ marginBottom: 8 }}
              />
            ) : null}
            {issues.length > 0 ? (
              <Alert
                isInline
                variant="warning"
                title={t('multi.validationIssues', { n: issues.length })}
                style={{ marginBottom: 8 }}
              >
                <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                  {issues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              </Alert>
            ) : null}

            <Grid hasGutter>
              {draft.map((station, index) => {
                const enabled = !excluded.includes(station.station_id)
                return (
                  <GridItem key={`${station.station_id}-${index}`} span={12} md={6} xl={4}>
                  <div data-testid="multi-card">
                    <Card isCompact>
                      <CardTitle>
                        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
                          <span>{`${t('multi.draftTitle')} #${index + 1} · ${station.station_id}`}</span>
                          <Label isCompact color={enabled ? 'blue' : 'grey'}>
                            {enabled ? t('sc.include') : t('msv.rowStopped')}
                          </Label>
                        </Flex>
                      </CardTitle>
                      <CardBody>
                        <Checkbox
                          id={`pf-multi-en-${index}`}
                          aria-label={`${t('sc.include')}-${station.station_id}`}
                          label={t('sc.include')}
                          isChecked={enabled}
                          isDisabled={running}
                          onChange={(_e, checked) =>
                            setExcluded((prev) => (checked
                              ? prev.filter((id) => id !== station.station_id)
                              : [...prev, station.station_id]))
                          }
                        />
                        <FormGroup label={t('sc.stationId')} fieldId={`pf-multi-id-${index}`}>
                          <TextInput
                            id={`pf-multi-id-${index}`}
                            placeholder={t('sc.stationIdPlaceholder')}
                            value={station.station_id}
                            isDisabled={running}
                            onChange={(_e, v) => patch(index, { station_id: v })}
                          />
                        </FormGroup>
                        <FormGroup label={t('sc.stationName')} fieldId={`pf-multi-name-${index}`}>
                          <TextInput
                            id={`pf-multi-name-${index}`}
                            value={station.station_name}
                            isDisabled={running}
                            onChange={(_e, v) => patch(index, { station_name: v })}
                          />
                        </FormGroup>
                        <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
                          <NumField
                            id={`pf-multi-port-${index}`}
                            label={t('msv.col.port')}
                            value={station.port ?? 0}
                            onChange={(v) => patch(index, { port: v })}
                            min={1}
                            max={65535}
                            width={120}
                          />
                          <NumField
                            id={`pf-multi-ca-${index}`}
                            label={t('msv.col.addr')}
                            value={station.common_addr ?? 0}
                            onChange={(v) => patch(index, { common_addr: v })}
                            min={0}
                            width={110}
                          />
                          <NumField
                            id={`pf-multi-conn-${index}`}
                            label={t('sc.maxConn')}
                            value={station.max_connections ?? 0}
                            onChange={(v) => patch(index, { max_connections: v })}
                            min={1}
                            width={120}
                          />
                        </Flex>
                        <div style={{ marginTop: 8 }}>
                          <Checkbox
                            id={`pf-multi-auto-${index}`}
                            label={t('sc.autoGen')}
                            isChecked={station.auto_generate}
                            isDisabled={running}
                            onChange={(_e, checked) => patch(index, { auto_generate: checked })}
                          />
                        </div>
                        {station.auto_generate ? (
                          <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
                            {(['yx_count', 'yc_count', 'yk_count', 'ym_count'] as const).map((key) => (
                              <NumField
                                key={key}
                                id={`pf-multi-${key}-${index}`}
                                label={t(COUNT_KEY[key])}
                                value={station[key] ?? 0}
                                onChange={(v) => patch(index, { [key]: v } as Partial<DraftStation>)}
                                min={0}
                                width={90}
                              />
                            ))}
                          </Flex>
                        ) : null}
                        <ActionGroup>
                          <Button
                            variant="danger"
                            size="sm"
                            aria-label={`${t('sc.delete')}-${station.station_id}`}
                            isDisabled={running}
                            onClick={() => setDraft((prev) => prev.filter((_s, i) => i !== index))}
                          >
                            {t('sc.delete')}
                          </Button>
                        </ActionGroup>
                      </CardBody>
                    </Card>
                  </div>
                  </GridItem>
                )
              })}
            </Grid>

            <ActionGroup>
              <Button
                variant="secondary"
                isDisabled={running}
                onClick={() => setDraft((prev) => [...prev, newStation(prev.length + 1)])}
              >
                {t('multi.addStation')}
              </Button>
              <Button variant="primary" isDisabled={running || busy || issues.length > 0} onClick={() => void runStart()}>
                {t('multi.startAll')}
              </Button>
              <Button variant="danger" isDisabled={!running || busy} onClick={() => void runStop()}>
                {t('multi.stopAll')}
              </Button>
            </ActionGroup>
          </CardBody>
        </Card>
      </PageSectionLike>

      {stations.length > 0 ? (
        <PageSectionLike>
          <Card>
            <CardTitle>{t('msv.title')}</CardTitle>
            <CardBody>
              <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
                <thead className="pf-v6-c-table__thead">
                  <tr className="pf-v6-c-table__tr">
                    <th className="pf-v6-c-table__th" style={{ width: 150, minWidth: 150 }}>{t('msv.col.id')}</th>
                    <th className="pf-v6-c-table__th" style={{ width: 160, minWidth: 160 }}>{t('msv.col.name')}</th>
                    <th className="pf-v6-c-table__th" style={{ width: 80, minWidth: 80 }}>{t('msv.col.port')}</th>
                    <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>{t('msv.col.addr')}</th>
                    <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>{t('msv.col.running')}</th>
                    <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>{t('msv.col.clients')}</th>
                    <th className="pf-v6-c-table__th" style={{ width: 170, minWidth: 170 }}>{t('msv.col.points')}</th>
                  </tr>
                </thead>
                <tbody className="pf-v6-c-table__tbody">
                  {stations.map((row) => (
                    <tr key={row.station_id} className="pf-v6-c-table__tr">
                      <td className="pf-v6-c-table__td mono">{row.station_id}</td>
                      <td className="pf-v6-c-table__td">{row.station_name}</td>
                      <td className="pf-v6-c-table__td mono">{row.port}</td>
                      <td className="pf-v6-c-table__td mono">{row.common_addr}</td>
                      <td className="pf-v6-c-table__td">
                        <Label isCompact color={row.running ? 'green' : 'grey'}>
                          {row.running ? t('msv.rowRunning') : t('msv.rowStopped')}
                        </Label>
                      </td>
                      <td className="pf-v6-c-table__td">{row.client_count}</td>
                      <td className="pf-v6-c-table__td mono">
                        {row.yx_count}/{row.yc_count}/{row.yk_count}/{row.ym_count}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardBody>
          </Card>
        </PageSectionLike>
      ) : null}
    </>
  )
}

/** 与 PageSection 等价的间距容器（页面内多卡片时保持纵向节奏）。 */
function PageSectionLike({ children }: { children: ReactNode }) {
  return <div style={{ marginBottom: 16 }}>{children}</div>
}
