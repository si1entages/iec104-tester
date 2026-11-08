import { useMemo, useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Checkbox,
  Flex,
  FormSelect,
  FormSelectOption,
  Label,
  Pagination,
  SearchInput,
} from '@patternfly/react-core'
import { useQueryClient } from '@tanstack/react-query'

import { apiUrl } from '../../api/client'
import { LOGS_EXPORT_URL } from '../../api/endpoints'
import { clearLiveLogs, useLiveLogs, useLogsQuery } from '../../api/queries'
import type { LogRow } from '../../api/types'
import { useLocale, useT } from '../../i18n'
import { formatDateTime, localeTag } from '../../lib/format'
import { useUiStore } from '../../store/uiStore'

const ALL_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
const MAX_VIEW_ROWS = 1000
const PAGE_SIZE = 100

const LEVEL_COLOR: Record<string, 'blue' | 'orange' | 'red' | 'grey'> = {
  DEBUG: 'grey',
  INFO: 'blue',
  WARNING: 'orange',
  ERROR: 'red',
  CRITICAL: 'red',
}

const CATEGORIES = ['connection', 'protocol', 'command', 'data', 'ui', 'system']

function rowKey(row: LogRow): string {
  return `${row.ts}|${row.source}|${row.level}|${row.message}`
}

export function PfLogsPage() {
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
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          <span>{t('logs.title')}</span>
          <Label isCompact color="blue">
            {t('logs.view', { n: rows.length })}
          </Label>
          <Label isCompact>{t('logs.buffer', { n: liveLogs.length })}</Label>
          {typeof logsQuery.data?.stats?.total === 'number' ? (
            <Label isCompact>{t('logs.backendTotal', { n: logsQuery.data.stats.total })}</Label>
          ) : null}
          {paused ? (
            <Label isCompact color="orange">
              {bufferedWhilePaused > 0 ? t('logs.pausedBuffer', { n: bufferedWhilePaused }) : t('logs.paused')}
            </Label>
          ) : null}
          {wsStatus !== 'open' ? (
            <Label isCompact color="red">
              {t('logs.streamDown')}
            </Label>
          ) : null}
          {droppedFrames > 0 ? (
            <Label isCompact color="orange">
              {t('logs.dropped', { n: droppedFrames })}
            </Label>
          ) : null}
          {truncated ? (
            <Label isCompact color="orange">
              {t('logs.truncated', { n: MAX_VIEW_ROWS })}
            </Label>
          ) : null}
        </Flex>
      </CardTitle>
      <CardBody>
        <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
          <div style={{ width: 420, minWidth: 420 }}>
            <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 4 }}>{t('logs.levels')}</div>
            <Flex gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
              {ALL_LEVELS.map((level) => (
                <Checkbox
                  key={level}
                  id={`pf-log-level-${level}`}
                  label={level}
                  isChecked={levels.includes(level)}
                  onChange={(_event, checked) => toggleLevel(level, checked)}
                />
              ))}
            </Flex>
          </div>
          <div style={{ width: 170, minWidth: 170 }}>
            <FormSelect value={category} onChange={(_e, v) => setCategory(v)} aria-label={t('logs.category')}>
              <FormSelectOption value="" label={t('common.all')} />
              {CATEGORIES.map((c) => (
                <FormSelectOption key={c} value={c} label={c} />
              ))}
            </FormSelect>
          </div>
          <div style={{ width: 260, minWidth: 260 }}>
            <SearchInput
              placeholder={t('logs.search')}
              value={keyword}
              onChange={(_e, v) => setKeyword(v)}
              onClear={() => setKeyword('')}
            />
          </div>
          <Button
            variant="secondary"
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
            variant="secondary"
            onClick={() => {
              clearLiveLogs(queryClient)
              setFrozenRows(null)
              setPaused(false)
              setPage(1)
            }}
          >
            {t('logs.clear')}
          </Button>
          <Button variant="primary" onClick={() => window.open(apiUrl(LOGS_EXPORT_URL), '_blank')}>
            {t('logs.export')}
          </Button>
        </Flex>

        <div style={{ marginTop: 12, overflowX: 'auto' }}>
          <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
            <thead className="pf-v6-c-table__thead">
              <tr className="pf-v6-c-table__tr">
                <th className="pf-v6-c-table__th" style={{ width: 190, minWidth: 190 }}>
                  {t('logs.col.time')}
                </th>
                <th className="pf-v6-c-table__th" style={{ width: 100, minWidth: 100 }}>
                  {t('logs.col.level')}
                </th>
                <th className="pf-v6-c-table__th" style={{ width: 110, minWidth: 110 }}>
                  {t('logs.col.category')}
                </th>
                <th className="pf-v6-c-table__th" style={{ width: 100, minWidth: 100 }}>
                  {t('logs.col.source')}
                </th>
                <th className="pf-v6-c-table__th">{t('logs.col.message')}</th>
              </tr>
            </thead>
            <tbody className="pf-v6-c-table__tbody">
              {pageRows.length === 0 ? (
                <tr className="pf-v6-c-table__tr">
                  <td className="pf-v6-c-table__td" colSpan={5} style={{ textAlign: 'center', padding: 24, opacity: 0.7 }}>
                    {t('logs.empty')}
                  </td>
                </tr>
              ) : (
                pageRows.map((row) => (
                  <tr key={rowKey(row)} className="pf-v6-c-table__tr" data-testid="log-row">
                    <td className="pf-v6-c-table__td mono">{formatDateTime(row.ts, localeTag(locale))}</td>
                    <td className="pf-v6-c-table__td">
                      <Label isCompact color={LEVEL_COLOR[row.level] ?? 'grey'}>
                        {row.level}
                      </Label>
                    </td>
                    <td className="pf-v6-c-table__td">{row.category}</td>
                    <td className="pf-v6-c-table__td">{row.source}</td>
                    <td className="pf-v6-c-table__td">{row.message}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: 8 }}>
          <Pagination
            itemCount={rows.length}
            perPage={PAGE_SIZE}
            page={currentPage}
            onSetPage={(_event, p) => setPage(p)}
            isCompact
          />
        </div>
      </CardBody>
    </Card>
  )
}
