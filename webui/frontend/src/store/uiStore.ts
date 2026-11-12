import { create } from 'zustand'

import { setActiveRole as setApiActiveRole } from '../api/client'
import type { Point, Role } from '../api/types'
import type { Locale } from '../i18n'
import { applyThemeToDom, resolveInitialTheme, saveThemePreference } from '../lib/themePreference'
import type { ThemeMode } from '../lib/themePreference'
import type { WsStatus } from '../ws/client'

export type PageKey = 'status' | 'master' | 'slave' | 'multi' | 'logs' | 'history' | 'capture' | 'tests' | 'commission' | 'audit' | 'bridge'

const LOCALE_KEY = 'iec104_locale'

/** 语言偏好：默认中文；仅识别 en（其它值回落 zh） */
function resolveInitialLocale(): Locale {
  try {
    return localStorage.getItem(LOCALE_KEY) === 'en' ? 'en' : 'zh'
  } catch {
    return 'zh'
  }
}

/**
 * 纯 UI 状态（T11）。
 * 约束：**不在 Zustand 里缓存服务端数据**——状态 / 点表 / 日志全部由 React Query 持有，
 * 本 store 只保存「界面上打开哪个页、连接指示、告警文案」这类本地状态。
 */
interface UiState {
  page: PageKey
  setPage: (page: PageKey) => void

  /** 当前工作台角色（决定 API/WS 走 /api 还是 /slave/api） */
  activeRole: Role
  setActiveRole: (role: Role) => void

  /** 可用角色（来自 GET /api/schema；单角色模式只有一个） */
  availableRoles: Role[]
  setAvailableRoles: (roles: Role[]) => void

  /** 主题（深/浅）：初始值在模块加载时同步解析（渲染前，无闪屏）；切换即持久化 */
  theme: ThemeMode
  setTheme: (mode: ThemeMode) => void

  /** 界面语言（C3 i18n）：默认 zh，切换即持久化 */
  locale: Locale
  setLocale: (locale: Locale) => void

  /** WS 连接状态（头部指示 + 日志页提示） */
  wsStatus: WsStatus
  setWsStatus: (status: WsStatus) => void

  /** 契约版本不匹配时的降级告警（null = 正常） */
  schemaWarning: string | null
  setSchemaWarning: (warning: string | null) => void

  /** 后端背压丢弃累计（来自 Status.dropped） */
  droppedFrames: number
  setDroppedFrames: (dropped: number) => void

  /** 发送侧积压提示（WS bufferedAmount 超阈值） */
  sendBackpressure: string | null
  setSendBackpressure: (notice: string | null) => void

  /** 等待重连后的首个快照（此期间应用不接收增量） */
  resyncing: boolean
  setResyncing: (resyncing: boolean) => void

  /**
   * 点值全量刷新周期（ms，0 = 关闭）。
   * 值更新的主路径是 WS `event` 增量补丁；本项是兜底/权威对齐，
   * 大点表下应调大或关闭（组件会给出提示）。
   */
  liveRefreshMs: number
  setLiveRefreshMs: (ms: number) => void

  /**
   * 主站工作台的点表选中行与趋势 watch 列表（T70 反馈）：
   * 放在共享 store 里，切换页面/套件后回来不丢，趋势曲线无需重新加入。
   * Point 对象只取 type/ioa/name 等标识字段，值仍以点表缓存为准。
   */
  selectedPoint: Point | null
  setSelectedPoint: (point: Point | null) => void

  trendWatched: Point[]
  setTrendWatched: (points: Point[]) => void

  /** 历史曲线快照（T87）：ECharts getDataURL → 报告导出时嵌入（最多 4 张） */
  chartSnapshots: string[]
  setChartSnapshots: (images: string[]) => void
}

export const useUiStore = create<UiState>((set) => ({
  page: 'status',
  setPage: (page) => set({ page }),

  activeRole: 'master',
  setActiveRole: (activeRole) => {
    setApiActiveRole(activeRole)
    set({ activeRole })
  },

  availableRoles: [],
  setAvailableRoles: (availableRoles) => set({ availableRoles }),

  // 模块加载即解析（跟随系统/localStorage），保证 ConfigProvider 首帧就用对算法
  theme: resolveInitialTheme(),
  setTheme: (mode) => {
    applyThemeToDom(mode)
    saveThemePreference(mode)
    set({ theme: mode })
  },

  locale: resolveInitialLocale(),
  setLocale: (locale) => {
    try {
      localStorage.setItem(LOCALE_KEY, locale)
    } catch {
      // 存储不可用时仅当前会话生效
    }
    set({ locale })
  },

  wsStatus: 'idle',
  setWsStatus: (wsStatus) => set({ wsStatus }),

  schemaWarning: null,
  setSchemaWarning: (schemaWarning) => set({ schemaWarning }),

  droppedFrames: 0,
  setDroppedFrames: (droppedFrames) => set({ droppedFrames }),

  sendBackpressure: null,
  setSendBackpressure: (sendBackpressure) => set({ sendBackpressure }),

  resyncing: false,
  setResyncing: (resyncing) => set({ resyncing }),

  liveRefreshMs: 1000,
  setLiveRefreshMs: (liveRefreshMs) => set({ liveRefreshMs }),

  selectedPoint: null,
  setSelectedPoint: (selectedPoint) => set({ selectedPoint }),

  trendWatched: [],
  setTrendWatched: (trendWatched) => set({ trendWatched }),

  chartSnapshots: [],
  setChartSnapshots: (chartSnapshots) => set({ chartSnapshots }),
}))
