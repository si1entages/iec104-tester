import { useEffect } from 'react'

import { useQueryClient } from '@tanstack/react-query'

import {
  appendEvent,
  appendFrame,
  appendLiveLogs,
  queryKeys,
  replaceEvents,
  replaceFrames,
  replaceLiveLogs,
} from '../api/queries'
import { describeSchemaMismatch } from '../api/schema'
import type { LogRow, Point, WsMessage } from '../api/types'
import { isLogRow, isPointsResponse, isStatus, isWsMessage, readSchemaVersion } from '../api/validate'
import { tNow } from '../i18n'
import { applyPatches, extractPatches, mergePointValues, pointKey } from '../lib/pointValue'
import { normalizeEvent, normalizeEvents, normalizeFrame, normalizeFrames } from '../lib/records'
import { trendBuffer } from '../lib/trendBuffer'
import { useUiStore } from '../store/uiStore'
import { WsClient, resolveWsUrl } from './client'

/** 快照到达前最多缓冲的增量条数（防极端乱序导致内存膨胀） */
const MAX_PENDING = 2000

/** 高频日志批量合并窗口（ms）：窗口内的 log 消息整批一次写入缓存，不逐条渲染 */
const LOG_FLUSH_MS = 250

/**
 * 全局 WS 桥（T11/T12）：
 *  - **snapshot 先行**：建连/重连后先等 snapshot 对齐缓存，期间的增量先入缓冲，
 *    快照落地后再按序回放（服务端本就是快照先行，这里是消费侧兜底）
 *  - 服务端状态写入 **React Query 缓存**（status / points / frames / events / logs）
 *  - 点值走两条路径：`event.data_received` 的**增量补丁**（O(1)、不联网），
 *    以及按 `liveRefreshMs` 节流的**全量快照对齐**（兜底，大点表下可调大/关闭）
 *  - 契约版本不匹配 → 记录降级告警，**照常渲染不崩溃**
 *  - 背压：后端丢帧经 `Status.dropped` 暴露；发送侧积压经 `bufferedAmount` 上报
 */
export function useWsBridge(): void {
  const queryClient = useQueryClient()
  const setWsStatus = useUiStore((s) => s.setWsStatus)
  const setSchemaWarning = useUiStore((s) => s.setSchemaWarning)
  const setDroppedFrames = useUiStore((s) => s.setDroppedFrames)
  const setSendBackpressure = useUiStore((s) => s.setSendBackpressure)
  const setResyncing = useUiStore((s) => s.setResyncing)

  useEffect(() => {
    let awaitingSnapshot = true
    let pending: WsMessage[] = []
    let refreshTimer: ReturnType<typeof setTimeout> | null = null
    let pendingLogs: LogRow[] = []
    let logFlushTimer: ReturnType<typeof setTimeout> | null = null

    const flushLogs = (): void => {
      logFlushTimer = null
      if (pendingLogs.length === 0) return
      const rows = pendingLogs
      pendingLogs = []
      appendLiveLogs(queryClient, rows)
    }

    const recordTrend = (rows: Point[]): void => {
      if (rows.length === 0) return
      const ts = Date.now() / 1000
      for (const row of rows) {
        const key = pointKey(row)
        if (trendBuffer.isWatched(key)) trendBuffer.record(key, ts, row.value)
      }
    }

    const applyStatus = (status: unknown): void => {
      if (!isStatus(status)) return
      queryClient.setQueryData(queryKeys.status, status)
      if (typeof status.schemaVersion === 'number') {
        setSchemaWarning(describeSchemaMismatch(status.schemaVersion))
      }
      if (typeof status.dropped === 'number') setDroppedFrames(status.dropped)
    }

    const scheduleRefresh = (): void => {
      const ms = useUiStore.getState().liveRefreshMs
      if (ms <= 0 || refreshTimer) return
      refreshTimer = setTimeout(() => {
        refreshTimer = null
        client.requestRefresh()
      }, ms)
    }

    const apply = (msg: WsMessage): void => {
      switch (msg.kind) {
        case 'snapshot': {
          const data = msg.data
          const remote = readSchemaVersion(msg) ?? readSchemaVersion(data)
          if (remote !== undefined) setSchemaWarning(describeSchemaMismatch(remote))
          applyStatus(data?.status)

          if (data && isPointsResponse(data)) {
            const changed: Point[] = []
            queryClient.setQueryData<Point[]>(queryKeys.points, (prev) =>
              mergePointValues(prev, data.points, changed),
            )
            recordTrend(changed)
          }

          const frames = normalizeFrames(data?.frames)
          if (frames.length > 0) replaceFrames(queryClient, frames)
          const events = normalizeEvents(data?.events)
          if (events.length > 0) replaceEvents(queryClient, events)
          if (Array.isArray(data?.logs)) replaceLiveLogs(queryClient, data.logs.filter(isLogRow))

          setResyncing(false)
          break
        }
        case 'frame': {
          const frame = normalizeFrame(msg)
          if (frame) {
            appendFrame(queryClient, frame)
            scheduleRefresh()
          }
          break
        }
        case 'event': {
          const event = normalizeEvent(msg)
          if (!event) break
          appendEvent(queryClient, event)
          const patches = extractPatches(event)
          if (patches.length > 0) {
            // 主路径：事件直接携带点值，就地更新，不联网
            const changed: Point[] = []
            queryClient.setQueryData<Point[]>(queryKeys.points, (prev) =>
              applyPatches(prev, patches, changed),
            )
            recordTrend(changed)
          } else {
            // 兜底：形状不认识（如子站 data_changed）时按节流拉一次快照
            scheduleRefresh()
          }
          break
        }
        case 'log':
          // 批量合并：窗口内的日志先入缓冲，统一一次写入（避免高频日志逐条触发渲染）
          if (isLogRow(msg.data)) {
            pendingLogs.push(msg.data)
            if (!logFlushTimer) logFlushTimer = setTimeout(flushLogs, LOG_FLUSH_MS)
          }
          break
        default:
          break
      }
    }

    const handle = (raw: WsMessage): void => {
      if (!isWsMessage(raw)) return
      if (raw.kind === 'snapshot') {
        awaitingSnapshot = false
        apply(raw)
        if (pending.length) {
          const buffered = pending
          pending = []
          for (const msg of buffered) apply(msg)
        }
        return
      }
      if (awaitingSnapshot) {
        if (pending.length < MAX_PENDING) pending.push(raw)
        return
      }
      apply(raw)
    }

    const client = new WsClient(resolveWsUrl(), {
      onStatus: setWsStatus,
      onOpen: () => {
        // 每次（重）连都要重新等一次快照，避免用陈旧缓存接收增量
        awaitingSnapshot = true
        setResyncing(true)
        setSendBackpressure(null)
      },
      onBackpressure: ({ bufferedBytes, threshold, streak }) => {
        setSendBackpressure(
          tNow('ws.backpressure', {
            kb: (bufferedBytes / 1024).toFixed(0),
            thr: (threshold / 1024).toFixed(0),
            n: streak,
          }),
        )
      },
    })

    const unsubscribe = client.subscribe(handle)
    client.connect()

    return () => {
      unsubscribe()
      if (refreshTimer) clearTimeout(refreshTimer)
      if (logFlushTimer) clearTimeout(logFlushTimer)
      client.close()
    }
  }, [
    queryClient,
    setWsStatus,
    setSchemaWarning,
    setDroppedFrames,
    setSendBackpressure,
    setResyncing,
  ])
}
