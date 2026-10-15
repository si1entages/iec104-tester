import { useEffect, useState } from 'react'

import { ApiOutlined, ClusterOutlined } from '@ant-design/icons'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Descriptions,
  Empty,
  Input,
  InputNumber,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useStatusQuery } from '../../api/queries'

interface ClientRow {
  key: string
  peer: string
  index: number
}

const CLIENT_COLUMNS: TableColumnsType<ClientRow> = [
  { title: '#', dataIndex: 'index', width: 56, align: 'right' },
  { title: '客户端', dataIndex: 'peer', className: 'mono' },
]

/**
 * 子站启动与状态区（T13）。
 *
 * - 绑定地址 / 端口 / 公共地址 + 启动监听、停止
 * - 状态栏：running / tx / rx / 背压丢帧 dropped / schemaVersion / 点位数
 * - 客户端连接列表：连接数 + 各会话（`Status.client_list`）信息
 */
export function SlaveConnectionPanel() {
  const { message } = AntdApp.useApp()
  const statusQuery = useStatusQuery()
  const status = statusQuery.data
  const running = Boolean(status?.running)

  const [host, setHost] = useState('0.0.0.0')
  const [port, setPort] = useState(2404)
  const [addr, setAddr] = useState(1)
  // TLS 传输加密（T20）：最小增量——启用开关 + 证书/私钥/CA 路径三项
  const [tlsEnabled, setTlsEnabled] = useState(false)
  const [tlsCert, setTlsCert] = useState('')
  const [tlsKey, setTlsKey] = useState('')
  const [tlsCa, setTlsCa] = useState('')

  const start = useCommand(api.slave.start)
  const stop = useCommandNoArgs(api.slave.stop)

  useEffect(() => {
    if (!status) return
    // 主站状态里也有 host/port；只在子站会话下回填，避免主站参数串写
    if (status.role !== 'slave') return
    if (typeof status.host === 'string' && status.host) setHost(status.host)
    if (typeof status.port === 'number') setPort(status.port)
    if (typeof status.addr === 'number') setAddr(status.addr)
  }, [status?.role, status?.host, status?.port, status?.addr])

  const report = (label: string, result: { ok: boolean; error?: string }): void => {
    if (result.ok) message.success(`${label} 已下发`)
    else message.error(`${label} 失败：${result.error ?? '未知错误'}`)
  }

  const dropped = status?.dropped ?? 0
  const clients = status?.client_list ?? []
  const clientRows: ClientRow[] = clients.map((peer, i) => ({ key: peer, peer, index: i + 1 }))

  return (
    <Card
      size="small"
      title={
        <Space>
          <ApiOutlined />
          <span>子站启动与状态</span>
          <Tag color={running ? 'success' : 'default'}>{running ? '监听中' : '已停止'}</Tag>
        </Space>
      }
      extra={
        <Space>
          <Button
            type="primary"
            loading={start.isPending}
            disabled={running}
            onClick={() =>
              void start
                .mutateAsync({
                  host,
                  port,
                  addr,
                  ...(tlsEnabled
                    ? {
                        tls: {
                          enabled: true,
                          ...(tlsCert ? { certfile: tlsCert } : {}),
                          ...(tlsKey ? { keyfile: tlsKey } : {}),
                          ...(tlsCa ? { cafile: tlsCa } : {}),
                        },
                      }
                    : {}),
                })
                .then((r) => report('启动监听', r))
            }
          >
            启动监听
          </Button>
          <Button
            danger
            loading={stop.isPending}
            disabled={!running}
            onClick={() => void stop.mutateAsync().then((r) => report('停止监听', r))}
          >
            停止
          </Button>
        </Space>
      }
    >
      {statusQuery.isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="读取 /api/status 失败"
          description={String((statusQuery.error as Error)?.message ?? statusQuery.error)}
        />
      ) : null}

      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          prefix="绑定地址"
          style={{ width: 200 }}
          value={host}
          placeholder="0.0.0.0"
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
          prefix="公共地址"
          min={0}
          value={addr}
          onChange={(v) => setAddr(Number(v ?? 1))}
        />
      </Space>

      <Space wrap style={{ marginBottom: 12 }}>
        <span style={{ color: '#8c8c8c' }}>TLS</span>
        <Switch size="small" checked={tlsEnabled} onChange={setTlsEnabled} />
        {tlsEnabled ? (
          <>
            <Input
              prefix="服务端证书"
              placeholder="server.pem"
              style={{ width: 200 }}
              value={tlsCert}
              onChange={(e) => setTlsCert(e.target.value)}
            />
            <Input
              prefix="服务端私钥"
              placeholder="server.key"
              style={{ width: 200 }}
              value={tlsKey}
              onChange={(e) => setTlsKey(e.target.value)}
            />
            <Input
              prefix="CA 证书"
              placeholder="ca.pem（双向认证时）"
              style={{ width: 220 }}
              value={tlsCa}
              onChange={(e) => setTlsCa(e.target.value)}
            />
          </>
        ) : null}
      </Space>

      <Descriptions
        size="small"
        column={5}
        items={[
          { key: 'points', label: '点位数', children: status?.points ?? '-' },
          {
            key: 'clients',
            label: '客户端数',
            children: (
              <span style={{ color: clients.length > 0 ? '#52c41a' : undefined }}>
                {status?.clients ?? clients.length}
              </span>
            ),
          },
          { key: 'tx', label: '发送帧', children: status?.tx ?? '-' },
          { key: 'rx', label: '接收帧', children: status?.rx ?? '-' },
          {
            key: 'dropped',
            label: '背压丢帧',
            children: <span style={{ color: dropped > 0 ? '#faad14' : undefined }}>{dropped}</span>,
          },
          { key: 'schema', label: 'schemaVersion', children: status?.schemaVersion ?? '-' },
          { key: 'sim', label: '模拟', children: status?.simulation ? '开' : '关' },
        ]}
      />

      <Card
        size="small"
        type="inner"
        style={{ marginTop: 12 }}
        title={
          <Space>
            <ClusterOutlined />
            <span>客户端连接</span>
            <Tag color="blue">{clients.length}</Tag>
          </Space>
        }
      >
        {clientRows.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                暂无客户端连接（主站在 2404 端口连上后会出现在这里）
              </Typography.Text>
            }
          />
        ) : (
          <Table<ClientRow>
            rowKey="key"
            size="small"
            columns={CLIENT_COLUMNS}
            dataSource={clientRows}
            pagination={false}
            scroll={{ y: 160 }}
          />
        )}
      </Card>
    </Card>
  )
}
