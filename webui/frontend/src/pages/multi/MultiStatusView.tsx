import { Alert, Button, Card, Col, Empty, Popconfirm, Row, Space, Statistic, Table, Tag, Tooltip, theme as antdTheme } from 'antd'
import type { TableColumnsType } from 'antd'

import type { MultiStatusResponse, MultiSummaryResponse, StationStatus } from '../../api/types'

interface Props {
  summary?: MultiSummaryResponse
  status?: MultiStatusResponse
  loading?: boolean
  isError?: boolean
  error?: unknown
  /** 运行中：对单个站「停用」（会重建管理器，需二次确认） */
  onDisableStation?: (stationId: string) => void
  busy?: boolean
}

function formatUptime(seconds: number): string {
  if (!seconds || seconds <= 0) return '-'
  const s = Math.floor(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

const COLUMNS = (onDisable?: (id: string) => void, busy?: boolean): TableColumnsType<StationStatus> => [
  { title: '站标识', dataIndex: 'station_id', width: 150, className: 'mono' },
  { title: '站名', dataIndex: 'station_name', width: 160, ellipsis: true },
  { title: '端口', dataIndex: 'port', width: 80, className: 'mono' },
  { title: '公共地址', dataIndex: 'common_addr', width: 90, className: 'mono' },
  {
    title: '运行',
    dataIndex: 'running',
    width: 80,
    render: (running: boolean) => (
      <Tag color={running ? 'success' : 'default'}>{running ? '运行中' : '已停止'}</Tag>
    ),
  },
  {
    title: '客户端',
    dataIndex: 'client_count',
    width: 80,
    render: (n: number) => <span style={{ color: n > 0 ? '#52c41a' : undefined }}>{n}</span>,
  },
  {
    title: '点数 YX/YC/YK/YM',
    width: 170,
    className: 'mono',
    render: (_v, row) => `${row.yx_count}/${row.yc_count}/${row.yk_count}/${row.ym_count}`,
  },
  {
    title: '模拟',
    dataIndex: 'simulation_active',
    width: 80,
    render: (on: boolean) => (on ? <Tag color="green">开</Tag> : <Tag>关</Tag>),
  },
  {
    title: '操作',
    width: 130,
    render: (_v, row) =>
      onDisable ? (
        <Popconfirm
          title={`停用 ${row.station_id}？`}
          description="后端只支持整体启停：会先停止全部站，再以「其余站」重新启动。其他站的连接会短暂断开。"
          okText="确认停用并重建"
          cancelText="取消"
          onConfirm={() => onDisable(row.station_id)}
        >
          <Button size="small" danger type="text" disabled={busy}>
            停用此站
          </Button>
        </Popconfirm>
      ) : (
        '-'
      ),
  },
]

/**
 * 多站聚合状态视图（T16）。
 *
 * - **汇总卡**：消费 `GET /api/multi/summary`（运行中 / 站数 / 总客户端 / 运行时长 / 四类点合计）
 * - **明细表**：消费 `GET /api/multi/status` 的 `stations[]`（`StationStatus`），
 *   逐站展示运行状态、客户端连接数、点位数、模拟开关
 *
 * 两个端点都由页面轮询驱动（页面卸载即停）。
 */
export function MultiStatusView({ summary, status, loading, isError, error, onDisableStation, busy }: Props) {
  const { token } = antdTheme.useToken()
  const stations = status?.stations ?? []
  const running = Boolean(summary?.running ?? status?.running)

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>聚合状态</span>
          <Tag color={running ? 'success' : 'default'}>{running ? '运行中' : '未运行'}</Tag>
        </Space>
      }
    >
      {isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="读取 /api/multi/status・/api/multi/summary 失败"
          description={String((error as Error)?.message ?? error)}
        />
      ) : null}

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={4}>
          <Statistic title="站数" value={summary?.station_count ?? stations.length} />
        </Col>
        <Col span={4}>
          <Statistic
            title="总客户端"
            value={summary?.total_clients ?? 0}
            valueStyle={{ color: (summary?.total_clients ?? 0) > 0 ? token.colorSuccess : undefined }}
          />
        </Col>
        <Col span={4}>
          <Statistic title="运行时长" value={formatUptime(summary?.uptime ?? 0)} />
        </Col>
        <Col span={4}>
          <Tooltip title="全部站的 YX/YC/YK/YM 点数合计">
            <Statistic
              title="点合计"
              value={
                summary
                  ? (summary.total_yx ?? 0) +
                    (summary.total_yc ?? 0) +
                    (summary.total_yk ?? 0) +
                    (summary.total_ym ?? 0)
                  : stations.reduce(
                      (n, s) => n + s.yx_count + s.yc_count + s.yk_count + s.ym_count,
                      0,
                    )
              }
            />
          </Tooltip>
        </Col>
        <Col span={4}>
          <Statistic
            title="在线站"
            value={stations.filter((s) => s.running).length}
            suffix={`/ ${stations.length}`}
          />
        </Col>
      </Row>

      {stations.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="没有正在运行的多站（用上方配置列表启动）"
        />
      ) : (
        <Table<StationStatus>
          rowKey="station_id"
          size="small"
          loading={loading}
          columns={COLUMNS(onDisableStation, busy)}
          dataSource={stations}
          pagination={false}
          scroll={{ x: 980, y: 320 }}
        />
      )}
    </Card>
  )
}
