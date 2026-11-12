/** 旁路真实网卡抓包卡片的共享逻辑（WP9）——Carbon / PF 复用。 */

import { useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../api/endpoints'
import { queryKeys, useSniffQuery } from '../api/queries'

export function useSniffer() {
  const client = useQueryClient()
  const q = useSniffQuery()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    void client.invalidateQueries({ queryKey: queryKeys.sniff() })
  }, [client])

  const guard = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [refresh])

  const start = useCallback(() => {
    void guard(async () => {
      const r = await api.sniff.start({})
      // 后端能力不足时返回 ok=false（HTTP 200），错误信息要原样呈现
      if (r.ok === false) setError(String(r.error ?? ''))
    })
  }, [guard])

  const stop = useCallback(() => {
    void guard(() => api.sniff.stop())
  }, [guard])

  const status = q.data
  const cap = status?.capability

  return {
    status,
    capability: cap,
    running: Boolean(status?.running),
    frames: status?.frames ?? 0,
    stats: status?.stats,
    busy,
    error,
    refresh,
    actions: { start, stop },
  }
}
