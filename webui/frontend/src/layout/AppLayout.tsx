import type { ReactNode } from 'react'

import {
  ApiOutlined,
  CameraOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Alert, Badge, Layout, Menu, Segmented, Switch, Tag, Typography, theme as antdTheme } from 'antd'

import { useStatusQuery } from '../api/queries'
import type { Role } from '../api/types'
import { useT } from '../i18n'
import type { Locale, MessageKey } from '../i18n'
import { useUiStore } from '../store/uiStore'
import type { PageKey } from '../store/uiStore'
import type { WsStatus } from '../ws/client'

const { Header, Sider, Content } = Layout

/** 导航项按部署角色过滤：主站会话不出现子站页面入口（反之亦然） */
const MENU_ITEMS: { key: PageKey; icon: ReactNode; labelKey: MessageKey; roles: Role[] }[] = [
  { key: 'master', icon: <ThunderboltOutlined />, labelKey: 'menu.master', roles: ['master'] },
  { key: 'slave', icon: <DeploymentUnitOutlined />, labelKey: 'menu.slave', roles: ['slave'] },
  { key: 'multi', icon: <CloudServerOutlined />, labelKey: 'menu.multi', roles: ['master', 'slave'] },
  { key: 'status', icon: <DashboardOutlined />, labelKey: 'menu.status', roles: ['master', 'slave'] },
  { key: 'logs', icon: <FileTextOutlined />, labelKey: 'menu.logs', roles: ['master', 'slave'] },
  { key: 'history', icon: <DatabaseOutlined />, labelKey: 'menu.history', roles: ['master', 'slave'] },
  { key: 'capture', icon: <CameraOutlined />, labelKey: 'menu.capture', roles: ['master', 'slave'] },
  { key: 'tests', icon: <ExperimentOutlined />, labelKey: 'menu.tests', roles: ['master', 'slave'] },
]

const WS_BADGE: Record<WsStatus, { status: 'processing' | 'warning' | 'error' | 'default'; textKey: MessageKey }> = {
  idle: { status: 'default', textKey: 'header.ws.idle' },
  connecting: { status: 'warning', textKey: 'header.ws.connecting' },
  open: { status: 'processing', textKey: 'header.ws.open' },
  closed: { status: 'error', textKey: 'header.ws.closed' },
}

interface Props {
  children: ReactNode
}

export function AppLayout({ children }: Props) {
  const t = useT()
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
  const locale = useUiStore((s) => s.locale)
  const setLocale = useUiStore((s) => s.setLocale)
  const isDark = theme === 'dark'

  const { data: status } = useStatusQuery()
  const role = status?.role
  // 角色未知（状态未返回）时不过滤，避免导航闪空；角色就绪后按 role 过滤。
  // 只把 key/icon/label 传给 Menu：roles 是自定义过滤字段，透传会漏成 DOM 属性
  const menuItems = (
    role ? MENU_ITEMS.filter((item) => item.roles.includes(role)) : MENU_ITEMS
  ).map(({ key, icon, labelKey }) => ({ key, icon, label: t(labelKey) }))
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
            {t(MENU_ITEMS.find((i) => i.key === page)?.labelKey ?? 'menu.status')}
          </Typography.Text>
          {status?.role ? (
            <Tag color={status.role === 'master' ? 'blue' : 'purple'}>{status.role}</Tag>
          ) : null}
          {typeof status?.running === 'boolean' ? (
            <Tag color={status.running ? 'success' : 'default'}>
              {status.running ? 'running' : 'stopped'}
            </Tag>
          ) : null}
          {resyncing ? <Tag color="warning">{t('header.syncing')}</Tag> : null}
          <span style={{ flex: 1 }} />
          <Segmented
            size="small"
            aria-label={t('header.lang')}
            value={locale}
            onChange={(value) => setLocale(value as Locale)}
            options={[
              { label: '中', value: 'zh' }, // i18n-ignore 语言名按原生显示
              { label: 'EN', value: 'en' },
            ]}
          />
          <Switch
            size="small"
            aria-label={t('header.theme.dark')}
            checked={isDark}
            checkedChildren={t('header.theme.on')}
            unCheckedChildren={t('header.theme.off')}
            onChange={(checked) => setTheme(checked ? 'dark' : 'light')}
          />
          <Badge
            status={badge.status}
            text={<span style={{ color: token.colorTextTertiary }}>{t(badge.textKey)}</span>}
          />
          <ApiOutlined style={{ color: token.colorTextTertiary }} />
        </Header>
        <Content style={{ padding: 16, overflow: 'auto' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {schemaWarning ? (
              <Alert type="warning" showIcon title={t('header.schemaWarning')} description={schemaWarning} />
            ) : null}
            {sendBackpressure ? (
              <Alert
                type="warning"
                showIcon
                closable
                title={t('header.backpressure')}
                description={sendBackpressure}
                onClose={() => setSendBackpressure(null)}
              />
            ) : null}
            {droppedFrames > 0 ? (
              <Alert
                type="info"
                showIcon
                title={t('header.dropped', { n: droppedFrames })}
                description={t('header.droppedDesc')}
              />
            ) : null}
            {children}
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
