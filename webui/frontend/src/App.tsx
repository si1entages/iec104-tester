import { Suspense, lazy, useEffect, useRef } from 'react'

import { Spin } from 'antd'

import { useStatusQuery } from './api/queries'
import { useSchemaHandshake } from './hooks/useSchemaHandshake'
import { useHashRoute } from './hooks/useHashRoute'
import { ErrorBoundary } from './layout/ErrorBoundary'
import { AppLayout } from './layout/AppLayout'
import { useUiStore } from './store/uiStore'
import { useWsBridge } from './ws/useWsBridge'

// 路由级 code-split：主站/子站工作台（含 ECharts）与其它页面各自成 chunk，
// 首屏只加载外壳 + 当前页。
const MasterPage = lazy(() => import('./pages/master/MasterPage'))
const SlavePage = lazy(() => import('./pages/slave/SlavePage'))
const MultiPage = lazy(() => import('./pages/multi/MultiPage'))
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
  // 契约版本协商（GET /api/schema）+ 全局 WS（snapshot 先行 / 背压感知）+ hash 路由同步
  useSchemaHandshake()
  useWsBridge()
  useHashRoute()

  const page = useUiStore((s) => s.page)
  const setPage = useUiStore((s) => s.setPage)
  const { data: status } = useStatusQuery()
  const initialized = useRef(false)

  // 角色决定默认页：主站部署直接进主站工作台，子站部署直接进子站工作台
  useEffect(() => {
    if (!status?.role || initialized.current) return
    initialized.current = true
    setPage(status.role === 'master' ? 'master' : 'slave')
  }, [status?.role, setPage])

  return (
    <AppLayout>
      <Suspense fallback={<PageFallback />}>
        {/* 页面级错误边界：单页抛错只影响本页（可重试/切页恢复），外壳不受牵连；
            key=page 保证切页后边界状态重置 */}
        <ErrorBoundary key={page}>
          {page === 'master' ? (
            <MasterPage />
          ) : page === 'slave' ? (
            <SlavePage />
          ) : page === 'multi' ? (
            <MultiPage />
          ) : page === 'logs' ? (
            <LogsPage />
          ) : (
            <StatusPage />
          )}
        </ErrorBoundary>
      </Suspense>
    </AppLayout>
  )
}
