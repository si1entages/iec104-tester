import { useDeferredValue, useMemo, useState } from 'react'

import { LineChartOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Input, Select, Space, Switch, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'

import { usePointsQuery } from '../api/queries'
import type { Point } from '../api/types'
import { formatValue } from '../lib/format'
import { pointKey } from '../lib/pointValue'

const TYPE_OPTIONS = ['YX', 'YC', 'YK', 'YM'].map((v) => ({ value: v, label: v }))

const COLUMNS: TableColumnsType<Point> = [
  { title: 'IOA', dataIndex: 'ioa', width: 100, className: 'mono' },
  { title: '类型', dataIndex: 'type', width: 80 },
  { title: '名称', dataIndex: 'name', width: 360, ellipsis: true },
  { title: '组', dataIndex: 'group', width: 70 },
  {
    title: '使能',
    dataIndex: 'enabled',
    width: 80,
    render: (enabled: boolean) => (
      <Tag color={enabled ? 'green' : 'default'}>{enabled ? '启用' : '停用'}</Tag>
    ),
  },
  {
    title: '值',
    dataIndex: 'value',
    width: 150,
    render: (value: Point['value']) => {
      const text = formatValue(value)
      const color =
        text === 'ON' ? '#52c41a' : text === 'OFF' ? '#8c8c8c' : undefined
      return (
        <span className="mono" style={{ color }}>
          {text}
        </span>
      )
    },
  },
  { title: '品质', dataIndex: 'quality', width: 220, ellipsis: true, className: 'mono' },
]

const SCROLL_Y = 520
const SCROLL_X = COLUMNS.reduce((sum, c) => sum + Number(c?.width ?? 0), 0)

interface Props {
  selected: Point | null
  onSelect: (point: Point | null) => void
  /** 已加入趋势的点位键（`类别-IOA`），用于置灰按钮 */
  watchedKeys?: string[]
  onAddTrend?: (point: Point) => void
  /** 未选中时的引导文案；主站/子站用途不同，这里可覆盖 */
  selectHint?: string
}

/**
 * 点表视图（T12）——**主站与子站共用的共享组件**。
 *
 * - **十万行虚拟滚动**：`virtual` + 固定 `scroll.y`，只渲染可视窗口内的行
 * - **就地更新单元格**：值由 WS 增量补丁/合并快照写入 React Query，
 *   仅变化行换新对象（见 `lib/pointValue.ts`），正常行保持引用不重渲染
 * - **单击选中行**（主站据此下发命令、子站据此手动置数）——**刻意不提供双击路径**
 */
export function PointsTable({
  selected,
  onSelect,
  watchedKeys = [],
  onAddTrend,
  selectHint = '单击行以选中并下发命令',
}: Props) {
  const { data: points = [], isLoading, isError, error } = usePointsQuery()
  const [keyword, setKeyword] = useState('')
  const [type, setType] = useState<string | undefined>(undefined)
  const [enabledOnly, setEnabledOnly] = useState(false)
  // 十万行过滤放到低优先级更新，保证输入框不掉帧
  const deferredKeyword = useDeferredValue(keyword)

  const rows = useMemo(() => {
    const kw = deferredKeyword.trim().toLowerCase()
    if (!kw && !type && !enabledOnly) return points
    return points.filter(
      (p) =>
        (!type || p.type === type) &&
        (!enabledOnly || p.enabled) &&
        (!kw || p.name.toLowerCase().includes(kw) || String(p.ioa).includes(kw)),
    )
  }, [points, deferredKeyword, type, enabledOnly])

  const selectedKey = selected ? pointKey(selected) : null

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>点表</span>
          <Tag color="blue">{rows.length}</Tag>
          {rows.length !== points.length ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              / 共 {points.length}
            </Typography.Text>
          ) : null}
          {selected ? (
            <Tag color="gold">
              已选 {selected.type}-{selected.ioa}
            </Tag>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {selectHint}
            </Typography.Text>
          )}
        </Space>
      }
      extra={
        <Space wrap>
          <Button
            size="small"
            icon={<LineChartOutlined />}
            disabled={!selected || !onAddTrend || watchedKeys.includes(pointKey(selected))}
            onClick={() => selected && onAddTrend?.(selected)}
          >
            加入趋势
          </Button>
          <Select
            size="small"
            style={{ width: 96 }}
            allowClear
            placeholder="类型"
            value={type}
            options={TYPE_OPTIONS}
            onChange={setType}
          />
          <Input.Search
            size="small"
            style={{ width: 200 }}
            allowClear
            placeholder="按名称 / IOA 过滤"
            onChange={(e) => setKeyword(e.target.value)}
          />
          <span style={{ color: '#8c8c8c', fontSize: 12 }}>仅启用</span>
          <Switch size="small" checked={enabledOnly} onChange={setEnabledOnly} />
        </Space>
      }
    >
      {isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 8 }}
          message="读取 /api/points 失败"
          description={String((error as Error)?.message ?? error)}
        />
      ) : null}
      <Table<Point>
        virtual
        rowKey={pointKey}
        size="small"
        loading={isLoading}
        columns={COLUMNS}
        dataSource={rows}
        pagination={false}
        scroll={{ y: SCROLL_Y, x: SCROLL_X }}
        rowSelection={{
          type: 'radio',
          columnWidth: 40,
          selectedRowKeys: selectedKey ? [selectedKey] : [],
          onChange: (_keys, selectedRows) => onSelect(selectedRows[0] ?? null),
        }}
        onRow={(row) => ({
          onClick: () => onSelect(row),
        })}
      />
    </Card>
  )
}
