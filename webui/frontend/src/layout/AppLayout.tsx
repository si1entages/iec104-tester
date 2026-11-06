import type { ReactNode } from 'react'

import {
  ApiOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Alert, Badge, Layout, Menu, Switch, Tag, Typography, theme as antdTheme } from 'antd'

import { useStatusQuery } from '../api/queries'
import type { Role } from '../api/types'
import { useUiStore } from '../store/uiStore'
import type { PageKey } from '../store/uiStore'
import type { WsStatus } from '../ws/client'

const { Header, Sider, Content } = Layout

/** 导航项按部署角色过滤：主站会话不出现子站页面入口（反之亦然） */
const MENU_ITEMS: { key: PageKey; icon: ReactNode; label: string; roles: Role[] }[] = [
  { key: 'master', icon: <ThunderboltOutlined />, label: '主站工作台', roles: ['master'] },
  { key: 'slave', icon: <DeploymentUnitOutlined />, label: '子站工作台', roles: ['slave'] },
  { key: 'multi', icon: <CloudServerOutlined />, label: '多站', roles: ['master', 'slave'] },
  { key: 'status', icon: <DashboardOutlined />, label: '状态总览', roles: ['master', 'slave'] },
  { key: 'logs', icon: <FileTextOutlined />, label: '日志', roles: ['master', 'slave'] },
  { key: 'history', icon: <DatabaseOutlined />, label: '历史', roles: ['master', 'slave'] },
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
  const theme = useUiStore((s) => s.theme)
  const setTheme = useUiStore((s) => s.setTheme)
  const isDark = theme === 'dark'

  const { data: status } = useStatusQuery()
  const role = status?.role
  // 角色未知（状态未返回）时不过滤，避免导航闪空；角色就绪后按 role 过滤。
  // 只把 key/icon/label 传给 Menu：roles 是自定义过滤字段，透传会漏成 DOM 属性
  const menuItems = (
    role ? MENU_ITEMS.filter((item) => item.roles.includes(role)) : MENU_ITEMS
  ).map(({ key, icon, label }) => ({ key, icon, label }))
  const badge = WS_BADGE[wsStatus]
  // 颜色一律取自主题 token，禁止硬编码（亮暗一致）
  const { token } = antdTheme.useToken()

  return (
    <Layout style={{ minHeight: '100%' }}>
      <Sider width={200} theme={isDark ? 'dark' : 'light'}>
        <div
          style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            padding: '0 16px',
            color: token.colorPrimary,
            fontWeight: 600,
            letterSpacing: 0.5,
          }}
        >
          IEC104 Tester
        </div>
        <Menu
          theme={isDark ? 'dark' : 'light'}
          mode="inline"
          selectedKeys={[page]}
          items={menuItems}
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
          <Switch
            size="small"
            aria-label="深色模式"
            checked={isDark}
            checkedChildren="深"
            unCheckedChildren="浅"
            onChange={(checked) => setTheme(checked ? 'dark' : 'light')}
          />
          <Badge
            status={badge.status}
            text={<span style={{ color: token.colorTextTertiary }}>{badge.text}</span>}
          />
          <ApiOutlined style={{ color: token.colorTextTertiary }} />
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
