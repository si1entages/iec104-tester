import { useMemo, useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FormSelect,
  FormSelectOption,
  Label,
  Pagination,
  TextInput,
} from '@patternfly/react-core'

import { buildUrl } from '../../api/client'
import { HISTORY_EXPORT_URL } from '../../api/endpoints'
import { PfHistoryCurve } from '../components/PfHistoryCurve'
import { useHistoryDataQuery, useHistoryFramesQuery, useHistoryStatsQuery } from '../../api/queries'
import type { HistoryDataRecord, HistoryFrameRecord } from '../../api/types'
import { useLocale, useT } from '../../i18n'
import { formatDate, formatDateTime, localeTag } from '../../lib/format'
import { PfQualityTags } from '../components/PfQualityTags'

const PAGE_SIZE = 50
const DEFAULT_LIMIT = 1000

type TabKey = 'data' | 'frames' | 'curve'

function formatBytes(n: number): string {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

/** 把 datetime-local 值转成秒级时间戳（空值 → undefined）。 */
function toEpoch(value: string): number | undefined {
  if (!value) return undefined
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : undefined
}

interface Applied {
  start?: number
  end?: number
  point_type?: string
  ioa?: number
  direction?: string
}

export function PfHistoryPage() {
  const t = useT()
  const locale = useLocale()
  const [tab, setTab] = useState<TabKey>('data')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [pointType, setPointType] = useState('')
  const [ioa, setIoa] = useState('')
  const [direction, setDirection] = useState('')
  const [limit, setLimit] = useState(String(DEFAULT_LIMIT))
  const [applied, setApplied] = useState<Applied>({})
  const [page, setPage] = useState(1)

  const statsQuery = useHistoryStatsQuery()
  const dataQuery = useHistoryDataQuery(
    {
      start: applied.start,
      end: applied.end,
      point_type: applied.point_type,
      ioa: applied.ioa,
      limit: Number(limit) || DEFAULT_LIMIT,
    },
    tab === 'data',
  )
  const framesQuery = useHistoryFramesQuery(
    {
      start: applied.start,
      end: applied.end,
      direction: applied.direction,
      limit: Number(limit) || DEFAULT_LIMIT,
    },
    tab === 'frames',
  )

  const enabled = statsQuery.data?.enabled === true
  const stats = statsQuery.data?.stats
  const rows: Array<HistoryDataRecord | HistoryFrameRecord> =
    tab === 'data' ? (dataQuery.data?.rows ?? []) : (framesQuery.data?.rows ?? [])
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageRows = rows.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  const exportUrl = useMemo(
    () =>
      buildUrl(HISTORY_EXPORT_URL, {
        type: tab,
        point_type: tab === 'data' ? applied.point_type : undefined,
        ioa: tab === 'data' ? applied.ioa : undefined,
        direction: tab === 'frames' ? applied.direction : undefined,
        start: applied.start,
        end: applied.end,
        limit: 200000,
      }),
    [tab, applied],
  )

  const search = (): void => {
    setApplied({
      start: toEpoch(start),
      end: toEpoch(end),
      point_type: tab === 'data' ? pointType || undefined : undefined,
      ioa: tab === 'data' && ioa ? Number(ioa) : undefined,
      direction: tab === 'frames' ? direction || undefined : undefined,
    })
    setPage(1)
  }

  const reset = (): void => {
    setStart('')
    setEnd('')
    setPointType('')
    setIoa('')
    setDirection('')
    setLimit(String(DEFAULT_LIMIT))
    setApplied({})
    setPage(1)
  }

  return (
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          <span>{t('history.title')}</span>
          {!enabled && statsQuery.isSuccess ? <Label isCompact>{t('history.disabled')}</Label> : null}
          {enabled && stats ? (
            <>
              <Label isCompact color="blue">
                {t('history.dataCount', { n: stats.data_records })}
              </Label>
              <Label isCompact color="blue">
                {t('history.frameCount', { n: stats.frame_records })}
              </Label>
              <Label isCompact>{formatBytes(stats.db_size_bytes)}</Label>
              {stats.oldest_data ? (
                <Label isCompact>
                  {formatDate(stats.oldest_data, localeTag(locale))} ~{' '}
                  {formatDate(stats.newest_data, localeTag(locale))}
                </Label>
              ) : null}
              {stats.dropped_records > 0 ? (
                <Label isCompact color="orange">
                  {t('history.dropped', { n: stats.dropped_records })}
                </Label>
              ) : null}
            </>
          ) : null}
          {tab !== 'curve' ? (
            <Label isCompact color="blue">
              {t('history.view', { n: rows.length })}
            </Label>
          ) : null}
        </Flex>
      </CardTitle>
      <CardBody>
        {statsQuery.isError ? (
          <div style={{ color: 'var(--pf-t--global--text--color--status--danger--default)', marginBottom: 8 }}>
            {t('common.loadFailed')}: {statsQuery.error instanceof Error ? statsQuery.error.message : ''}
          </div>
        ) : null}
        {statsQuery.isSuccess && !enabled ? (
          <div style={{ marginBottom: 8, fontSize: 13 }}>{t('history.notEnabledDesc')}</div>
        ) : null}

        <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
          <Button variant={tab === 'data' ? 'primary' : 'secondary'} onClick={() => { setTab('data'); setPage(1) }}>
            {t('history.tab.data')}
          </Button>
          <Button variant={tab === 'frames' ? 'primary' : 'secondary'} onClick={() => { setTab('frames'); setPage(1) }}>
            {t('history.tab.frames')}
          </Button>
          <Button variant={tab === 'curve' ? 'primary' : 'secondary'} onClick={() => { setTab('curve'); setPage(1) }}>
            {t('history.tab.curve')}
          </Button>
          <div style={{ width: 210, minWidth: 210 }}>
            <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 4 }}>{t('history.start')}</div>
            <TextInput
              type="datetime-local"
              value={start}
              onChange={(_e, v) => setStart(v)}
              aria-label={t('history.start')}
            />
          </div>
          <div style={{ width: 210, minWidth: 210 }}>
            <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 4 }}>{t('history.end')}</div>
            <TextInput
              type="datetime-local"
              value={end}
              onChange={(_e, v) => setEnd(v)}
              aria-label={t('history.end')}
            />
          </div>
          {tab === 'data' ? (
            <>
              <div style={{ width: 130, minWidth: 130 }}>
                <FormSelect value={pointType} onChange={(_e, v) => setPointType(v)} aria-label={t('history.type')}>
                  <FormSelectOption value="" label={t('history.type')} />
                  <FormSelectOption value="yx" label={t('history.type.yx')} />
                  <FormSelectOption value="yc" label={t('history.type.yc')} />
                  <FormSelectOption value="ym" label={t('history.type.ym')} />
                </FormSelect>
              </div>
              <div style={{ width: 130, minWidth: 130 }}>
                <TextInput
                  type="number"
                  min={0}
                  placeholder={t('history.ioa')}
                  value={ioa}
                  onChange={(_e, v) => setIoa(v)}
                  aria-label={t('history.ioa')}
                />
              </div>
            </>
          ) : (
            <div style={{ width: 130, minWidth: 130 }}>
              <FormSelect value={direction} onChange={(_e, v) => setDirection(v)} aria-label={t('history.direction')}>
                <FormSelectOption value="" label={t('history.direction')} />
                <FormSelectOption value="rx" label={t('history.dir.rx')} />
                <FormSelectOption value="tx" label={t('history.dir.tx')} />
              </FormSelect>
            </div>
          )}
          <div style={{ width: 110, minWidth: 110 }}>
            <TextInput
              type="number"
              min={1}
              max={10000}
              value={limit}
              onChange={(_e, v) => setLimit(v)}
              aria-label={t('history.limit')}
            />
          </div>
          <Button variant="primary" onClick={search}>
            {t('common.query')}
          </Button>
          <Button variant="secondary" onClick={reset}>
            {t('common.reset')}
          </Button>
          {tab !== 'curve' ? (
            <Button variant="link" onClick={() => window.open(exportUrl, '_blank')}>
              {t('history.export')}
            </Button>
          ) : null}
        </Flex>

        {tab === 'curve' ? (
          <div style={{ marginTop: 12 }}>
            <PfHistoryCurve start={applied.start} end={applied.end} />
          </div>
        ) : (
        <div style={{ marginTop: 12, overflowX: 'auto' }}>
          <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
            <thead className="pf-v6-c-table__thead">
              {tab === 'data' ? (
                <tr className="pf-v6-c-table__tr">
                  <th className="pf-v6-c-table__th" style={{ width: 190, minWidth: 190 }}>{t('history.col.time')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 80, minWidth: 80 }}>{t('history.col.type')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 110, minWidth: 110 }}>{t('history.col.ioa')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 150, minWidth: 150 }}>{t('history.col.value')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 130, minWidth: 130 }}>{t('history.col.quality')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 100, minWidth: 100 }}>{t('history.col.source')}</th>
                </tr>
              ) : (
                <tr className="pf-v6-c-table__tr">
                  <th className="pf-v6-c-table__th" style={{ width: 190, minWidth: 190 }}>{t('history.col.time')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 80, minWidth: 80 }}>{t('history.col.direction')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>{t('history.col.frameType')}</th>
                  <th className="pf-v6-c-table__th">{t('history.col.hex')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 180, minWidth: 180 }}>{t('history.col.parsed')}</th>
                </tr>
              )}
            </thead>
            <tbody className="pf-v6-c-table__tbody">
              {pageRows.length === 0 ? (
                <tr className="pf-v6-c-table__tr">
                  <td className="pf-v6-c-table__td" colSpan={6} style={{ textAlign: 'center', padding: 24, opacity: 0.7 }}>
                    {t('history.empty')}
                  </td>
                </tr>
              ) : tab === 'data' ? (
                (pageRows as HistoryDataRecord[]).map((row) => (
                  <tr key={row.id} className="pf-v6-c-table__tr" data-testid="history-row">
                    <td className="pf-v6-c-table__td mono">{formatDateTime(row.ts, localeTag(locale))}</td>
                    <td className="pf-v6-c-table__td">{row.point_type}</td>
                    <td className="pf-v6-c-table__td mono">{row.ioa}</td>
                    <td className="pf-v6-c-table__td mono">{row.value}</td>
                    <td className="pf-v6-c-table__td"><PfQualityTags quality={row.quality} /></td>
                    <td className="pf-v6-c-table__td">{row.source}</td>
                  </tr>
                ))
              ) : (
                (pageRows as HistoryFrameRecord[]).map((row) => (
                  <tr key={row.id} className="pf-v6-c-table__tr" data-testid="history-row">
                    <td className="pf-v6-c-table__td mono">{formatDateTime(row.ts, localeTag(locale))}</td>
                    <td className="pf-v6-c-table__td">
                      <Label isCompact color={row.direction === 'rx' ? 'blue' : 'green'}>
                        {row.direction}
                      </Label>
                    </td>
                    <td className="pf-v6-c-table__td">{row.frame_type}</td>
                    <td className="pf-v6-c-table__td mono" style={{ wordBreak: 'break-all' }}>{row.hex}</td>
                    <td className="pf-v6-c-table__td">{row.parsed}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        )}

        {tab !== 'curve' ? (
          <div style={{ marginTop: 8 }}>
            <Pagination
              itemCount={rows.length}
              perPage={PAGE_SIZE}
              page={currentPage}
              onSetPage={(_event, p) => setPage(p)}
              isCompact
            />
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}
