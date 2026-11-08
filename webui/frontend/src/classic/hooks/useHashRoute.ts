import { useEffect } from 'react'

import { useUiStore } from '../store/uiStore'
import type { PageKey } from '../store/uiStore'

const PAGES: PageKey[] = ['status', 'master', 'slave', 'multi', 'logs', 'history', 'capture', 'tests']

/** 解析当前 hash → 页面 key；不认识的 hash 返回 null（保持现状） */
export function pageFromHash(hash: string = window.location.hash): PageKey | null {
  const raw = hash.replace(/^#\/?/, '')
  return (PAGES as string[]).includes(raw) ? (raw as PageKey) : null
}

export function hashForPage(page: PageKey): string {
  return `#/${page}`
}

/**
 * 轻量路由（T14）：uiStore.page 与 location.hash 双向同步。
 *  - 深链/刷新保留当前页（#/logs 直达日志页）
 *  - 浏览器前进/后退、手动改地址可切换页面
 *  - 用 replaceState 写 hash，避免触发多余的 hashchange 事件
 */
export function useHashRoute(): void {
  const page = useUiStore((s) => s.page)
  const setPage = useUiStore((s) => s.setPage)

  // hash → 页面（初始 + 监听浏览器导航）
  useEffect(() => {
    const fromHash = pageFromHash()
    if (fromHash && fromHash !== useUiStore.getState().page) setPage(fromHash)

    const onHash = (): void => {
      const next = pageFromHash()
      if (next && next !== useUiStore.getState().page) setPage(next)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [setPage])

  // 页面 → hash
  useEffect(() => {
    const target = hashForPage(page)
    if (window.location.hash !== target) {
      window.history.replaceState(null, '', target)
    }
  }, [page])
}
