import type { ReactNode } from 'react'

import {
  ApiOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DeploymentUnitOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Alert, Badge, Layout, Menu, Tag, Typography } from 'antd'

import { useStatusQuery } from '../api/queries'
import { useUiStore } from '../store/uiStore'
import type { PageKey } from '../store/uiStore'
import type { WsStatus } from '../ws/client'

const { Header, Sider, Content } = Layout

const MENU_ITEMS = [
  { key: 'master', icon: <ThunderboltOutlined />, label: '主站工作台' },
  { key: 'slave', icon: <DeploymentUnitOutlined />, label: '子站工作台' },
  { key: 'multi', icon: <CloudServerOutlined />, label: '多站' },
  { key: 'status', icon: <DashboardOutlined />, label: '状态总览' },
  { key: 'logs', icon: <FileTextOutlined />, label: '日志' },
]

const WS_BADGE: Record<WsStatus, { status: 'processing' | 'warning' | 'error' | 'default'; text: string }> = {
  idle: { status: 'default', text: 'WS 未连接' },
  connecting: { status: 'warning', text: 'WS 连接中' },
  open: { status: 'processing', text: 'WS 已连接' },
  closed: { status: 'error', text: 'WS 已断开（重连中）' },
}

interface Props {
  children: ReactNode
}

export function AppLayout({ children }: Props) {
  const page = useUiStore((s) => s.page)
  const setPage = useUiStore((s) => s.setPage)
  const wsStatus = useUiStore((s) => s.wsStatus)
  const schemaWarning = useUiStore((s) => s.schemaWarning)
  const sendBackpressure = useUiStore((s) => s.sendBackpressure)
  const droppedFrames = useUiStore((s) => s.droppedFrames)
  const resyncing = useUiStore((s) => s.resyncing)
  const setSendBackpressure = useUiStore((s) => s.setSendBackpressure)

  const { data: status } = useStatusQuery()
  const badge = WS_BADGE[wsStatus]

  return (
    <Layout style={{ minHeight: '100%' }}>
      <Sider width={200} theme="dark">
        <div
          style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            padding: '0 16px',
            color: '#13c2c2',
            fontWeight: 600,
            letterSpacing: 0.5,
          }}
        >
          IEC104 Tester
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[page]}
          items={MENU_ITEMS}
          onClick={({ key }) => setPage(key as PageKey)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            paddingInline: 20,
            height: 48,
            lineHeight: '48px',
          }}
        >
          <Typography.Text strong style={{ fontSize: 14 }}>
            {MENU_ITEMS.find((i) => i.key === page)?.label}
          </Typography.Text>
          {status?.role ? (
            <Tag color={status.role === 'master' ? 'blue' : 'purple'}>{status.role}</Tag>
          ) : null}
          {typeof status?.running === 'boolean' ? (
            <Tag color={status.running ? 'success' : 'default'}>
              {status.running ? 'running' : 'stopped'}
            </Tag>
          ) : null}
          {resyncing ? <Tag color="warning">同步快照中…</Tag> : null}
          <span style={{ flex: 1 }} />
          <Badge status={badge.status} text={<span style={{ color: '#8c8c8c' }}>{badge.text}</span>} />
          <ApiOutlined style={{ color: '#8c8c8c' }} />
        </Header>
        <Content style={{ padding: 16, overflow: 'auto' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {schemaWarning ? (
              <Alert type="warning" showIcon message="契约版本不匹配（降级运行）" description={schemaWarning} />
            ) : null}
            {sendBackpressure ? (
              <Alert
                type="warning"
                showIcon
                closable
                message="WebSocket 发送积压"
                description={sendBackpressure}
                onClose={() => setSendBackpressure(null)}
              />
            ) : null}
            {droppedFrames > 0 ? (
              <Alert
                type="info"
                showIcon
                message={`后端背压丢帧 ${droppedFrames} 条`}
                description="订阅队列（容量 256）写满时后端会丢最旧消息以保证界面跟得上；累积值来自 Status.dropped。"
              />
            ) : null}
            {children}
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
