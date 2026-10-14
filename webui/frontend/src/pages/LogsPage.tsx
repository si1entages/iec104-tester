import { useMemo, useState } from 'react'

import { ClearOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Card, Input, Select, Space, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'

import { LOGS_EXPORT_URL } from '../api/endpoints'
import { clearLiveLogs, useLiveLogs, useLogsQuery } from '../api/queries'
import type { LogLevel, LogQueryParams, LogRow } from '../api/types'
import { useUiStore } from '../store/uiStore'

const LEVEL_ORDER: Record<string, number> = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
}

const LEVEL_COLOR: Record<string, string> = {
  DEBUG: 'default',
  INFO: 'blue',
  WARNING: 'orange',
  ERROR: 'red',
  CRITICAL: 'magenta',
}

const LEVEL_OPTIONS = (['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as LogLevel[]).map(
  (v) => ({ value: v, label: v }),
)

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

function matches(row: LogRow, params: LogQueryParams): boolean {
  const min = LEVEL_ORDER[params.level_min ?? 'DEBUG'] ?? 0
  if ((LEVEL_ORDER[row.level] ?? 0) < min) return false
  if (params.category && row.category !== params.category) return false
  if (params.source && row.source !== params.source) return false
  if (params.q && !row.message.toLowerCase().includes(params.q.toLowerCase())) return false
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
  const [levelMin, setLevelMin] = useState<string>('DEBUG')
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [keyword, setKeyword] = useState<string>('')

  const queryClient = useQueryClient()
  const params = useMemo<LogQueryParams>(
    () => ({ level_min: levelMin, category, q: keyword || undefined, limit: 200 }),
    [levelMin, category, keyword],
  )

  const liveLogs = useLiveLogs()
  const logsQuery = useLogsQuery(params)
  const wsStatus = useUiStore((s) => s.wsStatus)
  const droppedFrames = useUiStore((s) => s.droppedFrames)

  const rows = useMemo(() => {
    const seen = new Set<string>()
    const out: LogRow[] = []
    // 实时流优先（最新在上）
    for (let i = liveLogs.length - 1; i >= 0; i -= 1) {
      const row = liveLogs[i]
      if (!matches(row, params)) continue
      const key = rowKey(row)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(row)
    }
    // 再补历史（后端默认 newest_first）
    for (const row of logsQuery.data?.logs ?? []) {
      const key = rowKey(row)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(row)
    }
    return out.slice(0, 1000)
  }, [liveLogs, logsQuery.data, params])

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>日志</span>
          <Tag color="blue">实时 {liveLogs.length}</Tag>
          <Tag>历史 {logsQuery.data?.logs.length ?? 0}</Tag>
          {wsStatus !== 'open' ? <Tag color="orange">实时流已断开</Tag> : null}
          {droppedFrames > 0 ? <Tag color="warning">已丢帧 {droppedFrames}</Tag> : null}
        </Space>
      }
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void logsQuery.refetch()}>
            刷新
          </Button>
          <Button icon={<ClearOutlined />} onClick={() => clearLiveLogs(queryClient)}>
            清空实时
          </Button>
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
          style={{ width: 140 }}
          value={levelMin}
          options={LEVEL_OPTIONS}
          onChange={setLevelMin}
          placeholder="最低级别"
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
      />
    </Card>
  )
}
