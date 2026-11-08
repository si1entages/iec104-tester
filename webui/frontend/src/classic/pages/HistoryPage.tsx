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
import { useT } from '../i18n'
import type { MessageKey } from '../i18n'
import { useUiStore } from '../store/uiStore'

type TabKey = 'data' | 'frames'

/** applied 同时携带两个页签的过滤键（historyQuery 会跳过空值） */
type AppliedParams = HistoryDataParams & HistoryFramesParams

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

const DEFAULT_LIMIT = 500

interface FormState {
  range: [Dayjs | null, Dayjs | null] | null
  point_type?: string
  direction?: string
  ioa?: number
  limit: number
}

function localeTag(): string {
  return useUiStore.getState().locale === 'en' ? 'en-GB' : 'zh-CN'
}

function formatTime(ts: number): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString(localeTag(), { hour12: false })
}

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(localeTag())
}

function formatBytes(n: number): string {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function pointTypeOptions(t: TFn) {
  return [
    { value: 'yx', label: t('history.type.yx') },
    { value: 'yc', label: t('history.type.yc') },
    { value: 'ym', label: t('history.type.ym') },
  ]
}

function directionOptions(t: TFn) {
  return [
    { value: 'rx', label: t('history.dir.rx') },
    { value: 'tx', label: t('history.dir.tx') },
  ]
}

function makePagination(t: TFn) {
  return {
    pageSize: 50,
    showSizeChanger: true,
    showTotal: (total: number) => t('common.total', { n: total }),
  }
}

function makeFooter(t: TFn) {
  return function renderFooter() {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {t('history.footer')}
      </Typography.Text>
    )
  }
}

function useDataColumns(): TableColumnsType<HistoryDataRecord> {
  const t = useT()
  return useMemo(
    () => [
      {
        title: t('history.col.time'),
        dataIndex: 'ts',
        width: 190,
        render: (ts: number) => <span className="mono">{formatTime(ts)}</span>,
      },
      { title: t('history.col.type'), dataIndex: 'point_type', width: 80 },
      {
        title: t('history.col.ioa'),
        dataIndex: 'ioa',
        width: 110,
        render: (ioa: number) => <span className="mono">{ioa}</span>,
      },
      {
        title: t('history.col.value'),
        dataIndex: 'value',
        width: 150,
        render: (v: string) => <span className="mono">{v}</span>,
      },
      {
        title: t('history.col.quality'),
        dataIndex: 'quality',
        width: 110,
        render: (q: string) => q || '-',
      },
      { title: t('history.col.source'), dataIndex: 'source', width: 100 },
    ],
    [t],
  )
}

function useFrameColumns(): TableColumnsType<HistoryFrameRecord> {
  const t = useT()
  return useMemo(
    () => [
      {
        title: t('history.col.time'),
        dataIndex: 'ts',
        width: 190,
        render: (ts: number) => <span className="mono">{formatTime(ts)}</span>,
      },
      {
        title: t('history.col.direction'),
        dataIndex: 'direction',
        width: 80,
        render: (d: string) => <Tag color={d === 'rx' ? 'blue' : 'orange'}>{d}</Tag>,
      },
      { title: t('history.col.frameType'), dataIndex: 'frame_type', width: 80 },
      {
        title: t('history.col.hex'),
        dataIndex: 'hex',
        width: 320,
        render: (hex: string) => (
          <span className="mono" style={{ wordBreak: 'break-all' }}>
            {hex}
          </span>
        ),
      },
      {
        title: t('history.col.parsed'),
        dataIndex: 'parsed',
        ellipsis: true,
        render: (p: string) => p || '-',
      },
      {
        title: t('history.col.client'),
        dataIndex: 'client',
        width: 110,
        render: (c: string) => c || '-',
      },
    ],
    [t],
  )
}

export function HistoryPage() {
  const t = useT()
  const [tab, setTab] = useState<TabKey>('data')
  const [form, setForm] = useState<FormState>({ range: null, limit: DEFAULT_LIMIT })
  const [applied, setApplied] = useState<AppliedParams>({})

  const statsQuery = useHistoryStatsQuery()
  // 历史为静态存量数据：不自动轮询，由「查询」按钮变更 applied（queryKey 含 params）触发；
  // 切页签时按当前 applied 立即加载该页签的数据
  const dataQuery = useHistoryDataQuery(applied, tab === 'data')
  const framesQuery = useHistoryFramesQuery(applied, tab === 'frames')

  const dataColumns = useDataColumns()
  const frameColumns = useFrameColumns()
  const pagination = useMemo(() => makePagination(t), [t])
  const renderFooter = useMemo(() => makeFooter(t), [t])

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
          <span>{t('history.title')}</span>
          {!enabled && statsQuery.isSuccess ? (
            <Tag color="default">{t('history.disabled')}</Tag>
          ) : null}
          {enabled && stats ? (
            <>
              <Tag color="blue">{t('history.dataCount', { n: stats.data_records })}</Tag>
              <Tag color="blue">{t('history.frameCount', { n: stats.frame_records })}</Tag>
              {stats.buffered_data + stats.buffered_frames > 0 ? (
                <Tooltip title={t('history.bufferedTip')}>
                  <Tag>
                    {t('history.buffered', { n: stats.buffered_data + stats.buffered_frames })}
                  </Tag>
                </Tooltip>
              ) : null}
              {stats.dropped_records > 0 ? (
                <Tooltip title={t('history.droppedTip')}>
                  <Tag color="warning">{t('history.dropped', { n: stats.dropped_records })}</Tag>
                </Tooltip>
              ) : null}
              <Tooltip title={t('history.dbSizeTip')}>
                <Tag>{formatBytes(stats.db_size_bytes)}</Tag>
              </Tooltip>
              {stats.oldest_data ? (
                <Tooltip title={t('history.rangeTip')}>
                  <Tag>
                    {formatDate(stats.oldest_data)} ~ {formatDate(stats.newest_data)}
                  </Tag>
                </Tooltip>
              ) : null}
            </>
          ) : null}
          <Tag color="blue">{t('history.view', { n: rows.length })}</Tag>
          {truncated ? (
            <Tooltip title={t('history.limitTip', { n: activeLimit })}>
              <Tag color="warning">{t('history.limitReached')}</Tag>
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
            {t('common.refresh')}
          </Button>
          <Tooltip title={t('history.exportTip')}>
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              disabled={!enabled}
              onClick={() => window.open(exportUrl, '_blank')}
            >
              {t('history.export')}
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
          title={t('history.notEnabled')}
          description={t('history.notEnabledDesc')}
        />
      ) : null}
      <Space style={{ marginBottom: 12 }} wrap>
        <Segmented
          value={tab}
          onChange={(v) => setTab(v as TabKey)}
          options={[
            { label: t('history.tab.data'), value: 'data' },
            { label: t('history.tab.frames'), value: 'frames' },
          ]}
        />
        <DatePicker.RangePicker
          showTime
          value={form.range}
          onChange={(v) => setForm({ ...form, range: v })}
          placeholder={[t('history.start'), t('history.end')]}
        />
        {tab === 'data' ? (
          <>
            <Select
              style={{ width: 130 }}
              allowClear
              placeholder={t('history.type')}
              value={form.point_type}
              options={pointTypeOptions(t)}
              onChange={(v) => setForm({ ...form, point_type: v })}
            />
            <InputNumber
              style={{ width: 140 }}
              min={0}
              placeholder={t('history.ioa')}
              value={form.ioa}
              onChange={(v) => setForm({ ...form, ioa: v ?? undefined })}
            />
          </>
        ) : (
          <Select
            style={{ width: 130 }}
            allowClear
            placeholder={t('history.direction')}
            value={form.direction}
            options={directionOptions(t)}
            onChange={(v) => setForm({ ...form, direction: v })}
          />
        )}
        <InputNumber
          style={{ width: 110 }}
          min={1}
          max={10000}
          placeholder={t('history.limit')}
          value={form.limit}
          onChange={(v) => setForm({ ...form, limit: v ?? DEFAULT_LIMIT })}
        />
        <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
          {t('common.query')}
        </Button>
        <Button onClick={handleReset}>{t('common.reset')}</Button>
      </Space>
      {tab === 'data' ? (
        <Table<HistoryDataRecord>
          rowKey="id"
          size="small"
          loading={fetching}
          columns={dataColumns}
          dataSource={dataRows}
          pagination={pagination}
          scroll={{ x: 900, y: 420 }}
          footer={renderFooter}
        />
      ) : (
        <Table<HistoryFrameRecord>
          rowKey="id"
          size="small"
          loading={fetching}
          columns={frameColumns}
          dataSource={frameRows}
          pagination={pagination}
          scroll={{ x: 900, y: 420 }}
          footer={renderFooter}
        />
      )}
    </Card>
  )
}
