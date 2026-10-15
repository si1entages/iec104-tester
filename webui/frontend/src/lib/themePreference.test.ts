import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  applyThemeToDom,
  resolveInitialTheme,
  saveThemePreference,
} from './themePreference'

type MatchMediaState = { matches: boolean }

let mediaState: MatchMediaState

function stubMatchMedia(matches: boolean): void {
  mediaState = { matches }
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string): MediaQueryList =>
      ({
        matches: query.includes('light') ? mediaState.matches : !mediaState.matches,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  })
}

describe('themePreference（主题偏好解析）', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('无任何记录时跟随系统偏好（浅色系统 → light）', () => {
    stubMatchMedia(true)
    expect(resolveInitialTheme()).toBe('light')
  })

  it('无任何记录且系统为深色 → dark', () => {
    stubMatchMedia(false)
    expect(resolveInitialTheme()).toBe('dark')
  })

  it('用户手动切换后以 localStorage 记忆为准（不再跟随系统）', () => {
    stubMatchMedia(true) // 系统浅色
    saveThemePreference('dark')
    expect(resolveInitialTheme()).toBe('dark')
  })

  it('localStorage 存了非法值 → 回落系统偏好', () => {
    stubMatchMedia(false)
    window.localStorage.setItem('iec104.theme', 'blue')
    expect(resolveInitialTheme()).toBe('dark')
  })

  it('applyThemeToDom 同步到 html[data-theme]', () => {
    applyThemeToDom('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    applyThemeToDom('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})
