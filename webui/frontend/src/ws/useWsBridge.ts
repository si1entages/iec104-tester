import { useEffect } from 'react'

import { useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../api/queries'
import type { WsMessage } from '../api/types'
import { useUiStore } from '../store/uiStore'
import { WsClient, resolveWsUrl } from './client'

/**
 * 把全局 WS 接到 React Query 缓存与 Zustand：
 * - snapshot：覆盖 status / points 缓存，并重置 live 日志
 * - log：增量推入 live 日志环形缓冲
 * （frame / event 由 T12/T13 的报文查看器消费）
 */
export function useWsBridge(): void {
  const queryClient = useQueryClient()
  const setWsConnected = useUiStore((s) => s.setWsConnected)
  const seedLogs = useUiStore((s) => s.seedLogs)
  const pushLog = useUiStore((s) => s.pushLog)

  useEffect(() => {
    const client = new WsClient(resolveWsUrl())

    const handle = (msg: WsMessage) => {
      switch (msg.kind) {
        case 'snapshot':
          queryClient.setQueryData(queryKeys.status, msg.data.status)
          queryClient.setQueryData(queryKeys.points, msg.data.points)
          if (msg.data.logs) seedLogs(msg.data.logs)
          break
        case 'log':
          pushLog(msg.data)
          break
        default:
          break
      }
    }

    const unsubscribe = client.subscribe(handle)
    client.onOpen = () => setWsConnected(true)
    client.onClose = () => setWsConnected(false)
    client.connect()

    return () => {
      unsubscribe()
      client.close()
    }
  }, [queryClient, setWsConnected, seedLogs, pushLog])
}
