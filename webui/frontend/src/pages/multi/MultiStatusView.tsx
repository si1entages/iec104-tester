import { Alert, Button, Card, Col, Empty, Popconfirm, Row, Space, Statistic, Table, Tag, Tooltip, theme as antdTheme } from 'antd'
import type { TableColumnsType } from 'antd'

import type { MultiStatusResponse, MultiSummaryResponse, StationStatus } from '../../api/types'
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

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

const columns = (
  t: TFn,
  onDisable?: (id: string) => void,
  busy?: boolean,
): TableColumnsType<StationStatus> => [
  { title: t('msv.col.id'), dataIndex: 'station_id', width: 150, className: 'mono' },
  { title: t('msv.col.name'), dataIndex: 'station_name', width: 160, ellipsis: true },
  { title: t('msv.col.port'), dataIndex: 'port', width: 80, className: 'mono' },
  { title: t('msv.col.addr'), dataIndex: 'common_addr', width: 90, className: 'mono' },
  {
    title: t('msv.col.running'),
    dataIndex: 'running',
    width: 80,
    render: (running: boolean) => (
      <Tag color={running ? 'success' : 'default'}>
        {running ? t('msv.rowRunning') : t('msv.rowStopped')}
      </Tag>
    ),
  },
  {
    title: t('msv.col.clients'),
    dataIndex: 'client_count',
    width: 80,
    render: (n: number) => <span style={{ color: n > 0 ? '#52c41a' : undefined }}>{n}</span>,
  },
  {
    title: t('msv.col.points'),
    width: 170,
    className: 'mono',
    render: (_v, row) => `${row.yx_count}/${row.yc_count}/${row.yk_count}/${row.ym_count}`,
  },
  {
    title: t('msv.col.sim'),
    dataIndex: 'simulation_active',
    width: 80,
    render: (on: boolean) =>
      on ? <Tag color="green">{t('msv.simOn')}</Tag> : <Tag>{t('msv.simOff')}</Tag>,
  },
  {
    title: t('msv.col.actions'),
    width: 130,
    render: (_v, row) =>
      onDisable ? (
        <Popconfirm
          title={t('msv.disableTitle', { id: row.station_id })}
          description={t('msv.disableDesc')}
          okText={t('msv.confirmDisable')}
          cancelText={t('pcd.cancel')}
          onConfirm={() => onDisable(row.station_id)}
        >
          <Button size="small" danger type="text" disabled={busy}>
            {t('msv.disableBtn')}
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
  const t = useT()
  const { token } = antdTheme.useToken()
  const stations = status?.stations ?? []
  const running = Boolean(summary?.running ?? status?.running)

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>{t('msv.title')}</span>
          <Tag color={running ? 'success' : 'default'}>
            {running ? t('msv.running') : t('msv.notRunning')}
          </Tag>
        </Space>
      }
    >
      {isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={t('msv.error')}
          description={String((error as Error)?.message ?? error)}
        />
      ) : null}

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={4}>
          <Statistic title={t('msv.stationCount')} value={summary?.station_count ?? stations.length} />
        </Col>
        <Col span={4}>
          <Statistic
            title={t('msv.totalClients')}
            value={summary?.total_clients ?? 0}
            valueStyle={{ color: (summary?.total_clients ?? 0) > 0 ? token.colorSuccess : undefined }}
          />
        </Col>
        <Col span={4}>
          <Statistic title={t('msv.uptime')} value={formatUptime(summary?.uptime ?? 0)} />
        </Col>
        <Col span={4}>
          <Tooltip title={t('msv.pointsTotalTip')}>
            <Statistic
              title={t('msv.pointsTotal')}
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
            title={t('msv.online')}
            value={stations.filter((s) => s.running).length}
            suffix={`/ ${stations.length}`}
          />
        </Col>
      </Row>

      {stations.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('msv.empty')}
        />
      ) : (
        <Table<StationStatus>
          rowKey="station_id"
          size="small"
          loading={loading}
          columns={columns(t, onDisableStation, busy)}
          dataSource={stations}
          pagination={false}
          scroll={{ x: 980, y: 320 }}
        />
      )}
    </Card>
  )
}
