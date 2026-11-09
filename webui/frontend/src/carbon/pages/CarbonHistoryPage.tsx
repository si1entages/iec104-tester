import { useMemo, useState } from 'react'

import { Button, Select, SelectItem, Tag, TextInput } from '@carbon/react'

import { buildUrl } from '../../api/client'
import { HISTORY_EXPORT_URL } from '../../api/endpoints'
import { useHistoryDataQuery, useHistoryFramesQuery, useHistoryStatsQuery } from '../../api/queries'
import type { HistoryDataRecord, HistoryFrameRecord } from '../../api/types'
import { useLocale, useT } from '../../i18n'
import { formatDate, formatDateTime, localeTag } from '../../lib/format'
import { CarbonHistoryCurve } from '../components/CarbonHistoryCurve'
import { CarbonQualityTags } from '../components/CarbonQualityTags'
import { Panel, Pager, TableFrame } from '../components/ui'

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

export function CarbonHistoryPage() {
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
    <Panel
      title={
        <span className="app-row">
          {t('history.title')}
          {!enabled && statsQuery.isSuccess ? <Tag size="sm" type="gray">{t('history.disabled')}</Tag> : null}
          {enabled && stats ? (
            <>
              <Tag size="sm" type="blue">{t('history.dataCount', { n: stats.data_records })}</Tag>
              <Tag size="sm" type="blue">{t('history.frameCount', { n: stats.frame_records })}</Tag>
              <Tag size="sm" type="gray">{formatBytes(stats.db_size_bytes)}</Tag>
              {stats.oldest_data ? (
                <Tag size="sm" type="gray">
                  {formatDate(stats.oldest_data, localeTag(locale))} ~{' '}
                  {formatDate(stats.newest_data, localeTag(locale))}
                </Tag>
              ) : null}
              {stats.dropped_records > 0 ? (
                <Tag size="sm" type="magenta">{t('history.dropped', { n: stats.dropped_records })}</Tag>
              ) : null}
            </>
          ) : null}
          {tab !== 'curve' ? (
            <Tag size="sm" type="blue">{t('history.view', { n: rows.length })}</Tag>
          ) : null}
        </span>
      }
    >
      {statsQuery.isError ? (
        <div style={{ color: 'var(--cds-text-error)', marginBottom: 8 }}>
          {t('common.loadFailed')}: {statsQuery.error instanceof Error ? statsQuery.error.message : ''}
        </div>
      ) : null}
      {statsQuery.isSuccess && !enabled ? (
        <div style={{ marginBottom: 8, fontSize: 13 }}>{t('history.notEnabledDesc')}</div>
      ) : null}

      <div className="app-row" style={{ alignItems: 'flex-end' }}>
        <Button
          kind={tab === 'data' ? 'primary' : 'secondary'}
          onClick={() => {
            setTab('data')
            setPage(1)
          }}
        >
          {t('history.tab.data')}
        </Button>
        <Button
          kind={tab === 'frames' ? 'primary' : 'secondary'}
          onClick={() => {
            setTab('frames')
            setPage(1)
          }}
        >
          {t('history.tab.frames')}
        </Button>
        <Button
          kind={tab === 'curve' ? 'primary' : 'secondary'}
          onClick={() => {
            setTab('curve')
            setPage(1)
          }}
        >
          {t('history.tab.curve')}
        </Button>
        <div style={{ width: 210, minWidth: 210 }}>
          <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginBottom: 4 }}>{t('history.start')}</div>
          <TextInput
            id="cb-h-start"
            type="datetime-local"
            labelText={t('history.start')}
            hideLabel
            value={start}
            onChange={(event) => setStart(event.target.value)}
          />
        </div>
        <div style={{ width: 210, minWidth: 210 }}>
          <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginBottom: 4 }}>{t('history.end')}</div>
          <TextInput
            id="cb-h-end"
            type="datetime-local"
            labelText={t('history.end')}
            hideLabel
            value={end}
            onChange={(event) => setEnd(event.target.value)}
          />
        </div>
        {tab === 'data' ? (
          <>
            <div style={{ width: 130, minWidth: 130 }}>
              <Select
                id="cb-h-type"
                labelText={t('history.type')}
                hideLabel
                value={pointType}
                onChange={(event) => setPointType((event.target as HTMLSelectElement).value)}
              >
                <SelectItem value="" text={t('history.type')} />
                <SelectItem value="yx" text={t('history.type.yx')} />
                <SelectItem value="yc" text={t('history.type.yc')} />
                <SelectItem value="ym" text={t('history.type.ym')} />
              </Select>
            </div>
            <div style={{ width: 130, minWidth: 130 }}>
              <TextInput
                id="cb-h-ioa"
                type="number"
                labelText={t('history.ioa')}
                hideLabel
                min={0}
                placeholder={t('history.ioa')}
                value={ioa}
                onChange={(event) => setIoa(event.target.value)}
              />
            </div>
          </>
        ) : (
          <div style={{ width: 130, minWidth: 130 }}>
            <Select
              id="cb-h-direction"
              labelText={t('history.direction')}
              hideLabel
              value={direction}
              onChange={(event) => setDirection((event.target as HTMLSelectElement).value)}
            >
              <SelectItem value="" text={t('history.direction')} />
              <SelectItem value="rx" text={t('history.dir.rx')} />
              <SelectItem value="tx" text={t('history.dir.tx')} />
            </Select>
          </div>
        )}
        <div style={{ width: 110, minWidth: 110 }}>
          <TextInput
            id="cb-h-limit"
            type="number"
            labelText={t('history.limit')}
            hideLabel
            min={1}
            max={10000}
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
          />
        </div>
        <Button kind="primary" onClick={search}>
          {t('common.query')}
        </Button>
        <Button kind="secondary" onClick={reset}>
          {t('common.reset')}
        </Button>
        {tab !== 'curve' ? (
          <Button kind="ghost" onClick={() => window.open(exportUrl, '_blank')}>
            {t('history.export')}
          </Button>
        ) : null}
      </div>

      {tab === 'curve' ? (
        <div style={{ marginTop: 12 }}>
          <CarbonHistoryCurve start={applied.start} end={applied.end} />
        </div>
      ) : (
      <div style={{ marginTop: 12 }}>
        <TableFrame>
          <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
            <thead>
              {tab === 'data' ? (
                <tr>
                  <th style={{ width: 190, minWidth: 190 }}><span className="cds--table-header-label">{t('history.col.time')}</span></th>
                  <th style={{ width: 80, minWidth: 80 }}><span className="cds--table-header-label">{t('history.col.type')}</span></th>
                  <th style={{ width: 110, minWidth: 110 }}><span className="cds--table-header-label">{t('history.col.ioa')}</span></th>
                  <th style={{ width: 150, minWidth: 150 }}><span className="cds--table-header-label">{t('history.col.value')}</span></th>
                  <th style={{ width: 130, minWidth: 130 }}><span className="cds--table-header-label">{t('history.col.quality')}</span></th>
                  <th style={{ width: 100, minWidth: 100 }}><span className="cds--table-header-label">{t('history.col.source')}</span></th>
                </tr>
              ) : (
                <tr>
                  <th style={{ width: 190, minWidth: 190 }}><span className="cds--table-header-label">{t('history.col.time')}</span></th>
                  <th style={{ width: 80, minWidth: 80 }}><span className="cds--table-header-label">{t('history.col.direction')}</span></th>
                  <th style={{ width: 90, minWidth: 90 }}><span className="cds--table-header-label">{t('history.col.frameType')}</span></th>
                  <th><span className="cds--table-header-label">{t('history.col.hex')}</span></th>
                  <th style={{ width: 180, minWidth: 180 }}><span className="cds--table-header-label">{t('history.col.parsed')}</span></th>
                </tr>
              )}
            </thead>
            <tbody>
              {pageRows.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: 24, color: 'var(--cds-text-secondary)' }}>
                    {t('history.empty')}
                  </td>
                </tr>
              ) : tab === 'data' ? (
                (pageRows as HistoryDataRecord[]).map((row) => (
                  <tr key={row.id} data-testid="history-row">
                    <td className="mono">{formatDateTime(row.ts, localeTag(locale))}</td>
                    <td>{row.point_type}</td>
                    <td className="mono">{row.ioa}</td>
                    <td className="mono">{row.value}</td>
                    <td><CarbonQualityTags quality={row.quality} /></td>
                    <td>{row.source}</td>
                  </tr>
                ))
              ) : (
                (pageRows as HistoryFrameRecord[]).map((row) => (
                  <tr key={row.id} data-testid="history-row">
                    <td className="mono">{formatDateTime(row.ts, localeTag(locale))}</td>
                    <td>
                      <Tag size="sm" type={row.direction === 'rx' ? 'blue' : 'green'}>
                        {row.direction}
                      </Tag>
                    </td>
                    <td>{row.frame_type}</td>
                    <td className="mono" style={{ wordBreak: 'break-all' }}>{row.hex}</td>
                    <td>{row.parsed}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </TableFrame>
      </div>
      )}

      {tab !== 'curve' ? (
        <div style={{ marginTop: 8 }}>
          <Pager page={currentPage} pageSize={PAGE_SIZE} totalItems={rows.length} onChange={setPage} />
        </div>
      ) : null}
    </Panel>
  )
}
