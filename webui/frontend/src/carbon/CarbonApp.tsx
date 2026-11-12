import { useEffect, useRef } from 'react'

import { Asleep, Sun } from '@carbon/icons-react'
import {
  Button,
  Header,
  HeaderGlobalBar,
  HeaderName,
  InlineNotification,
  SideNav,
  SideNavLink,
  SideNavItems,
} from '@carbon/react'

import { useStatusQuery } from '../api/queries'
import { CarbonAuthGate } from './components/CarbonAuthGate'
import { CarbonErrorBoundary } from './components/CarbonErrorBoundary'
import { useLocale, useT } from '../i18n'
import type { MessageKey } from '../i18n'
import { useUiStore } from '../store/uiStore'
import type { PageKey } from '../store/uiStore'
import { CarbonBridgePage } from './pages/CarbonBridgePage'
import { CarbonCapturePage } from './pages/CarbonCapturePage'
import { CarbonAuditPage } from './pages/CarbonAuditPage'
import { CarbonCommissionPage } from './pages/CarbonCommissionPage'
import { CarbonHistoryPage } from './pages/CarbonHistoryPage'
import { CarbonLogsPage } from './pages/CarbonLogsPage'
import { CarbonMasterPage } from './pages/CarbonMasterPage'
import { CarbonMultiPage } from './pages/CarbonMultiPage'
import { CarbonSlavePage } from './pages/CarbonSlavePage'
import { CarbonStatusPage } from './pages/CarbonStatusPage'
import { CarbonTestCenterPage } from './pages/CarbonTestCenterPage'

const PAGES: { key: PageKey; labelKey: MessageKey }[] = [
  { key: 'master', labelKey: 'menu.master' },
  { key: 'slave', labelKey: 'menu.slave' },
  { key: 'multi', labelKey: 'menu.multi' },
  { key: 'status', labelKey: 'menu.status' },
  { key: 'logs', labelKey: 'menu.logs' },
  { key: 'history', labelKey: 'menu.history' },
  { key: 'bridge', labelKey: 'menu.bridge' },
  { key: 'capture', labelKey: 'menu.capture' },
  { key: 'tests', labelKey: 'menu.tests' },
  { key: 'commission', labelKey: 'menu.commission' },
  { key: 'audit', labelKey: 'menu.audit' },
]

function isPageKey(value: string): value is PageKey {
  return PAGES.some((p) => p.key === value)
}

/** 同步 hash 与 uiStore.page（与 PF 外壳一致；两个套件共享 uiStore，切换后仍停在同一页） */
function useHashPage(): { page: PageKey; go: (page: PageKey) => void } {
  const page = useUiStore((s) => s.page)
  const setPage = useUiStore((s) => s.setPage)
  useEffect(() => {
    const sync = (): void => {
      const raw = window.location.hash.replace(/^#\/?/, '')
      if (isPageKey(raw)) setPage(raw)
    }
    sync()
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [setPage])
  const go = (next: PageKey): void => {
    setPage(next)
    window.location.hash = `#/${next}`
  }
  return { page, go }
}

/** 把 uiStore 的主题同步到 Carbon 的 g10/g100 主题类（挂 <html>，portal 同样生效） */
function useCarbonTheme(): void {
  const theme = useUiStore((s) => s.theme)
  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('cds--g100', theme === 'dark')
    root.classList.toggle('cds--g10', theme !== 'dark')
    return () => {
      root.classList.remove('cds--g100', 'cds--g10')
    }
  }, [theme])
}

export function CarbonApp() {
  const t = useT()
  const locale = useLocale()
  const { page, go } = useHashPage()
  const setLocale = useUiStore((s) => s.setLocale)
  const theme = useUiStore((s) => s.theme)
  const setTheme = useUiStore((s) => s.setTheme)
  const schemaWarning = useUiStore((s) => s.schemaWarning)
  const backpressure = useUiStore((s) => s.sendBackpressure)
  const droppedFrames = useUiStore((s) => s.droppedFrames)
  const availableRoles = useUiStore((s) => s.availableRoles)
  const setActiveRole = useUiStore((s) => s.setActiveRole)
  const { data: status } = useStatusQuery()
  const initialized = useRef(false)

  useCarbonTheme()

  // 与 PF 外壳一致：首次拿到角色后，默认进入对应工作台（无 hash 时）
  useEffect(() => {
    if (!status?.role || initialized.current) return
    initialized.current = true
    if (!window.location.hash)
      go(status.role === 'bridge' ? 'bridge'
        : status.role === 'master' ? 'master' : 'slave')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.role])

  // 单角色部署直接采用唯一角色；合并部署按当前工作台切换 API/WS 前缀（/api ↔ /slave/api）
  useEffect(() => {
    if (availableRoles.length === 1) setActiveRole(availableRoles[0])
    else if (availableRoles.length > 1) {
      if (page === 'slave') setActiveRole('slave')
      else if (page === 'master') setActiveRole('master')
    }
  }, [availableRoles, page, setActiveRole])

  const masthead = (
    <Header aria-label="IEC104 Tester">
      <HeaderName href="#/status" prefix="">
        <span className="app-brand-mark" aria-hidden="true" />
        IEC104 Tester
      </HeaderName>
      <HeaderGlobalBar>
        <Button kind="ghost" size="sm" onClick={() => setLocale(locale === 'zh' ? 'en' : 'zh')}>
          {locale === 'zh' ? 'EN' : '中'} {/* i18n-ignore 语言名按原生显示 */}
        </Button>
        <Button
          kind="ghost"
          size="sm"
          data-testid="theme-toggle"
          hasIconOnly
          renderIcon={theme === 'dark' ? Sun : Asleep}
          iconDescription={t('header.theme.dark')}
          aria-label={t('header.theme.dark')}
          tooltipAlignment="start"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        />
      </HeaderGlobalBar>
    </Header>
  )

  const sidebar = (
    <SideNav aria-label={t('menu.master')} expanded isChildOfHeader={false} className="app-sidenav">
      <SideNavItems>
        {PAGES.filter(({ key }) => {
          if (key === 'bridge') {
            const rs = availableRoles.length > 0 ? availableRoles : status?.role ? [status.role] : []
            return rs.includes('bridge')
          }
          if (key === 'audit' || key === 'commission') {
            // 对点页需要 104 引擎下发命令；bridge 角色无引擎，隐藏入口
            const rs = availableRoles.length > 0 ? availableRoles : status?.role ? [status.role] : []
            return !rs.includes('bridge')
          }
          if (key !== 'master' && key !== 'slave') return true
          const roles = availableRoles.length > 0 ? availableRoles : status?.role ? [status.role] : []
          return roles.includes(key)
        }).map(({ key, labelKey }) => (
          <SideNavLink
            key={key}
            href={`#/${key}`}
            isActive={page === key}
            onClick={(event) => {
              event.preventDefault()
              go(key)
            }}
          >
            {t(labelKey)}
          </SideNavLink>
        ))}
      </SideNavItems>
    </SideNav>
  )

  let content
  if (page === 'status') content = <CarbonStatusPage />
  else if (page === 'master') content = <CarbonMasterPage />
  else if (page === 'slave') content = <CarbonSlavePage />
  else if (page === 'logs') content = <CarbonLogsPage />
  else if (page === 'history') content = <CarbonHistoryPage />
  else if (page === 'capture') content = <CarbonCapturePage />
  else if (page === 'tests') content = <CarbonTestCenterPage />
  else if (page === 'multi') content = <CarbonMultiPage />
  else if (page === 'commission') content = <CarbonCommissionPage />
  else if (page === 'audit') content = <CarbonAuditPage />
  else if (page === 'bridge') content = <CarbonBridgePage />
  else content = null

  const hasBanner = Boolean(schemaWarning) || backpressure || droppedFrames > 0

  return (
    <div className="cds-app-shell">
      {masthead}
      {sidebar}
      <main className="app-main">
        <CarbonAuthGate>
          {hasBanner ? (
            <div style={{ marginBottom: 12 }}>
              {schemaWarning ? (
                <InlineNotification
                  kind="warning"
                  lowContrast
                  hideCloseButton
                  title={t('header.schemaWarning')}
                  subtitle={schemaWarning}
                />
              ) : null}
              {backpressure ? (
                <InlineNotification
                  kind="warning"
                  lowContrast
                  hideCloseButton
                  title={t('header.backpressure')}
                />
              ) : null}
              {droppedFrames > 0 ? (
                <InlineNotification
                  kind="warning"
                  lowContrast
                  hideCloseButton
                  title={t('header.dropped', { n: droppedFrames })}
                  subtitle={t('header.droppedDesc')}
                />
              ) : null}
            </div>
          ) : null}
          <CarbonErrorBoundary resetKey={page}>{content}</CarbonErrorBoundary>
        </CarbonAuthGate>
      </main>
    </div>
  )
}
