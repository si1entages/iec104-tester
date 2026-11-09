import { useMemo, useState } from 'react'

import { Button, Search, Select, SelectItem, Tag } from '@carbon/react'
import { useQueryClient } from '@tanstack/react-query'

import { apiUrl } from '../../api/client'
import { LOGS_EXPORT_URL } from '../../api/endpoints'
import { clearLiveLogs, useLiveLogs, useLogsQuery } from '../../api/queries'
import type { LogRow } from '../../api/types'
import { useLocale, useT } from '../../i18n'
import { formatDateTime, localeTag } from '../../lib/format'
import { useUiStore } from '../../store/uiStore'
import { CheckField, Panel, Pager, TableFrame } from '../components/ui'

const ALL_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
const MAX_VIEW_ROWS = 1000
const PAGE_SIZE = 100

const LEVEL_TONE: Record<string, 'blue' | 'magenta' | 'red' | 'gray' | 'cool-gray'> = {
  DEBUG: 'cool-gray',
  INFO: 'blue',
  WARNING: 'magenta',
  ERROR: 'red',
  CRITICAL: 'red',
}

const CATEGORIES = ['connection', 'protocol', 'command', 'data', 'ui', 'system']

function rowKey(row: LogRow): string {
  return `${row.ts}|${row.source}|${row.level}|${row.message}`
}

export function CarbonLogsPage() {
  const t = useT()
  const locale = useLocale()
  const queryClient = useQueryClient()
  const [levels, setLevels] = useState<string[]>(ALL_LEVELS)
  const [category, setCategory] = useState('')
  const [keyword, setKeyword] = useState('')
  const [paused, setPaused] = useState(false)
  const [frozenRows, setFrozenRows] = useState<LogRow[] | null>(null)
  const [frozenLen, setFrozenLen] = useState(0)
  const [page, setPage] = useState(1)

  const liveLogs = useLiveLogs()
  const logsQuery = useLogsQuery({ q: keyword || undefined, category: category || undefined, limit: 2000 })
  const wsStatus = useUiStore((s) => s.wsStatus)
  const droppedFrames = useUiStore((s) => s.droppedFrames)

  const merged = useMemo(() => {
    const levelSet = new Set(levels)
    const cat = category || undefined
    const kw = keyword.trim().toLowerCase()
    const seen = new Set<string>()
    const out: LogRow[] = []
    const match = (row: LogRow): boolean => {
      if (!levelSet.has(row.level)) return false
      if (cat && row.category !== cat) return false
      if (kw && !row.message.toLowerCase().includes(kw) && !row.source.toLowerCase().includes(kw)) return false
      return true
    }
    for (let i = liveLogs.length - 1; i >= 0; i -= 1) {
      const row = liveLogs[i]
      if (!match(row)) continue
      const key = rowKey(row)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(row)
    }
    for (const row of logsQuery.data?.logs ?? []) {
      if (!match(row)) continue
      const key = rowKey(row)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(row)
    }
    return out.slice(0, MAX_VIEW_ROWS)
  }, [liveLogs, logsQuery.data, levels, category, keyword])

  const rows = paused && frozenRows ? frozenRows : merged
  const bufferedWhilePaused = paused ? Math.max(0, liveLogs.length - frozenLen) : 0
  const truncated = merged.length >= MAX_VIEW_ROWS

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageRows = rows.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  const toggleLevel = (level: string, checked: boolean): void => {
    setLevels((prev) => {
      const next = checked ? [...new Set([...prev, level])] : prev.filter((l) => l !== level)
      return next.length > 0 ? next : ALL_LEVELS
    })
  }

  return (
    <Panel
      title={
        <span className="app-row">
          {t('logs.title')}
          <Tag size="sm" type="blue">{t('logs.view', { n: rows.length })}</Tag>
          <Tag size="sm" type="gray">{t('logs.buffer', { n: liveLogs.length })}</Tag>
          {typeof logsQuery.data?.stats?.total === 'number' ? (
            <Tag size="sm" type="gray">{t('logs.backendTotal', { n: logsQuery.data.stats.total })}</Tag>
          ) : null}
          {paused ? (
            <Tag size="sm" type="magenta">
              {bufferedWhilePaused > 0 ? t('logs.pausedBuffer', { n: bufferedWhilePaused }) : t('logs.paused')}
            </Tag>
          ) : null}
          {wsStatus !== 'open' ? <Tag size="sm" type="red">{t('logs.streamDown')}</Tag> : null}
          {droppedFrames > 0 ? <Tag size="sm" type="magenta">{t('logs.dropped', { n: droppedFrames })}</Tag> : null}
          {truncated ? <Tag size="sm" type="magenta">{t('logs.truncated', { n: MAX_VIEW_ROWS })}</Tag> : null}
        </span>
      }
    >
      <div className="app-row" style={{ alignItems: 'flex-end' }}>
        <div style={{ width: 420, minWidth: 420 }}>
          <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginBottom: 4 }}>{t('logs.levels')}</div>
          <div className="app-row">
            {ALL_LEVELS.map((level) => (
              <CheckField
                key={level}
                id={`cb-log-level-${level}`}
                label={level}
                checked={levels.includes(level)}
                onChange={(checked) => toggleLevel(level, checked)}
              />
            ))}
          </div>
        </div>
        <div style={{ width: 170, minWidth: 170 }}>
          <Select
            id="cb-log-category"
            labelText={t('logs.category')}
            hideLabel
            value={category}
            onChange={(event) => setCategory((event.target as HTMLSelectElement).value)}
          >
            <SelectItem value="" text={t('common.all')} />
            {CATEGORIES.map((c) => (
              <SelectItem key={c} value={c} text={c} />
            ))}
          </Select>
        </div>
        <div style={{ width: 260, minWidth: 260 }}>
          <Search
            id="cb-log-search"
            labelText={t('logs.search')}
            placeholder={t('logs.search')}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onClear={() => setKeyword('')}
          />
        </div>
        <Button
          kind="secondary"
          onClick={() => {
            if (paused) {
              setPaused(false)
              setFrozenRows(null)
            } else {
              setFrozenRows(merged)
              setFrozenLen(liveLogs.length)
              setPaused(true)
            }
          }}
        >
          {paused ? t('logs.resume') : t('logs.pause')}
        </Button>
        <Button
          kind="secondary"
          onClick={() => {
            clearLiveLogs(queryClient)
            setFrozenRows(null)
            setPaused(false)
            setPage(1)
          }}
        >
          {t('logs.clear')}
        </Button>
        <Button kind="primary" onClick={() => window.open(apiUrl(LOGS_EXPORT_URL), '_blank')}>
          {t('logs.export')}
        </Button>
      </div>

      <div style={{ marginTop: 12 }}>
        <TableFrame>
          <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
            <thead>
              <tr>
                <th style={{ width: 190, minWidth: 190 }}><span className="cds--table-header-label">{t('logs.col.time')}</span></th>
                <th style={{ width: 100, minWidth: 100 }}><span className="cds--table-header-label">{t('logs.col.level')}</span></th>
                <th style={{ width: 110, minWidth: 110 }}><span className="cds--table-header-label">{t('logs.col.category')}</span></th>
                <th style={{ width: 100, minWidth: 100 }}><span className="cds--table-header-label">{t('logs.col.source')}</span></th>
                <th><span className="cds--table-header-label">{t('logs.col.message')}</span></th>
              </tr>
            </thead>
            <tbody>
              {pageRows.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: 24, color: 'var(--cds-text-secondary)' }}>
                    {t('logs.empty')}
                  </td>
                </tr>
              ) : (
                pageRows.map((row) => (
                  <tr key={rowKey(row)} data-testid="log-row">
                    <td className="mono">{formatDateTime(row.ts, localeTag(locale))}</td>
                    <td>
                      <Tag size="sm" type={LEVEL_TONE[row.level] ?? 'gray'}>
                        {row.level}
                      </Tag>
                    </td>
                    <td>{row.category}</td>
                    <td>{row.source}</td>
                    <td>{row.message}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </TableFrame>
      </div>

      <div style={{ marginTop: 8 }}>
        <Pager page={currentPage} pageSize={PAGE_SIZE} totalItems={rows.length} onChange={setPage} />
      </div>
    </Panel>
  )
}
