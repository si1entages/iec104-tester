import { useEffect, useRef } from 'react'

import {
  Alert,
  Button,
  Flex,
  Masthead,
  MastheadBrand,
  MastheadContent,
  MastheadMain,
  Nav,
  NavItem,
  NavList,
  Page,
  PageSection,
  PageSidebar,
  PageSidebarBody,
  Title,
} from '@patternfly/react-core'
import { MoonIcon, SunIcon } from '@patternfly/react-icons'

import { useStatusQuery } from '../api/queries'
import { PfAuthGate } from './components/PfAuthGate'
import { PfErrorBoundary } from './components/PfErrorBoundary'
import { useLocale, useT } from '../i18n'
import type { MessageKey } from '../i18n'
import { useUiStore } from '../store/uiStore'
import type { PageKey } from '../store/uiStore'
import { PfBridgePage } from './pages/PfBridgePage'
import { PfCapturePage } from './pages/PfCapturePage'
import { PfHistoryPage } from './pages/PfHistoryPage'
import { PfLogsPage } from './pages/PfLogsPage'
import { PfMasterPage } from './pages/PfMasterPage'
import { PfMultiPage } from './pages/PfMultiPage'
import { PfPlaceholder } from './pages/PfPlaceholder'
import { PfSlavePage } from './pages/PfSlavePage'
import { PfStatusPage } from './pages/PfStatusPage'
import { PfTestCenterPage } from './pages/PfTestCenterPage'

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
]

function isPageKey(value: string): value is PageKey {
  return PAGES.some((p) => p.key === value)
}

/** 同步 hash 与 uiStore.page（与 antd 外壳一致，但两者是独立文档，互不影响） */
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

/** 把 uiStore 的主题同步到 PF 的 `pf-v6-theme-dark` 类（切走时移除，不污染其它套件） */
function usePfTheme(): void {
  const theme = useUiStore((s) => s.theme)
  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('pf-v6-theme-dark', theme === 'dark')
    // `data-theme` / color-scheme 由根入口统一维护（见 src/main.tsx）
    return () => root.classList.remove('pf-v6-theme-dark')
  }, [theme])
}

export function PfApp() {
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

  usePfTheme()

  // 与旧外壳一致：首次拿到角色后，默认进入对应工作台（无 hash 时）
  useEffect(() => {
    if (!status?.role || initialized.current) return
    initialized.current = true
    if (!window.location.hash)
      go(status.role === 'bridge' ? 'bridge'
        : status.role === 'master' ? 'master' : 'slave')
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
    <Masthead>
      <MastheadMain>
        <MastheadBrand>
          <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
            <span
              style={{
                width: 26,
                height: 26,
                borderRadius: 6,
                background: 'var(--pf-t--global--color--brand--default)',
                display: 'inline-block',
              }}
            />
            <Title headingLevel="h1" size="lg">
              IEC104 Tester
            </Title>
          </Flex>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Flex
          alignItems={{ default: 'alignItemsCenter' }}
          gap={{ default: 'gapMd' }}
          style={{ width: '100%', justifyContent: 'flex-end' }}
        >
          <Button
            variant="plain"
            data-testid="theme-toggle"
            aria-label={t('header.theme.dark')}
            icon={theme === 'dark' ? <SunIcon /> : <MoonIcon />}
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          />
          <Button variant="plain" onClick={() => setLocale(locale === 'zh' ? 'en' : 'zh')}>
            {locale === 'zh' ? 'EN' : '中'} {/* i18n-ignore 语言名按原生显示 */}
          </Button>
        </Flex>
      </MastheadContent>
    </Masthead>
  )

  const sidebar = (
    <PageSidebar isSidebarOpen id="pf-sidebar">
      <PageSidebarBody>
        <Nav aria-label={t('menu.master')}>
          <NavList>
            {PAGES.filter(({ key }) => {
              if (key === 'bridge') {
                const rs = availableRoles.length > 0 ? availableRoles : status?.role ? [status.role] : []
                return rs.includes('bridge')
              }
              if (key !== 'master' && key !== 'slave') return true
              const roles = availableRoles.length > 0 ? availableRoles : status?.role ? [status.role] : []
              return roles.includes(key)
            }).map(({ key, labelKey }) => (
              <NavItem
                key={key}
                itemId={key}
                isActive={page === key}
                to={`#/${key}`}
                onClick={(event) => {
                  event.preventDefault()
                  go(key)
                }}
              >
                {t(labelKey)}
              </NavItem>
            ))}
          </NavList>
        </Nav>
      </PageSidebarBody>
    </PageSidebar>
  )

  let content
  if (page === 'status') content = <PfStatusPage />
  else if (page === 'master') content = <PfMasterPage />
  else if (page === 'slave') content = <PfSlavePage />
  else if (page === 'logs') content = <PfLogsPage />
  else if (page === 'history') content = <PfHistoryPage />
  else if (page === 'capture') content = <PfCapturePage />
  else if (page === 'tests') content = <PfTestCenterPage />
  else if (page === 'multi') content = <PfMultiPage />
  else if (page === 'bridge') content = <PfBridgePage />
  else content = <PfPlaceholder />

  const hasBanner = Boolean(schemaWarning) || backpressure || droppedFrames > 0

  return (
    <PfAuthGate>
      <Page masthead={masthead} sidebar={sidebar}>
        {hasBanner ? (
          <PageSection variant="secondary" style={{ paddingBlock: 8 }}>
            {schemaWarning ? (
              <Alert isInline variant="warning" title={t('header.schemaWarning')}>
                {schemaWarning}
              </Alert>
            ) : null}
            {backpressure ? <Alert isInline variant="warning" title={t('header.backpressure')} /> : null}
            {droppedFrames > 0 ? (
              <Alert isInline variant="warning" title={t('header.dropped', { n: droppedFrames })}>
                {t('header.droppedDesc')}
              </Alert>
            ) : null}
          </PageSection>
        ) : null}
        <PfErrorBoundary resetKey={page}>{content}</PfErrorBoundary>
      </Page>
    </PfAuthGate>
  )
}
