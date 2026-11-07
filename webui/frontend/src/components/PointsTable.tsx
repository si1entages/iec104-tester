import { useDeferredValue, useMemo, useState } from 'react'
import type { MouseEvent } from 'react'

import { LineChartOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Input, Segmented, Space, Switch, Table, Tag, Typography, theme as antdTheme } from 'antd'
import type { TableColumnsType } from 'antd'

import { usePointsQuery } from '../api/queries'
import type { Point } from '../api/types'
import { useT } from '../i18n'
import type { MessageKey } from '../i18n'
import { formatValue } from '../lib/format'
import { directCommandHint } from '../lib/pointCommand'
import { pointKey } from '../lib/pointValue'
import { useResizableColumns } from '../hooks/useResizableColumns'
import { PointsTools } from './PointsTools'

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

/** 类型页签（第二批体验改造 ②）：全部 + 五类点；默认「全部」 */
function typeTabs(t: TFn) {
  return [
    { value: 'all', label: t('pt2.tab.all') },
    ...['YX', 'YC', 'YK', 'YM', 'STEP'].map((v) => ({ value: v, label: v })),
  ]
}

/**
 * 列定义。
 *
 * `onValueDoubleClick` 仅挂在「值」单元格上：双击行内其它列不触发命令，
 * 避免与选中/拖拽等表格交互冲突。值单元格始终带 `data-testid` 供 e2e 定位；
 * 只有命令点（YK/YC/STEP）才加指针样式与「双击下发…」悬停提示。
 */
function buildColumns(
  t: TFn,
  onValueDoubleClick?: (point: Point) => void,
): TableColumnsType<Point> {
  return [
    { title: t('status.col.ioa'), dataIndex: 'ioa', width: 100, className: 'mono' },
    { title: t('status.col.type'), dataIndex: 'type', width: 80 },
    // 名称/品质是长文本列：给宽默认值（可拖拽扩大），不再写死省略
    { title: t('status.col.name'), dataIndex: 'name', width: 360 },
    { title: t('status.col.group'), dataIndex: 'group', width: 70 },
    {
      title: t('status.col.enabled'),
      dataIndex: 'enabled',
      width: 80,
      render: (enabled: boolean) => (
        <Tag color={enabled ? 'green' : 'default'}>
          {enabled ? t('status.enabled') : t('status.disabled')}
        </Tag>
      ),
    },
    {
      title: t('status.col.value'),
      dataIndex: 'value',
      width: 150,
      onCell: (point) => {
        if (!onValueDoubleClick) return {}
        const hint = directCommandHint(point)
        return {
          onDoubleClick: (event: MouseEvent<HTMLElement>) => {
            event.stopPropagation()
            onValueDoubleClick(point)
          },
          ...(hint ? { title: hint, style: { cursor: 'pointer' as const } } : {}),
          'data-testid': `point-value-${pointKey(point)}`,
        }
      },
      render: (value: Point['value']) => {
        const text = formatValue(value)
        const color = text === 'ON' ? '#52c41a' : undefined
        return (
          <span className="mono" style={{ color }}>
            {text}
          </span>
        )
      },
    },
    { title: t('status.col.quality'), dataIndex: 'quality', width: 220, className: 'mono' },
  ]
}

const SCROLL_Y = 520

interface Props {
  selected: Point | null
  onSelect: (point: Point | null) => void
  /** 双击「值」单元格：主站传入后由确认弹窗下发命令；不传则保持纯浏览 */
  onValueDoubleClick?: (point: Point) => void
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
 * - **单击选中行**（主站据此下发命令、子站据此手动置数）
 * - **双击值单元格**（T21，仅主站传 `onValueDoubleClick`）：命令点打开确认弹窗
 *   直接下发；监视点仍只选中，不产生任何命令请求
 * - **类型页签**（第二批改造②）：全部/YX/YC/YK/YM/STEP，只影响**表格显示过滤**；
 *   PointsTools 批量操作保持原语义——按其弹窗内自选的类型与 IOA 列表对**全表**生效
 */
export function PointsTable({
  selected,
  onSelect,
  onValueDoubleClick,
  watchedKeys = [],
  onAddTrend,
  selectHint,
}: Props) {
  const t = useT()
  const { data: points = [], isLoading, isError, error } = usePointsQuery()
  const { token } = antdTheme.useToken()
  const tableHint =
    selectHint ??
    (onValueDoubleClick ? t('pt2.hint.command') : t('pt2.hint.select'))
  const baseColumns = useMemo(
    () => buildColumns(t, onValueDoubleClick),
    [t, onValueDoubleClick],
  )
  // 列宽拖拽（第二批改造③）：会话内记忆，virtual 表需要确定列宽故保留默认基线
  const { columns, headerComponents, totalWidth } = useResizableColumns(baseColumns)
  const [keyword, setKeyword] = useState('')
  // 类型页签：'all' = 不过滤；'YX'/'YC'/… = 只看该类型（取代原下拉选择器）
  const [typeTab, setTypeTab] = useState<string>('all')
  const [enabledOnly, setEnabledOnly] = useState(false)
  // 十万行过滤放到低优先级更新，保证输入框不掉帧
  const deferredKeyword = useDeferredValue(keyword)
  const type = typeTab === 'all' ? undefined : typeTab

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
          <span>{t('pt2.title')}</span>
          <Tag color="blue">{rows.length}</Tag>
          {rows.length !== points.length ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('pt2.total', { n: points.length })}
            </Typography.Text>
          ) : null}
          {selected ? (
            <Tag color="gold">
              {t('cmd.selected', { type: selected.type, ioa: selected.ioa })}
            </Tag>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {tableHint}
            </Typography.Text>
          )}
        </Space>
      }
      extra={
        <Space wrap>
          <PointsTools />
          <Button
            size="small"
            icon={<LineChartOutlined />}
            disabled={!selected || !onAddTrend || watchedKeys.includes(pointKey(selected))}
            onClick={() => selected && onAddTrend?.(selected)}
          >
            {t('pt2.addTrend')}
          </Button>
          <Input.Search
            size="small"
            style={{ width: 200 }}
            allowClear
            placeholder={t('pt2.filterPlaceholder')}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <span style={{ color: token.colorTextTertiary, fontSize: 12 }}>{t('pt2.enabledOnly')}</span>
          <Switch size="small" checked={enabledOnly} onChange={setEnabledOnly} />
        </Space>
      }
    >
      {isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 8 }}
          title={t('pt2.loadFailed')}
          description={String((error as Error)?.message ?? error)}
        />
      ) : null}
      <Segmented
        size="small"
        style={{ marginBottom: 8 }}
        options={typeTabs(t)}
        value={typeTab}
        onChange={(v) => setTypeTab(String(v))}
      />
      <Table<Point>
        virtual
        rowKey={pointKey}
        size="small"
        loading={isLoading}
        columns={columns}
        components={headerComponents}
        dataSource={rows}
        pagination={false}
        scroll={{ y: SCROLL_Y, x: totalWidth + 40 }}
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
