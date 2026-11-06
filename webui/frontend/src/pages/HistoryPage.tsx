import { useMemo, useState } from 'react'

import { DownloadOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  DatePicker,
  InputNumber,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
import type { Dayjs } from 'dayjs'
import { buildUrl } from '../api/client'
import { HISTORY_EXPORT_URL } from '../api/endpoints'
import { useHistoryDataQuery, useHistoryFramesQuery, useHistoryStatsQuery } from '../api/queries'
import type { HistoryDataParams, HistoryDataRecord, HistoryFrameRecord, HistoryFramesParams } from '../api/types'

type TabKey = 'data' | 'frames'

/** applied 同时携带两个页签的过滤键（historyQuery 会跳过空值） */
type AppliedParams = HistoryDataParams & HistoryFramesParams

const DEFAULT_LIMIT = 500

interface FormState {
  range: [Dayjs | null, Dayjs | null] | null
  point_type?: string
  direction?: string
  ioa?: number
  limit: number
}

const POINT_TYPE_OPTIONS = [
  { value: 'yx', label: 'YX 遥信' },
  { value: 'yc', label: 'YC 遥测' },
  { value: 'ym', label: 'YM 遥脉' },
]

const DIRECTION_OPTIONS = [
  { value: 'rx', label: 'RX 接收' },
  { value: 'tx', label: 'TX 发送' },
]

const HISTORY_PAGINATION = {
  pageSize: 50,
  showSizeChanger: true,
  showTotal: (total: number) => `共 ${total} 条`,
}

function renderFooter() {
  return (
    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
      按 时间戳 新→旧 返回；单次查询上限 10000 条、CSV 导出上限 20 万行。
      数据记录来源：遥信/遥测/遥脉变化（spont/召唤/周期）。
    </Typography.Text>
  )
}

function formatTime(ts: number): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function formatBytes(n: number): string {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

const DATA_COLUMNS: TableColumnsType<HistoryDataRecord> = [
  {
    title: '时间',
    dataIndex: 'ts',
    width: 190,
    render: (ts: number) => <span className="mono">{formatTime(ts)}</span>,
  },
  { title: '类型', dataIndex: 'point_type', width: 80 },
  {
    title: 'IOA',
    dataIndex: 'ioa',
    width: 110,
    render: (ioa: number) => <span className="mono">{ioa}</span>,
  },
  {
    title: '值',
    dataIndex: 'value',
    width: 150,
    render: (v: string) => <span className="mono">{v}</span>,
  },
  { title: '品质', dataIndex: 'quality', width: 110, render: (q: string) => q || '-' },
  { title: '来源', dataIndex: 'source', width: 100 },
]

const FRAME_COLUMNS: TableColumnsType<HistoryFrameRecord> = [
  {
    title: '时间',
    dataIndex: 'ts',
    width: 190,
    render: (ts: number) => <span className="mono">{formatTime(ts)}</span>,
  },
  {
    title: '方向',
    dataIndex: 'direction',
    width: 80,
    render: (d: string) => <Tag color={d === 'rx' ? 'blue' : 'orange'}>{d}</Tag>,
  },
  { title: '帧类型', dataIndex: 'frame_type', width: 80 },
  {
    title: 'HEX',
    dataIndex: 'hex',
    width: 320,
    render: (hex: string) => (
      <span className="mono" style={{ wordBreak: 'break-all' }}>
        {hex}
      </span>
    ),
  },
  { title: '解析', dataIndex: 'parsed', ellipsis: true, render: (p: string) => p || '-' },
  { title: '客户端', dataIndex: 'client', width: 110, render: (c: string) => c || '-' },
]

export function HistoryPage() {
  const [tab, setTab] = useState<TabKey>('data')
  const [form, setForm] = useState<FormState>({ range: null, limit: DEFAULT_LIMIT })
  const [applied, setApplied] = useState<AppliedParams>({})

  const statsQuery = useHistoryStatsQuery()
  // 历史为静态存量数据：不自动轮询，由「查询」按钮变更 applied（queryKey 含 params）触发；
  // 切页签时按当前 applied 立即加载该页签的数据
  const dataQuery = useHistoryDataQuery(applied, tab === 'data')
  const framesQuery = useHistoryFramesQuery(applied, tab === 'frames')

  const enabled = statsQuery.data?.enabled === true
  const stats = statsQuery.data?.stats
  const dataRows = dataQuery.data?.rows ?? []
  const frameRows = framesQuery.data?.rows ?? []
  const rows: Array<HistoryDataRecord | HistoryFrameRecord> =
    tab === 'data' ? dataRows : frameRows
  const fetching = tab === 'data' ? dataQuery.isFetching : framesQuery.isFetching
  const activeLimit = applied.limit ?? DEFAULT_LIMIT
  const truncated = rows.length >= activeLimit

  const handleSearch = (): void => {
    setApplied({
      limit: form.limit || DEFAULT_LIMIT,
      start: form.range?.[0] ? Math.floor(form.range[0].valueOf() / 1000) : undefined,
      end: form.range?.[1] ? Math.ceil(form.range[1].valueOf() / 1000) : undefined,
      point_type: form.point_type,
      ioa: form.ioa,
      direction: form.direction,
    })
  }

  const handleReset = (): void => {
    setForm({ range: null, limit: DEFAULT_LIMIT })
    setApplied({})
  }

  // 导出沿用当前页签与 applied 过滤条件；limit 放宽到契约导出上限
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

  return (
    <Card
      size="small"
      title={
        <Space size={4} wrap>
          <span>历史查询</span>
          {!enabled && statsQuery.isSuccess ? <Tag color="default">未启用</Tag> : null}
          {enabled && stats ? (
            <>
              <Tag color="blue">数据 {stats.data_records}</Tag>
              <Tag color="blue">报文 {stats.frame_records}</Tag>
              {stats.buffered_data + stats.buffered_frames > 0 ? (
                <Tooltip title="已在内存缓冲、等待批量落盘的记录数">
                  <Tag>待落盘 {stats.buffered_data + stats.buffered_frames}</Tag>
                </Tooltip>
              ) : null}
              {stats.dropped_records > 0 ? (
                <Tooltip title="缓冲写满时丢弃最旧记录的累计值；请调小 flush_interval 或降低记录频率">
                  <Tag color="warning">已丢弃 {stats.dropped_records}</Tag>
                </Tooltip>
              ) : null}
              <Tooltip title="库文件实际数据占用">
                <Tag>{formatBytes(stats.db_size_bytes)}</Tag>
              </Tooltip>
              {stats.oldest_data ? (
                <Tooltip title="最早/最新数据记录时间">
                  <Tag>
                    {new Date(stats.oldest_data * 1000).toLocaleDateString('zh-CN')} ~{' '}
                    {new Date(stats.newest_data * 1000).toLocaleDateString('zh-CN')}
                  </Tag>
                </Tooltip>
              ) : null}
            </>
          ) : null}
          <Tag color="blue">视图 {rows.length}</Tag>
          {truncated ? (
            <Tooltip title={`结果达到本次查询上限 ${activeLimit} 条；如需更早日志请缩小时间范围或增大条数`}>
              <Tag color="warning">达到上限</Tag>
            </Tooltip>
          ) : null}
        </Space>
      }
      extra={
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void statsQuery.refetch()
              if (tab === 'data') void dataQuery.refetch()
              else void framesQuery.refetch()
            }}
          >
            刷新
          </Button>
          <Tooltip title="按当前页签与过滤条件导出 CSV（上限 20 万行）">
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              disabled={!enabled}
              onClick={() => window.open(exportUrl, '_blank')}
            >
              导出 CSV
            </Button>
          </Tooltip>
        </Space>
      }
    >
      {statsQuery.isSuccess && !enabled ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="历史库未启用"
          description="本次启动未开启历史库（--no-history 或初始化失败）。历史查询页在启用后可用；启用方式见用户手册「历史库」章节。"
        />
      ) : null}
      <Space style={{ marginBottom: 12 }} wrap>
        <Segmented
          value={tab}
          onChange={(v) => setTab(v as TabKey)}
          options={[
            { label: '数据', value: 'data' },
            { label: '报文', value: 'frames' },
          ]}
        />
        <DatePicker.RangePicker
          showTime
          value={form.range}
          onChange={(v) => setForm({ ...form, range: v })}
          placeholder={['开始时间', '结束时间']}
        />
        {tab === 'data' ? (
          <>
            <Select
              style={{ width: 130 }}
              allowClear
              placeholder="类型"
              value={form.point_type}
              options={POINT_TYPE_OPTIONS}
              onChange={(v) => setForm({ ...form, point_type: v })}
            />
            <InputNumber
              style={{ width: 140 }}
              min={0}
              placeholder="IOA"
              value={form.ioa}
              onChange={(v) => setForm({ ...form, ioa: v ?? undefined })}
            />
          </>
        ) : (
          <Select
            style={{ width: 130 }}
            allowClear
            placeholder="方向"
            value={form.direction}
            options={DIRECTION_OPTIONS}
            onChange={(v) => setForm({ ...form, direction: v })}
          />
        )}
        <InputNumber
          style={{ width: 110 }}
          min={1}
          max={10000}
          placeholder="条数"
          value={form.limit}
          onChange={(v) => setForm({ ...form, limit: v ?? DEFAULT_LIMIT })}
        />
        <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
          查询
        </Button>
        <Button onClick={handleReset}>重置</Button>
      </Space>
      {tab === 'data' ? (
        <Table<HistoryDataRecord>
          rowKey="id"
          size="small"
          loading={fetching}
          columns={DATA_COLUMNS}
          dataSource={dataRows}
          pagination={HISTORY_PAGINATION}
          scroll={{ x: 900, y: 420 }}
          footer={renderFooter}
        />
      ) : (
        <Table<HistoryFrameRecord>
          rowKey="id"
          size="small"
          loading={fetching}
          columns={FRAME_COLUMNS}
          dataSource={frameRows}
          pagination={HISTORY_PAGINATION}
          scroll={{ x: 900, y: 420 }}
          footer={renderFooter}
        />
      )}
    </Card>
  )
}
