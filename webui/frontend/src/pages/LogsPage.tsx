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
import { useUiStore } from '../store/uiStore'

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

const columns: TableColumnsType<LogRow> = [
  {
    title: '时间',
    dataIndex: 'ts',
    width: 190,
    render: (ts: number) => <span className="mono">{formatTime(ts)}</span>,
  },
  {
    title: '级别',
    dataIndex: 'level',
    width: 100,
    render: (level: string) => <Tag color={LEVEL_COLOR[level] ?? 'default'}>{level}</Tag>,
  },
  { title: '分类', dataIndex: 'category', width: 110 },
  { title: '来源', dataIndex: 'source', width: 100 },
  { title: '消息', dataIndex: 'message', ellipsis: true },
]

export function LogsPage() {
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
          <span>日志</span>
          <Tag color="blue">视图 {rows.length}</Tag>
          <Tooltip title="前端实时缓冲上限 500 条（超出回卷丢弃最旧），历史日志由 GET /api/logs 提供">
            <Tag>缓冲 {liveLogs.length}</Tag>
          </Tooltip>
          {typeof logsQuery.data?.stats?.total === 'number' ? (
            <Tooltip title="后端累计日志条数（LogStats.total）">
              <Tag>后端累计 {logsQuery.data.stats.total}</Tag>
            </Tooltip>
          ) : null}
          {paused ? (
            <Tag color="warning">已暂停{bufferedWhilePaused > 0 ? ` · 新缓冲 ${bufferedWhilePaused} 条` : ''}</Tag>
          ) : null}
          {wsStatus !== 'open' ? <Tag color="orange">实时流已断开</Tag> : null}
          {droppedFrames > 0 ? <Tag color="warning">后端丢帧 {droppedFrames}</Tag> : null}
          {truncated ? (
            <Tooltip title={`视图仅保留最近 ${MAX_VIEW_ROWS} 条；更早日志请缩小过滤范围或用「导出」获取全量`}>
              <Tag color="warning">已截断（上限 {MAX_VIEW_ROWS}）</Tag>
            </Tooltip>
          ) : null}
        </Space>
      }
      extra={
        <Space>
          <Tooltip title="冻结当前视图；恢复后把暂停期间的实时日志一次性合入（不丢失）">
            <Button
              icon={paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
              onClick={handlePause}
            >
              {paused ? '恢复实时' : '暂停实时'}
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => void logsQuery.refetch()}>
            刷新
          </Button>
          <Tooltip title="仅清空前端实时缓冲与当前视图；后端日志文件与「导出」内容不受影响">
            <Button
              icon={<ClearOutlined />}
              onClick={() => {
                clearLiveLogs(queryClient)
                setFrozenRows(null)
                setPaused(false)
              }}
            >
              清空视图
            </Button>
          </Tooltip>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={() => window.open(LOGS_EXPORT_URL, '_blank')}
          >
            导出 JSONL
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
          placeholder="级别（多选）"
          maxTagCount="responsive"
        />
        <Select
          style={{ width: 160 }}
          allowClear
          value={category}
          options={CATEGORY_OPTIONS}
          onChange={setCategory}
          placeholder="分类"
        />
        <Input.Search
          style={{ width: 260 }}
          allowClear
          placeholder="关键字搜索"
          onSearch={setKeyword}
        />
      </Space>
      <Table<LogRow>
        rowKey={rowKey}
        size="small"
        loading={logsQuery.isLoading}
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 900, y: 420 }}
        footer={() => (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            实时流经 250ms 批量合并写入（不逐条渲染）；视图上限 {MAX_VIEW_ROWS} 条、实时缓冲上限{' '}
            {MAX_LIVE_LOGS} 条，超出部分截断/回卷（此处有标注，不静默丢弃）。
          </Typography.Text>
        )}
      />
    </Card>
  )
}
