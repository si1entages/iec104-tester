import { useMemo, useState } from 'react'

import {
  ClearOutlined,
  DownloadOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Card, Input, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import type { TableColumnsType } from 'antd'

import { LOGS_EXPORT_URL } from '../api/endpoints'
import { MAX_LIVE_LOGS, clearLiveLogs, useLiveLogs, useLogsQuery } from '../api/queries'
import type { LogLevel, LogRow } from '../api/types'
import { useT } from '../i18n'
import type { MessageKey } from '../i18n'
import { useUiStore } from '../store/uiStore'

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

/** 视图上限：超出部分截断（UI 明示，不静默丢弃——导出仍可取全量） */
const MAX_VIEW_ROWS = 1000

/** 与暗色主题（darkAlgorithm）兼容的 antd 预设色 */
const LEVEL_COLOR: Record<string, string> = {
  DEBUG: 'default',
  INFO: 'blue',
  WARNING: 'orange',
  ERROR: 'red',
  CRITICAL: 'magenta',
}

const ALL_LEVELS: LogLevel[] = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

const LEVEL_OPTIONS = ALL_LEVELS.map((v) => ({ value: v, label: v }))

const CATEGORY_OPTIONS = ['connection', 'protocol', 'command', 'data', 'ui', 'system'].map(
  (v) => ({ value: v, label: v }),
)

function formatTime(ts: number): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function rowKey(row: LogRow): string {
  return `${row.ts}|${row.source}|${row.level}|${row.message}`
}

function matches(row: LogRow, levels: Set<string>, category?: string, keyword?: string): boolean {
  if (!levels.has(row.level)) return false
  if (category && row.category !== category) return false
  if (keyword && !row.message.toLowerCase().includes(keyword.toLowerCase())) return false
  return true
}

function useLogColumns(t: TFn): TableColumnsType<LogRow> {
  return useMemo(
    () => [
      {
        title: t('logs.col.time'),
        dataIndex: 'ts',
        width: 190,
        render: (ts: number) => <span className="mono">{formatTime(ts)}</span>,
      },
      {
        title: t('logs.col.level'),
        dataIndex: 'level',
        width: 100,
        render: (level: string) => <Tag color={LEVEL_COLOR[level] ?? 'default'}>{level}</Tag>,
      },
      { title: t('logs.col.category'), dataIndex: 'category', width: 110 },
      { title: t('logs.col.source'), dataIndex: 'source', width: 100 },
      { title: t('logs.col.message'), dataIndex: 'message', ellipsis: true },
    ],
    [t],
  )
}

export function LogsPage() {
  const t = useT()
  const columns = useLogColumns(t)
  const [levels, setLevels] = useState<string[]>(ALL_LEVELS)
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [keyword, setKeyword] = useState<string>('')
  // 暂停 = 冻结当前视图。暂停期间 WS 实时流仍写入缓冲（上限 MAX_LIVE_LOGS 条），
  // 恢复后一次性合入，不丢日志；仅当缓冲超过上限回卷时更早的会被覆盖（UI 有提示）。
  const [paused, setPaused] = useState<boolean>(false)
  const [frozenRows, setFrozenRows] = useState<LogRow[] | null>(null)
  const [frozenLen, setFrozenLen] = useState<number>(0)

  const queryClient = useQueryClient()
  const liveLogs = useLiveLogs()
  const logsQuery = useLogsQuery({ q: keyword || undefined, category, limit: 2000 })
  // limit 2000 = 契约上限：视图合并（实时 500 + 历史 2000）足以触达视图截断线 1000
  const wsStatus = useUiStore((s) => s.wsStatus)
  const droppedFrames = useUiStore((s) => s.droppedFrames)

  const merged = useMemo(() => {
    const levelSet = new Set(levels)
    const seen = new Set<string>()
    const out: LogRow[] = []
    // 实时流优先（最新在上），再补历史（后端默认 newest_first）
    for (let i = liveLogs.length - 1; i >= 0; i -= 1) {
      const row = liveLogs[i]
      if (!matches(row, levelSet, category, keyword)) continue
      const key = rowKey(row)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(row)
    }
    for (const row of logsQuery.data?.logs ?? []) {
      if (!matches(row, levelSet, category, keyword)) continue
      const key = rowKey(row)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(row)
    }
    return out.slice(0, MAX_VIEW_ROWS)
  }, [liveLogs, logsQuery.data, levels, category, keyword])

  const rows = paused && frozenRows ? frozenRows : merged
  // 暂停期间新进缓冲的条数（缓冲上限回卷时以 0 起算并提示）
  const bufferedWhilePaused = paused ? Math.max(0, liveLogs.length - frozenLen) : 0
  const truncated = merged.length >= MAX_VIEW_ROWS

  const handlePause = (): void => {
    if (paused) {
      setPaused(false)
      setFrozenRows(null)
      return
    }
    setFrozenRows(merged)
    setFrozenLen(liveLogs.length)
    setPaused(true)
  }

  return (
    <Card
      size="small"
      title={
        <Space size={4} wrap>
          <span>{t('logs.title')}</span>
          <Tag color="blue">{t('logs.view', { n: rows.length })}</Tag>
          <Tooltip title={t('logs.bufferTip')}>
            <Tag>{t('logs.buffer', { n: liveLogs.length })}</Tag>
          </Tooltip>
          {typeof logsQuery.data?.stats?.total === 'number' ? (
            <Tooltip title={t('logs.backendTotalTip')}>
              <Tag>{t('logs.backendTotal', { n: logsQuery.data.stats.total })}</Tag>
            </Tooltip>
          ) : null}
          {paused ? (
            <Tag color="warning">
              {bufferedWhilePaused > 0
                ? t('logs.pausedBuffer', { n: bufferedWhilePaused })
                : t('logs.paused')}
            </Tag>
          ) : null}
          {wsStatus !== 'open' ? <Tag color="orange">{t('logs.streamDown')}</Tag> : null}
          {droppedFrames > 0 ? (
            <Tag color="warning">{t('logs.dropped', { n: droppedFrames })}</Tag>
          ) : null}
          {truncated ? (
            <Tooltip title={t('logs.truncatedTip', { n: MAX_VIEW_ROWS })}>
              <Tag color="warning">{t('logs.truncated', { n: MAX_VIEW_ROWS })}</Tag>
            </Tooltip>
          ) : null}
        </Space>
      }
      extra={
        <Space>
          <Tooltip title={t('logs.pauseTip')}>
            <Button
              icon={paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
              onClick={handlePause}
            >
              {paused ? t('logs.resume') : t('logs.pause')}
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => void logsQuery.refetch()}>
            {t('common.refresh')}
          </Button>
          <Tooltip title={t('logs.clearTip')}>
            <Button
              icon={<ClearOutlined />}
              onClick={() => {
                clearLiveLogs(queryClient)
                setFrozenRows(null)
                setPaused(false)
              }}
            >
              {t('logs.clear')}
            </Button>
          </Tooltip>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={() => window.open(LOGS_EXPORT_URL, '_blank')}
          >
            {t('logs.export')}
          </Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          mode="multiple"
          style={{ minWidth: 260 }}
          value={levels}
          options={LEVEL_OPTIONS}
          onChange={setLevels}
          placeholder={t('logs.levels')}
          maxTagCount="responsive"
        />
        <Select
          style={{ width: 160 }}
          allowClear
          value={category}
          options={CATEGORY_OPTIONS}
          onChange={setCategory}
          placeholder={t('logs.category')}
        />
        <Input.Search
          style={{ width: 260 }}
          allowClear
          placeholder={t('logs.keyword')}
          onSearch={setKeyword}
        />
      </Space>
      <Table<LogRow>
        rowKey={rowKey}
        size="small"
        loading={logsQuery.isLoading}
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (total) => t('common.total', { n: total }) }}
        scroll={{ x: 900, y: 420 }}
        footer={() => (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('logs.footer', { view: MAX_VIEW_ROWS, buffer: MAX_LIVE_LOGS })}
          </Typography.Text>
        )}
      />
    </Card>
  )
}
