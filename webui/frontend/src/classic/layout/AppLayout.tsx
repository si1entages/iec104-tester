import type { ReactNode } from 'react'

import {
  CameraOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
  MoonOutlined,
  SunOutlined,
} from '@ant-design/icons'
import { Alert, Button, Layout, Menu, Segmented, theme as antdTheme } from 'antd'

import { useStatusQuery } from '../api/queries'
import type { Role } from '../api/types'
import { useT } from '../i18n'
import type { Locale, MessageKey } from '../i18n'
import { useUiStore } from '../store/uiStore'
import type { PageKey } from '../store/uiStore'

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

interface Props {
  children: ReactNode
}

export function AppLayout({ children }: Props) {
  const t = useT()
  const page = useUiStore((s) => s.page)
  const setPage = useUiStore((s) => s.setPage)
  const schemaWarning = useUiStore((s) => s.schemaWarning)
  const sendBackpressure = useUiStore((s) => s.sendBackpressure)
  const droppedFrames = useUiStore((s) => s.droppedFrames)
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
          <Button
            type="text"
            data-testid="theme-toggle"
            aria-label={t('header.theme.dark')}
            title={t('header.theme.dark')}
            icon={isDark ? <SunOutlined /> : <MoonOutlined />}
            onClick={() => setTheme(isDark ? 'light' : 'dark')}
          />
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
