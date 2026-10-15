import { useEffect, useState } from 'react'

import { ApiOutlined, LinkOutlined, PauseCircleOutlined } from '@ant-design/icons'
import { Alert, App as AntdApp, Button, Card, Descriptions, Input, InputNumber, Space, Switch, Tag, Tooltip } from 'antd'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useStatusQuery } from '../../api/queries'
import { useUiStore } from '../../store/uiStore'

/** 连接与状态区（T12）：连接参数 + 启停 + 运行指标。 */
export function ConnectionPanel() {
  const { message } = AntdApp.useApp()
  const statusQuery = useStatusQuery()
  const status = statusQuery.data
  const running = Boolean(status?.running)

  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState(2404)
  const [addr, setAddr] = useState(1)
  const [reconnect, setReconnect] = useState(true)
  // 周期总召（T19 补齐旧页能力）：对只在总召时才回遥测的装置，设周期自动召唤（秒，0=关闭）
  const [giInterval, setGiInterval] = useState(0)
  // TLS 传输加密（T20）：最小增量——启用开关 + CA/证书/私钥路径三项
  const [tlsEnabled, setTlsEnabled] = useState(false)
  const [tlsCa, setTlsCa] = useState('')
  const [tlsCert, setTlsCert] = useState('')
  const [tlsKey, setTlsKey] = useState('')

  const start = useCommand(api.master.start)
  const stop = useCommandNoArgs(api.master.stop)

  useEffect(() => {
    if (!status) return
    if (typeof status.host === 'string') setHost(status.host)
    if (typeof status.port === 'number') setPort(status.port)
    if (typeof status.addr === 'number') setAddr(status.addr)
  }, [status?.host, status?.port, status?.addr])

  const report = (result: { ok: boolean; error?: string }): void => {
    if (result.ok) message.success('命令已下发')
    else message.error(result.error ?? '命令失败')
  }

  const dropped = status?.dropped ?? 0

  return (
    <Card
      size="small"
      title={
        <Space>
          <ApiOutlined />
          <span>连接与状态</span>
          <Tag color={running ? 'success' : 'default'}>{running ? '已连接/连接中' : '未连接'}</Tag>
          {status?.state ? <Tag color="blue">{status.state}</Tag> : null}
        </Space>
      }
      extra={
        <Space>
          <span style={{ color: '#8c8c8c' }}>断线重连</span>
          <Switch size="small" checked={reconnect} onChange={setReconnect} />
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
                  reconnect,
                  gi_interval: giInterval,
                  ...(tlsEnabled
                    ? {
                        tls: {
                          enabled: true,
                          ...(tlsCa ? { cafile: tlsCa } : {}),
                          ...(tlsCert ? { certfile: tlsCert } : {}),
                          ...(tlsKey ? { keyfile: tlsKey } : {}),
                        },
                      }
                    : {}),
                })
                .then(report)
            }
          >
            连接
          </Button>
          <Button
            danger
            loading={stop.isPending}
            disabled={!running}
            onClick={() => void stop.mutateAsync().then(report)}
          >
            断开
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
          prefix="主机"
          style={{ width: 200 }}
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
          prefix="公共地址"
          min={0}
          value={addr}
          onChange={(v) => setAddr(Number(v ?? 1))}
        />
        <Tooltip title="对只在总召时才回遥测的装置，可设周期自动召唤（秒，0=关闭）">
          <InputNumber
            prefix="周期总召(秒)"
            min={0}
            value={giInterval}
            onChange={(v) => setGiInterval(Number(v ?? 0))}
          />
        </Tooltip>
      </Space>

      <Space wrap style={{ marginBottom: 12 }}>
        <span style={{ color: '#8c8c8c' }}>TLS</span>
        <Switch size="small" checked={tlsEnabled} onChange={setTlsEnabled} />
        {tlsEnabled ? (
          <>
            <Input
              prefix="CA 证书"
              placeholder="ca.pem"
              style={{ width: 200 }}
              value={tlsCa}
              onChange={(e) => setTlsCa(e.target.value)}
            />
            <Input
              prefix="客户端证书"
              placeholder="client.pem"
              style={{ width: 200 }}
              value={tlsCert}
              onChange={(e) => setTlsCert(e.target.value)}
            />
            <Input
              prefix="客户端私钥"
              placeholder="client.key"
              style={{ width: 200 }}
              value={tlsKey}
              onChange={(e) => setTlsKey(e.target.value)}
            />
          </>
        ) : null}
      </Space>

      <Descriptions
        size="small"
        column={5}
        items={[
          { key: 'points', label: '点位数', children: status?.points ?? '-' },
          { key: 'tx', label: '发送帧', children: status?.tx ?? '-' },
          { key: 'rx', label: '接收帧', children: status?.rx ?? '-' },
          { key: 'window', label: '发送窗口 k', children: status?.window ?? '-' },
          { key: 'vs', label: 'Vs', children: status?.vs ?? '-' },
          { key: 'vr', label: 'Vr', children: status?.vr ?? '-' },
          {
            key: 'dropped',
            label: '背压丢帧',
            children: (
              <span style={{ color: dropped > 0 ? '#faad14' : undefined }}>{dropped}</span>
            ),
          },
          { key: 'clients', label: '客户端数', children: status?.clients ?? '-' },
          {
            key: 'schema',
            label: 'schemaVersion',
            children: status?.schemaVersion ?? '-',
          },
          { key: 'sim', label: '模拟', children: status?.simulation ? '开' : '关' },
        ]}
      />

      <LiveRefreshControl />
    </Card>
  )
}

/** 点值全量刷新节流控制（点值主路径是事件增量，这里是兜底对齐）。 */
function LiveRefreshControl() {
  const liveRefreshMs = useUiStore((s) => s.liveRefreshMs)
  const setLiveRefreshMs = useUiStore((s) => s.setLiveRefreshMs)
  const { data: status } = useStatusQuery()
  const points = status?.points ?? 0
  const heavy = points > 20000

  return (
    <Space wrap style={{ marginTop: 12 }}>
      <PauseCircleOutlined style={{ color: '#8c8c8c' }} />
      <span style={{ color: '#8c8c8c' }}>点值快照对齐周期</span>
      <InputNumber
        min={0}
        max={10000}
        step={500}
        value={liveRefreshMs}
        style={{ width: 130 }}
        onChange={(v) => setLiveRefreshMs(Math.max(0, Number(v ?? 0)))}
        addonAfter="ms"
      />
      <span style={{ color: '#8c8c8c' }}>（0 = 关闭，仅用事件增量）</span>
      {heavy ? (
        <Tag color="warning">
          点表 {points} 行较大，建议调大或关闭全量对齐，仅依赖事件增量
        </Tag>
      ) : null}
      <LinkOutlined style={{ color: '#8c8c8c' }} />
      <span style={{ color: '#8c8c8c' }}>
        值更新优先走 WS 事件增量补丁，本项仅作兜底权威对齐
      </span>
    </Space>
  )
}
