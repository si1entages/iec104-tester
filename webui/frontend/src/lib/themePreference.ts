/**
 * 主题偏好（第二批体验改造 ①）。
 *
 * 解析优先级：localStorage 用户手动选择 → 系统偏好（prefers-color-scheme）→ 深色。
 * 首次打开跟随系统；用户手动切换后由 localStorage 记忆。
 *
 * `resolveInitialTheme` 会在 React 渲染**之前**被 main.tsx 同步调用
 * （并同步设置 `html[data-theme]`），保证无「先浅后深」闪屏。
 */

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'iec104.theme'

function readStored(): ThemeMode | null {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    return v === 'dark' || v === 'light' ? v : null
  } catch {
    return null
  }
}

function systemPrefers(): ThemeMode {
  try {
    return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

/** React 渲染前解析初始主题（localStorage 优先，其次系统偏好，默认深色）。 */
export function resolveInitialTheme(): ThemeMode {
  return readStored() ?? systemPrefers()
}

/** 手动切换主题：持久化到 localStorage（跟随系统不再生效）。 */
export function saveThemePreference(mode: ThemeMode): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    // 隐私模式等存储不可用时静默降级（会话内仍生效）
  }
}

/** 把主题同步到 DOM（body 配色走 global.css 的 `html[data-theme]` 变量）。 */
export function applyThemeToDom(mode: ThemeMode): void {
  document.documentElement.dataset.theme = mode
}
