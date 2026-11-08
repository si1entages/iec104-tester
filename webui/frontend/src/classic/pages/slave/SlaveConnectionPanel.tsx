import { useEffect, useState } from 'react'

import { ApiOutlined, ClusterOutlined } from '@ant-design/icons'
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  theme as antdTheme,
} from 'antd'
import type { TableColumnsType } from 'antd'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'

interface ClientRow {
  key: string
  peer: string
  index: number
}

/**
 * 子站启动与状态区（T13）。
 *
 * - 绑定地址 / 端口 / 公共地址 + 启动监听、停止
 * - 状态栏：running / tx / rx / 背压丢帧 dropped / schemaVersion / 点位数
 * - 客户端连接列表：连接数 + 各会话（`Status.client_list`）信息
 */
export function SlaveConnectionPanel() {
  const t = useT()
  const { message } = AntdApp.useApp()
  const { token } = antdTheme.useToken()
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
    if (result.ok) message.success(t('cmd.done', { label }))
    else message.error(t('cmd.failed', { label, error: result.error ?? t('cmd.unknown') }))
  }

  const dropped = status?.dropped ?? 0
  const clients = status?.client_list ?? []
  const clientRows: ClientRow[] = clients.map((peer, i) => ({ key: peer, peer, index: i + 1 }))
  const clientColumns: TableColumnsType<ClientRow> = [
    { title: '#', dataIndex: 'index', width: 56, align: 'right' },
    { title: t('scp.col.client'), dataIndex: 'peer', className: 'mono' },
  ]

  return (
    <Card
      size="small"
      title={
        <Space>
          <ApiOutlined />
          <span>{t('scp.title')}</span>
          <Tag color={running ? 'success' : 'default'}>
            {running ? t('scp.listening') : t('scp.stopped')}
          </Tag>
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
                .then((r) => report(t('scp.start'), r))
            }
          >
            {t('scp.start')}
          </Button>
          <Button
            danger
            loading={stop.isPending}
            disabled={!running}
            onClick={() => void stop.mutateAsync().then((r) => report(t('scp.stop'), r))}
          >
            {t('scp.stop')}
          </Button>
        </Space>
      }
    >
      {statusQuery.isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          title={t('status.loadStatusFailed')}
          description={String((statusQuery.error as Error)?.message ?? statusQuery.error)}
        />
      ) : null}

      <Form layout="inline" style={{ marginBottom: 12 }} component="div">
        <Form.Item label={t('scp.bind')}>
          <Input
            style={{ width: 160 }}
            value={host}
            placeholder="0.0.0.0"
            onChange={(e) => setHost(e.target.value)}
          />
        </Form.Item>
        <Form.Item label={t('status.port')}>
          <InputNumber
            min={0}
            max={65535}
            value={port}
            style={{ width: 110 }}
            onChange={(v) => setPort(Number(v ?? 2404))}
          />
        </Form.Item>
        <Form.Item label={t('status.addr')}>
          <InputNumber
            min={0}
            value={addr}
            style={{ width: 110 }}
            onChange={(v) => setAddr(Number(v ?? 1))}
          />
        </Form.Item>
      </Form>

      <Space wrap style={{ marginBottom: 12 }}>
        <span style={{ color: token.colorTextTertiary }}>TLS</span>
        <Switch size="small" checked={tlsEnabled} onChange={setTlsEnabled} />
        {tlsEnabled ? (
          <>
            <Input
              prefix={t('scp.tlsCert')}
              placeholder="server.pem"
              style={{ width: 200 }}
              value={tlsCert}
              onChange={(e) => setTlsCert(e.target.value)}
            />
            <Input
              prefix={t('scp.tlsKey')}
              placeholder="server.key"
              style={{ width: 200 }}
              value={tlsKey}
              onChange={(e) => setTlsKey(e.target.value)}
            />
            <Input
              prefix={t('conn.tlsCa')}
              placeholder={t('scp.tlsCaPlaceholder')}
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
          { key: 'points', label: t('status.points'), children: status?.points ?? '-' },
          {
            key: 'clients',
            label: t('status.clients'),
            children: (
              <span style={{ color: clients.length > 0 ? '#52c41a' : undefined }}>
                {status?.clients ?? clients.length}
              </span>
            ),
          },
          { key: 'tx', label: t('status.tx'), children: status?.tx ?? '-' },
          { key: 'rx', label: t('status.rx'), children: status?.rx ?? '-' },
          {
            key: 'dropped',
            label: t('conn.dropped'),
            children: <span style={{ color: dropped > 0 ? '#faad14' : undefined }}>{dropped}</span>,
          },
          { key: 'schema', label: 'schemaVersion', children: status?.schemaVersion ?? '-' },
          { key: 'sim', label: t('conn.sim'), children: status?.simulation ? t('conn.on') : t('conn.off') },
        ]}
      />

      <Card
        size="small"
        type="inner"
        style={{ marginTop: 12 }}
        title={
          <Space>
            <ClusterOutlined />
            <span>{t('scp.clientList')}</span>
            <Tag color="blue">{clients.length}</Tag>
          </Space>
        }
      >
        {clientRows.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t('scp.noClients')}
              </Typography.Text>
            }
          />
        ) : (
          <Table<ClientRow>
            rowKey="key"
            size="small"
            columns={clientColumns}
            dataSource={clientRows}
            pagination={false}
            scroll={{ y: 160 }}
          />
        )}
      </Card>
    </Card>
  )
}
