import type { ReactNode } from 'react'

import { DashboardOutlined, FileTextOutlined, ApiOutlined } from '@ant-design/icons'
import { Badge, Layout, Menu, Tag, Typography } from 'antd'

import { useStatusQuery } from '../api/queries'
import { useUiStore } from '../store/uiStore'
import type { PageKey } from '../store/uiStore'

const { Header, Sider, Content } = Layout

const MENU_ITEMS = [
  { key: 'status', icon: <DashboardOutlined />, label: '状态总览' },
  { key: 'logs', icon: <FileTextOutlined />, label: '日志' },
]

interface Props {
  children: ReactNode
}

export function AppLayout({ children }: Props) {
  const page = useUiStore((s) => s.page)
  const setPage = useUiStore((s) => s.setPage)
  const wsConnected = useUiStore((s) => s.wsConnected)
  const { data: status } = useStatusQuery()

  const role = status?.role
  const running = status?.running

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
          {role ? <Tag color={role === 'master' ? 'blue' : 'purple'}>{role}</Tag> : null}
          {typeof running === 'boolean' ? (
            <Tag color={running ? 'success' : 'default'}>{running ? 'running' : 'stopped'}</Tag>
          ) : null}
          <span style={{ flex: 1 }} />
          <Badge
            status={wsConnected ? 'processing' : 'error'}
            text={<span style={{ color: '#8c8c8c' }}>{wsConnected ? 'WS 已连接' : 'WS 断开'}</span>}
          />
          <ApiOutlined style={{ color: '#8c8c8c' }} />
        </Header>
        <Content style={{ padding: 16, overflow: 'auto' }}>{children}</Content>
      </Layout>
    </Layout>
  )
}
