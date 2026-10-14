import { create } from 'zustand'

import type { LogRow } from '../api/types'

export type PageKey = 'status' | 'logs'

const MAX_LIVE_LOGS = 500

interface UiState {
  page: PageKey
  setPage: (page: PageKey) => void
  /** WS 连接状态（头部指示） */
  wsConnected: boolean
  setWsConnected: (connected: boolean) => void
  /** WS 实时日志环形缓冲 */
  liveLogs: LogRow[]
  seedLogs: (rows: LogRow[]) => void
  pushLog: (row: LogRow) => void
  clearLogs: () => void
}

export const useUiStore = create<UiState>((set) => ({
  page: 'status',
  setPage: (page) => set({ page }),
  wsConnected: false,
  setWsConnected: (wsConnected) => set({ wsConnected }),
  liveLogs: [],
  seedLogs: (rows) => set({ liveLogs: rows.slice(-MAX_LIVE_LOGS) }),
  pushLog: (row) =>
    set((state) => ({ liveLogs: [...state.liveLogs, row].slice(-MAX_LIVE_LOGS) })),
  clearLogs: () => set({ liveLogs: [] }),
}))
