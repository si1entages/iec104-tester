import { create } from 'zustand'

/**
 * 界面套件（UI kit）选择。
 *
 * 同一地址 `/app/` 内即时切换：根入口按此状态懒加载对应 kit，切换不刷新页面、
 * 不改变 URL，连接与数据缓存（WS / React Query）保持不断。
 *
 * 优先级：`?kit=` 查询参数（便于 e2e/分享定位）→ localStorage 上次选择 → `pf`。
 */
export type KitId = 'pf' | 'classic' | 'carbon'

export const KIT_IDS: KitId[] = ['pf', 'classic', 'carbon']

/** 已实现、可在界面上选择的套件。 */
export const AVAILABLE_KITS: KitId[] = ['pf', 'classic', 'carbon']

const STORAGE_KEY = 'iec104.ui.kit'
const QUERY_KEY = 'kit'

function isKitId(value: string | null): value is KitId {
  return value === 'pf' || value === 'classic' || value === 'carbon'
}

function readQueryKit(): KitId | null {
  try {
    const raw = new URLSearchParams(window.location.search).get(QUERY_KEY)
    return isKitId(raw) ? raw : null
  } catch {
    return null
  }
}

function readStoredKit(): KitId | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return isKitId(raw) ? raw : null
  } catch {
    return null
  }
}

/** 默认套件：Carbon（2026-11-08 起）。旧版默认 pf 的存量偏好按未设置处理。 */
export function resolveInitialKit(): KitId {
  const fromQuery = readQueryKit()
  if (fromQuery) return fromQuery
  const stored = readStoredKit()
  // 旧默认 pf 视为未设置 → 跟随新默认；classic/carbon 是用户主动选择，仍然保留
  if (stored && stored !== 'pf') return stored
  return 'carbon'
}

interface KitState {
  kit: KitId
  setKit: (kit: KitId) => void
}

export const useKitStore = create<KitState>((set) => ({
  kit: resolveInitialKit(),
  setKit: (kit) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, kit)
    } catch {
      // 隐私模式等存储不可用时仅当前会话生效
    }
    set({ kit })
  },
}))
