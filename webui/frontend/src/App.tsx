import { Suspense, lazy, useEffect, useRef } from 'react'

import { Spin } from 'antd'

import { useStatusQuery } from './api/queries'
import { AppLayout } from './layout/AppLayout'
import { useSchemaHandshake } from './hooks/useSchemaHandshake'
import { useUiStore } from './store/uiStore'
import { useWsBridge } from './ws/useWsBridge'

// 路由级 code-split：主站工作台（含 ECharts）与其它页面各自成 chunk，
// 首屏只加载外壳 + 当前页。
const MasterPage = lazy(() => import('./pages/master/MasterPage'))
const StatusPage = lazy(() => import('./pages/StatusPage').then((m) => ({ default: m.StatusPage })))
const LogsPage = lazy(() => import('./pages/LogsPage').then((m) => ({ default: m.LogsPage })))

function PageFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
      <Spin tip="加载页面…" size="large">
        <div style={{ width: 200, height: 60 }} />
      </Spin>
    </div>
  )
}

export default function App() {
  // 契约版本协商（GET /api/schema）+ 全局 WS（snapshot 先行 / 背压感知）
  useSchemaHandshake()
  useWsBridge()

  const page = useUiStore((s) => s.page)
  const setPage = useUiStore((s) => s.setPage)
  const { data: status } = useStatusQuery()
  const initialized = useRef(false)

  // 角色决定默认页：主站部署直接进工作台，子站部署先看状态总览
  useEffect(() => {
    if (!status?.role || initialized.current) return
    initialized.current = true
    setPage(status.role === 'master' ? 'master' : 'status')
  }, [status?.role, setPage])

  return (
    <AppLayout>
      <Suspense fallback={<PageFallback />}>
        {page === 'master' ? <MasterPage /> : page === 'logs' ? <LogsPage /> : <StatusPage />}
      </Suspense>
    </AppLayout>
  )
}
