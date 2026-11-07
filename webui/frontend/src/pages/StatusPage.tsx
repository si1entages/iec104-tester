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
import { useT } from '../i18n'
import type { MessageKey } from '../i18n'

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

function usePointColumns(t: TFn): TableColumnsType<Point> {
  return useMemo(
    () => [
      { title: t('status.col.ioa'), dataIndex: 'ioa', width: 90, sorter: (a, b) => a.ioa - b.ioa },
      { title: t('status.col.type'), dataIndex: 'type', width: 110 },
      { title: t('status.col.name'), dataIndex: 'name', ellipsis: true },
      { title: t('status.col.group'), dataIndex: 'group', width: 80 },
      {
        title: t('status.col.enabled'),
        dataIndex: 'enabled',
        width: 90,
        render: (enabled: boolean) => (
          <Tag color={enabled ? 'green' : 'default'}>
            {enabled ? t('status.enabled') : t('status.disabled')}
          </Tag>
        ),
      },
      {
        title: t('status.col.value'),
        dataIndex: 'value',
        width: 160,
        render: (value: Point['value']) => <span className="mono">{String(value ?? '-')}</span>,
      },
      { title: t('status.col.quality'), dataIndex: 'quality', width: 90 },
    ],
    [t],
  )
}

export function StatusPage() {
  const { message } = AntdApp.useApp()
  const t = useT()
  const pointColumns = usePointColumns(t)
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
    if (result.ok) message.success(t('common.cmdSent'))
    else message.error(result.error ?? t('common.cmdFailed'))
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
      { key: 'host', label: t('status.host'), children: status.host ?? '-' },
      { key: 'port', label: t('status.port'), children: status.port ?? '-' },
      { key: 'addr', label: t('status.addr'), children: status.addr ?? '-' },
      { key: 'state', label: t('status.state'), children: status.state ?? '-' },
      { key: 'window', label: t('status.window'), children: status.window ?? '-' },
      { key: 'vs', label: 'Vs', children: status.vs ?? '-' },
      { key: 'vr', label: 'Vr', children: status.vr ?? '-' },
      { key: 'clients', label: t('status.clients'), children: status.clients ?? '-' },
    ]
  }, [status, t])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {statusQuery.isError ? (
        <Alert
          type="error"
          showIcon
          title={t('status.loadStatusFailed')}
          description={String((statusQuery.error as Error)?.message ?? statusQuery.error)}
        />
      ) : null}

      <Card title={t('status.connectionCard')} size="small">
        <Space wrap>
          <Input
            prefix={t('status.host')}
            style={{ width: 220 }}
            value={host}
            onChange={(e) => setHost(e.target.value)}
          />
          <InputNumber
            prefix={t('status.port')}
            min={0}
            max={65535}
            value={port}
            onChange={(v) => setPort(Number(v ?? 2404))}
          />
          <InputNumber
            prefix={t('status.addr')}
            min={0}
            value={addr}
            onChange={(v) => setAddr(Number(v ?? 1))}
          />
          <Button type="primary" loading={busy} disabled={running} onClick={() => void handleStart()}>
            {role === 'slave' ? t('status.startListen') : t('status.connect')}
          </Button>
          <Button danger loading={busy} disabled={!running} onClick={() => void handleStop()}>
            {role === 'slave' ? t('status.stopListen') : t('status.disconnect')}
          </Button>
        </Space>
        {role === 'master' ? (
          <Space wrap style={{ marginTop: 12 }}>
            <Button size="small" disabled={!running} onClick={() => void gi.mutateAsync({}).then(report)}>
              {t('status.gi')}
            </Button>
            <Button size="small" disabled={!running} onClick={() => void clock.mutateAsync().then(report)}>
              {t('status.clock')}
            </Button>
            <Button size="small" disabled={!running} onClick={() => void testCommand.mutateAsync().then(report)}>
              {t('status.test')}
            </Button>
            <Button size="small" disabled={!running} onClick={() => void reset.mutateAsync().then(report)}>
              {t('status.reset')}
            </Button>
          </Space>
        ) : null}
      </Card>

      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic title={t('status.points')} value={status?.points ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title={t('status.tx')} value={status?.tx ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title={t('status.rx')} value={status?.rx ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('status.dropped')}
              value={status?.dropped ?? 0}
              styles={{ content: { color: (status?.dropped ?? 0) > 0 ? '#faad14' : undefined } }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        title={t('status.runtime')}
        size="small"
        loading={statusQuery.isLoading}
        extra={
          <Button size="small" icon={<DownloadOutlined />} href={DIAGNOSTICS_EXPORT_URL}>
            {t('status.exportDiag')}
          </Button>
        }
      >
        <Descriptions column={4} size="small" items={items} />
      </Card>

      <NetworkSimCard />

      <Card
        title={t('status.pointsTable', { n: pointsQuery.data?.length ?? 0 })}
        size="small"
        extra={
          pointsQuery.isError ? (
            <Tag color="red">
              {t('status.loadFailed', {
                msg: String((pointsQuery.error as Error)?.message ?? ''),
              })}
            </Tag>
          ) : null
        }
      >
        <Table<Point>
          rowKey={(row) => `${row.type}-${row.ioa}`}
          size="small"
          loading={pointsQuery.isLoading}
          columns={pointColumns}
          dataSource={pointsQuery.data ?? []}
          pagination={{
            pageSize: 20,
            showSizeChanger: true,
            showTotal: (total) => t('status.viewPoints', { n: total }),
          }}
          scroll={{ x: 720 }}
        />
      </Card>
    </div>
  )
}
