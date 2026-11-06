import { useEffect, useMemo, useState } from 'react'

import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  InputNumber,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  App as AntdApp,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'

import { api, DIAGNOSTICS_EXPORT_URL } from '../api/endpoints'
import {
  useCommand,
  useCommandNoArgs,
  usePointsQuery,
  useStatusQuery,
} from '../api/queries'
import type { OkResponse, Point } from '../api/types'
import { NetworkSimCard } from '../components/NetworkSimCard'

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
  const { message } = AntdApp.useApp()
  const statusQuery = useStatusQuery()
  const pointsQuery = usePointsQuery()
  const status = statusQuery.data
  const role = status?.role
  const running = Boolean(status?.running)

  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState(2404)
  const [addr, setAddr] = useState(1)

  // 状态里的连接参数一旦变化（启动/断开）就回填表单，避免输入框与实际脱节
  useEffect(() => {
    if (!status) return
    if (typeof status.host === 'string') setHost(status.host)
    if (typeof status.port === 'number') setPort(status.port)
    if (typeof status.addr === 'number') setAddr(status.addr)
  }, [status?.host, status?.port, status?.addr])

  const masterStart = useCommand(api.master.start)
  const masterStop = useCommandNoArgs(api.master.stop)
  const slaveStart = useCommand(api.slave.start)
  const slaveStop = useCommandNoArgs(api.slave.stop)
  const gi = useCommand(api.master.gi)
  const clock = useCommandNoArgs(api.master.clock)
  const testCommand = useCommandNoArgs(api.master.test)
  const reset = useCommandNoArgs(api.master.reset)

  const report = (result: OkResponse): void => {
    if (result.ok) message.success('命令已下发')
    else message.error(result.error ?? '命令失败')
  }

  const handleStart = async (): Promise<void> => {
    const body = { host, port, addr }
    report(role === 'slave' ? await slaveStart.mutateAsync(body) : await masterStart.mutateAsync(body))
  }

  const handleStop = async (): Promise<void> => {
    report(role === 'slave' ? await slaveStop.mutateAsync() : await masterStop.mutateAsync())
  }

  const busy =
    masterStart.isPending ||
    masterStop.isPending ||
    slaveStart.isPending ||
    slaveStop.isPending ||
    gi.isPending ||
    clock.isPending ||
    testCommand.isPending ||
    reset.isPending

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

      <Card title="连接与命令" size="small">
        <Space wrap>
          <Input
            prefix="主机"
            style={{ width: 220 }}
            value={host}
            onChange={(e) => setHost(e.target.value)}
          />
          <InputNumber
            prefix="端口"
            min={0}
            max={65535}
            value={port}
            onChange={(v) => setPort(Number(v ?? 2404))}
          />
          <InputNumber
            prefix="地址"
            min={0}
            value={addr}
            onChange={(v) => setAddr(Number(v ?? 1))}
          />
          <Button type="primary" loading={busy} disabled={running} onClick={() => void handleStart()}>
            {role === 'slave' ? '启动监听' : '连接'}
          </Button>
          <Button danger loading={busy} disabled={!running} onClick={() => void handleStop()}>
            {role === 'slave' ? '停止监听' : '断开'}
          </Button>
        </Space>
        {role === 'master' ? (
          <Space wrap style={{ marginTop: 12 }}>
            <Button size="small" disabled={!running} onClick={() => void gi.mutateAsync({}).then(report)}>
              总召唤
            </Button>
            <Button size="small" disabled={!running} onClick={() => void clock.mutateAsync().then(report)}>
              时钟同步
            </Button>
            <Button size="small" disabled={!running} onClick={() => void testCommand.mutateAsync().then(report)}>
              测试命令
            </Button>
            <Button size="small" disabled={!running} onClick={() => void reset.mutateAsync().then(report)}>
              复位进程
            </Button>
          </Space>
        ) : null}
      </Card>

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

      <Card
        title="运行状态"
        size="small"
        loading={statusQuery.isLoading}
        extra={
          <Button size="small" icon={<DownloadOutlined />} href={DIAGNOSTICS_EXPORT_URL}>
            导出诊断包
          </Button>
        }
      >
        <Descriptions column={4} size="small" items={items} />
      </Card>

      <NetworkSimCard />

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
