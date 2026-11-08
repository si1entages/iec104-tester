import { StrictMode, Suspense, lazy, useEffect, useState } from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'

import { KitSplash } from './kit/KitSplash'
import { KitSwitcher } from './kit/KitSwitcher'
import { applyKitCss } from './kit/useKitCss'
import { useKitStore } from './kit/store'
import type { KitId } from './kit/store'
import { useSchemaHandshake } from './hooks/useSchemaHandshake'
import { applyThemeToDom } from './lib/themePreference'
import { useUiStore } from './store/uiStore'
import { useWsBridge } from './ws/useWsBridge'

/**
 * 应用根入口（与 UI 套件无关）。
 *
 * 职责：
 *  - 数据运行时：React Query + WS 桥 + 契约协商，**常驻**，切套件不断连；
 *  - 套件宿主：按 `src/kit/store` 的选择懒加载 PatternFly / 经典版（antd）/ Carbon；
 *  - 样式隔离：同一文档内只保留当前套件的全局样式表（见 `useKitCss`）；
 *  - 主题：深浅色写入 `html[data-theme]`，由各套件自行消费。
 */
const PfRoot = lazy(() => import('./pf/PfRoot'))
const ClassicRoot = lazy(() => import('./classic/ClassicRoot'))
const CarbonRoot = lazy(() => import('./carbon/CarbonRoot'))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

/** 全局运行时：WS 快照/增量 + 契约版本协商（与套件无关，只挂一次） */
function Runtime(): null {
  useWsBridge()
  useSchemaHandshake()
  return null
}

/**
 * 套件宿主：先加载目标套件样式，再挂载组件树。
 * 切换时旧套件保持渲染，直到新样式就绪，避免闪白/无样式。
 */
function KitHost() {
  const kit = useKitStore((s) => s.kit)
  const [mounted, setMounted] = useState<KitId | null>(null)

  useEffect(() => {
    let cancelled = false
    void applyKitCss(kit).then(() => {
      if (cancelled) return
      setMounted(kit)
      document.documentElement.dataset.kit = kit
    })
    return () => {
      cancelled = true
    }
  }, [kit])

  return (
    <>
      <Suspense fallback={<KitSplash />}>
        {mounted === 'pf' ? (
          <PfRoot />
        ) : mounted === 'classic' ? (
          <ClassicRoot />
        ) : mounted === 'carbon' ? (
          <CarbonRoot />
        ) : (
          <KitSplash />
        )}
      </Suspense>
      <KitSwitcher />
    </>
  )
}

// 渲染前同步主题（避免「先浅后深」闪屏）；套件样式由 KitHost 按需加载
applyThemeToDom(useUiStore.getState().theme)

const rootEl = document.getElementById('root')
if (!rootEl) throw new Error('#root 节点缺失') // i18n-ignore 开发期错误

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Runtime />
      <KitHost />
    </QueryClientProvider>
  </StrictMode>,
)
