import { useMemo } from 'react'

import { Alert, Card, Col, Descriptions, Row, Statistic, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'

import { usePointsQuery, useStatusQuery } from '../api/queries'
import type { Point } from '../api/types'

const pointColumns: TableColumnsType<Point> = [
  { title: 'IOA', dataIndex: 'ioa', width: 90, sorter: (a, b) => a.ioa - b.ioa },
  { title: '类型', dataIndex: 'type', width: 110 },
  { title: '名称', dataIndex: 'name', ellipsis: true },
  { title: '组', dataIndex: 'group', width: 80 },
  {
    title: '使能',
    dataIndex: 'enabled',
    width: 90,
    render: (enabled: boolean) => (
      <Tag color={enabled ? 'green' : 'default'}>{enabled ? '启用' : '停用'}</Tag>
    ),
  },
  {
    title: '值',
    dataIndex: 'value',
    width: 160,
    render: (value: Point['value']) => <span className="mono">{String(value ?? '-')}</span>,
  },
  { title: '品质', dataIndex: 'quality', width: 90 },
]

export function StatusPage() {
  const statusQuery = useStatusQuery()
  const pointsQuery = usePointsQuery()
  const status = statusQuery.data

  const items = useMemo(() => {
    if (!status) return []
    return [
      { key: 'host', label: '主机', children: status.host ?? '-' },
      { key: 'port', label: '端口', children: status.port ?? '-' },
      { key: 'addr', label: '公共地址', children: status.addr ?? '-' },
      { key: 'state', label: '链路状态', children: status.state ?? '-' },
      { key: 'window', label: '发送窗口', children: status.window ?? '-' },
      { key: 'vs', label: 'Vs', children: status.vs ?? '-' },
      { key: 'vr', label: 'Vr', children: status.vr ?? '-' },
      { key: 'clients', label: '客户端数', children: status.clients ?? '-' },
    ]
  }, [status])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {statusQuery.isError ? (
        <Alert
          type="error"
          showIcon
          message="读取 /api/status 失败"
          description={String((statusQuery.error as Error)?.message ?? statusQuery.error)}
        />
      ) : null}

      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic title="点位数" value={status?.points ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="发送帧" value={status?.tx ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="接收帧" value={status?.rx ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="背压丢弃"
              value={status?.dropped ?? 0}
              valueStyle={{ color: (status?.dropped ?? 0) > 0 ? '#faad14' : undefined }}
            />
          </Card>
        </Col>
      </Row>

      <Card title="运行状态" size="small" loading={statusQuery.isLoading}>
        <Descriptions column={4} size="small" items={items} />
      </Card>

      <Card
        title={`点表（${pointsQuery.data?.length ?? 0}）`}
        size="small"
        extra={
          pointsQuery.isError ? (
            <Tag color="red">加载失败：{String((pointsQuery.error as Error)?.message ?? '')}</Tag>
          ) : null
        }
      >
        <Table<Point>
          rowKey={(row) => `${row.type}-${row.ioa}`}
          size="small"
          loading={pointsQuery.isLoading}
          columns={pointColumns}
          dataSource={pointsQuery.data ?? []}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 点` }}
          scroll={{ x: 720 }}
        />
      </Card>
    </div>
  )
}
