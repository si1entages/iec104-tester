import { create } from 'zustand'

import type { WsStatus } from '../ws/client'

export type PageKey = 'status' | 'master' | 'slave' | 'multi' | 'logs'

/**
 * 纯 UI 状态（T11）。
 * 约束：**不在 Zustand 里缓存服务端数据**——状态 / 点表 / 日志全部由 React Query 持有，
 * 本 store 只保存「界面上打开哪个页、连接指示、告警文案」这类本地状态。
 */
interface UiState {
  page: PageKey
  setPage: (page: PageKey) => void

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
}

export const useUiStore = create<UiState>((set) => ({
  page: 'status',
  setPage: (page) => set({ page }),

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
}))
