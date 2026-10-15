import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { useUiStore } from '../store/uiStore'
import { hashForPage, pageFromHash, useHashRoute } from './useHashRoute'

describe('useHashRoute（轻量路由）', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/')
    useUiStore.setState({ page: 'status' })
  })

  it('pageFromHash：识别合法 key、拒绝非法 hash', () => {
    expect(pageFromHash('#/logs')).toBe('logs')
    expect(pageFromHash('#multi')).toBe('multi')
    expect(pageFromHash('#/nope')).toBeNull()
    expect(pageFromHash('')).toBeNull()
  })

  it('hashForPage 生成可往返的 hash', () => {
    expect(pageFromHash(hashForPage('master'))).toBe('master')
  })

  it('初始 hash 决定页面（深链直达）', () => {
    window.history.replaceState(null, '', '#/logs')
    renderHook(() => useHashRoute())
    expect(useUiStore.getState().page).toBe('logs')
  })

  it('hashchange（浏览器前进/后退）切换页面', () => {
    renderHook(() => useHashRoute())
    act(() => {
      window.history.replaceState(null, '', '#/multi')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(useUiStore.getState().page).toBe('multi')
  })

  it('页面切换写回 hash（replaceState，不触发循环）', () => {
    renderHook(() => useHashRoute())
    act(() => {
      useUiStore.getState().setPage('slave')
    })
    expect(window.location.hash).toBe('#/slave')
    expect(useUiStore.getState().page).toBe('slave')
  })
})
