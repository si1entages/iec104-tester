import { useEffect, useState } from 'react'

import { ApiOutlined, LinkOutlined, PauseCircleOutlined } from '@ant-design/icons'
import { Alert, App as AntdApp, Button, Card, Descriptions, Form, Input, InputNumber, Space, Switch, Tag, theme as antdTheme } from 'antd'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import { useUiStore } from '../../store/uiStore'

/** 连接与状态区（T12）：连接参数 + 启停 + 运行指标。 */
export function ConnectionPanel() {
  const t = useT()
  const { message } = AntdApp.useApp()
  const { token } = antdTheme.useToken()
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
  // 冗余双通道（E3）：配置只在启动时生效；运行中禁用编辑，避免“改了没生效”误解
  const [redEnabled, setRedEnabled] = useState(false)
  const [redHost, setRedHost] = useState('127.0.0.1')
  const [redPort, setRedPort] = useState(2405)
  const [redSwitchTimeout, setRedSwitchTimeout] = useState(2)

  const start = useCommand(api.master.start)
  const stop = useCommandNoArgs(api.master.stop)

  useEffect(() => {
    if (!status) return
    if (typeof status.host === 'string') setHost(status.host)
    if (typeof status.port === 'number') setPort(status.port)
    if (typeof status.addr === 'number') setAddr(status.addr)
  }, [status?.host, status?.port, status?.addr])

  // 冗余配置回填（刷新页面/CLI 配置启动后仍能看到真实备用地址）
  useEffect(() => {
    const red = status?.redundancy
    if (!red) return
    setRedEnabled(red.enabled)
    if (red.standby_host) setRedHost(red.standby_host)
    if (red.standby_port) setRedPort(red.standby_port)
    if (red.switch_timeout) setRedSwitchTimeout(red.switch_timeout)
  }, [
    status?.redundancy?.enabled,
    status?.redundancy?.standby_host,
    status?.redundancy?.standby_port,
    status?.redundancy?.switch_timeout,
  ])

  const report = (result: { ok: boolean; error?: string }): void => {
    if (result.ok) message.success(t('common.cmdSent'))
    else message.error(result.error ?? t('common.cmdFailed'))
  }

  const dropped = status?.dropped ?? 0

  return (
    <Card
      size="small"
      title={
        <Space>
          <ApiOutlined />
          <span>{t('conn.title')}</span>
          <Tag color={running ? 'success' : 'default'}>
            {running ? t('conn.connected') : t('conn.disconnected')}
          </Tag>
          {status?.state ? <Tag color="blue">{status.state}</Tag> : null}
        </Space>
      }
      extra={
        <Space>
          <span style={{ color: token.colorTextTertiary }}>{t('conn.reconnect')}</span>
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
                  ...(redEnabled
                    ? {
                        redundancy: {
                          enabled: true,
                          standby_host: redHost,
                          standby_port: redPort,
                          switch_timeout: redSwitchTimeout,
                        },
                      }
                    : {}),
                })
                .then(report)
            }
          >
            {t('conn.connect')}
          </Button>
          <Button
            danger
            loading={stop.isPending}
            disabled={!running}
            onClick={() => void stop.mutateAsync().then(report)}
          >
            {t('conn.disconnect')}
          </Button>
        </Space>
      }
    >
      {statusQuery.isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={t('status.loadStatusFailed')}
          description={String((statusQuery.error as Error)?.message ?? statusQuery.error)}
        />
      ) : null}

      <Form layout="inline" style={{ marginBottom: 12 }} component="div">
        <Form.Item label={t('status.host')}>
          <Input style={{ width: 160 }} value={host} onChange={(e) => setHost(e.target.value)} />
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
        <Form.Item label={t('conn.giInterval')} tooltip={t('conn.giIntervalTip')}>
          <InputNumber
            min={0}
            value={giInterval}
            style={{ width: 110 }}
            onChange={(v) => setGiInterval(Number(v ?? 0))}
          />
        </Form.Item>
      </Form>

      <Space wrap style={{ marginBottom: 12 }}>
        <span style={{ color: token.colorTextTertiary }}>TLS</span>
        <Switch size="small" checked={tlsEnabled} onChange={setTlsEnabled} />
        {tlsEnabled ? (
          <>
            <Input
              prefix={t('conn.tlsCa')}
              placeholder="ca.pem"
              style={{ width: 200 }}
              value={tlsCa}
              onChange={(e) => setTlsCa(e.target.value)}
            />
            <Input
              prefix={t('conn.tlsCert')}
              placeholder="client.pem"
              style={{ width: 200 }}
              value={tlsCert}
              onChange={(e) => setTlsCert(e.target.value)}
            />
            <Input
              prefix={t('conn.tlsKey')}
              placeholder="client.key"
              style={{ width: 200 }}
              value={tlsKey}
              onChange={(e) => setTlsKey(e.target.value)}
            />
          </>
        ) : null}
      </Space>

      <Space wrap style={{ marginBottom: 12 }}>
        <span style={{ color: token.colorTextTertiary }}>{t('conn.redundancy')}</span>
        <Switch
          size="small"
          checked={redEnabled}
          disabled={running}
          onChange={setRedEnabled}
        />
        {redEnabled ? (
          <>
            <Input
              prefix={t('conn.standbyHost')}
              aria-label={t('conn.standbyHost')}
              placeholder="127.0.0.1"
              style={{ width: 180 }}
              value={redHost}
              disabled={running}
              onChange={(e) => setRedHost(e.target.value)}
            />
            <InputNumber
              prefix={t('conn.standbyPort')}
              aria-label={t('conn.standbyPort')}
              min={1}
              max={65535}
              style={{ width: 170 }}
              value={redPort}
              disabled={running}
              onChange={(v) => setRedPort(Number(v ?? 2405))}
            />
            <InputNumber
              prefix={t('conn.switchTimeout')}
              aria-label={t('conn.switchTimeout')}
              min={0.1}
              max={60}
              step={0.5}
              style={{ width: 180 }}
              value={redSwitchTimeout}
              disabled={running}
              onChange={(v) => setRedSwitchTimeout(Number(v ?? 2))}
            />
          </>
        ) : null}
        {status?.redundancy?.enabled ? (
          <Space size={4} wrap>
            <Tag color="purple">
              {t('conn.redActive')}:{' '}
              {status.redundancy.active === 'standby'
                ? t('conn.redStandby')
                : t('conn.redPrimary')}
            </Tag>
            <Tag color={status.redundancy.primary_connected ? 'success' : 'default'}>
              {t('conn.redPrimary')} {status.redundancy.primary_connected
                ? t('conn.redOnline')
                : t('conn.redOffline')}
            </Tag>
            <Tag color={status.redundancy.standby_connected ? 'success' : 'default'}>
              {t('conn.redStandby')} {status.redundancy.standby_connected
                ? t('conn.redOnline')
                : t('conn.redOffline')}
            </Tag>
            <Tag>{t('conn.redFailovers', { n: status.redundancy.failovers })}</Tag>
          </Space>
        ) : null}
      </Space>

      <Descriptions
        size="small"
        column={5}
        items={[
          { key: 'points', label: t('status.points'), children: status?.points ?? '-' },
          { key: 'tx', label: t('status.tx'), children: status?.tx ?? '-' },
          { key: 'rx', label: t('status.rx'), children: status?.rx ?? '-' },
          { key: 'window', label: t('conn.window'), children: status?.window ?? '-' },
          { key: 'vs', label: 'Vs', children: status?.vs ?? '-' },
          { key: 'vr', label: 'Vr', children: status?.vr ?? '-' },
          {
            key: 'dropped',
            label: t('conn.dropped'),
            children: (
              <span style={{ color: dropped > 0 ? '#faad14' : undefined }}>{dropped}</span>
            ),
          },
          // 客户端数是子站属性（主站恒为 "-"），不展示
          {
            key: 'schema',
            label: 'schemaVersion',
            children: status?.schemaVersion ?? '-',
          },
          { key: 'sim', label: t('conn.sim'), children: status?.simulation ? t('conn.on') : t('conn.off') },
        ]}
      />

      <LiveRefreshControl />
    </Card>
  )
}

/** 点值全量刷新节流控制（点值主路径是事件增量，这里是兜底对齐）。 */
function LiveRefreshControl() {
  const t = useT()
  const { token } = antdTheme.useToken()
  const liveRefreshMs = useUiStore((s) => s.liveRefreshMs)
  const setLiveRefreshMs = useUiStore((s) => s.setLiveRefreshMs)
  const { data: status } = useStatusQuery()
  const points = status?.points ?? 0
  const heavy = points > 20000

  return (
    <Space wrap style={{ marginTop: 12 }}>
      <PauseCircleOutlined style={{ color: token.colorTextTertiary }} />
      <span style={{ color: token.colorTextTertiary }}>{t('conn.liveRefresh')}</span>
      <InputNumber
        min={0}
        max={10000}
        step={500}
        value={liveRefreshMs}
        style={{ width: 130 }}
        onChange={(v) => setLiveRefreshMs(Math.max(0, Number(v ?? 0)))}
        addonAfter="ms"
      />
      <span style={{ color: token.colorTextTertiary }}>{t('conn.liveOff')}</span>
      {heavy ? (
        <Tag color="warning">{t('conn.heavy', { n: points })}</Tag>
      ) : null}
      <LinkOutlined style={{ color: token.colorTextTertiary }} />
      <span style={{ color: token.colorTextTertiary }}>{t('conn.liveHint')}</span>
    </Space>
  )
}
