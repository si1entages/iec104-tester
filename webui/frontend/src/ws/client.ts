import type { WsMessage } from '../api/types'

export type WsStatus = 'idle' | 'connecting' | 'open' | 'closed'

export type WsListener = (msg: WsMessage) => void

export interface WsBackpressureInfo {
  /** 发送缓冲待写字节数（WebSocket.bufferedAmount） */
  bufferedBytes: number
  /** 触发阈值 */
  threshold: number
  /** 连续第几次触发（>1 说明积压未缓解） */
  streak: number
}

export interface WsClientOptions {
  /** bufferedAmount 超过该字节数即认为发送侧积压 */
  backpressureBytes?: number
  /** 重连退避上限（ms） */
  maxBackoffMs?: number
  /** 重连退避基数（ms） */
  baseBackoffMs?: number
  onStatus?: (status: WsStatus) => void
  onBackpressure?: (info: WsBackpressureInfo) => void
  /** 每次成功建连（含重连）后回调：用于把「等待快照」状态置位 */
  onOpen?: () => void
  onClose?: () => void
}

/**
 * WS 客户端（T11）：指数退避重连 + 背压感知 + 订阅分发。
 *
 * 契约要点（见 webui/api_contract.md §3）：
 *  - 服务端建连后**先推 snapshot 再推增量**，因此「snapshot 先行」由服务端保证；
 *    消费侧由 useWsBridge 做缓冲兜底（快照到达前不应用增量）。
 *  - 消息信封为 `{kind, schemaVersion, ts, data}`。
 *  - 后端订阅队列容量 256，写满时**丢最旧**并累加 `Status.dropped`，
 *    前端通过 status 感知（本类的 bufferedAmount 只覆盖「发」方向）。
 */
export class WsClient {
  private readonly url: string
  private readonly options: Required<
    Pick<WsClientOptions, 'backpressureBytes' | 'maxBackoffMs' | 'baseBackoffMs'>
  > &
    WsClientOptions

  private socket: WebSocket | null = null
  private listeners = new Set<WsListener>()
  private retries = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private disposed = false
  private backpressureStreak = 0

  status: WsStatus = 'idle'

  constructor(url: string, options: WsClientOptions = {}) {
    this.url = url
    this.options = {
      backpressureBytes: 1 << 20, // 1 MiB
      maxBackoffMs: 30_000,
      baseBackoffMs: 1_000,
      ...options,
    }
  }

  connect(): void {
    if (this.disposed || this.socket) return
    this.setStatus('connecting')
    const socket = new WebSocket(this.url)
    this.socket = socket

    socket.onopen = () => {
      this.retries = 0
      this.setStatus('open')
      this.options.onOpen?.()
    }
    socket.onmessage = (event) => {
      this.checkBackpressure()
      let msg: WsMessage
      try {
        msg = JSON.parse(event.data as string) as WsMessage
      } catch {
        return
      }
      for (const listener of this.listeners) listener(msg)
    }
    socket.onerror = () => {
      // onerror 后浏览器必定触发 onclose，重连统一放在 onclose
    }
    socket.onclose = () => {
      this.socket = null
      this.setStatus('closed')
      this.options.onClose?.()
      this.scheduleReconnect()
    }
  }

  /** 发送文本；返回是否真正写出（socket 未就绪时返回 false）。 */
  send(payload: string): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(payload)
    this.checkBackpressure()
    return true
  }

  /** 请求服务端重推一次 snapshot（"snapshot 先行" 的手动对齐入口）。 */
  requestRefresh(): boolean {
    return this.send('refresh')
  }

  subscribe(listener: WsListener): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  close(): void {
    this.disposed = true
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    this.socket?.close()
    this.socket = null
    this.setStatus('closed')
  }

  private setStatus(status: WsStatus): void {
    if (this.status === status) return
    this.status = status
    this.options.onStatus?.(status)
  }

  /** 发送侧积压检测：bufferedAmount 持续超阈值即上报（连续次数递增）。 */
  private checkBackpressure(): void {
    const bufferedBytes = this.socket?.bufferedAmount ?? 0
    const threshold = this.options.backpressureBytes
    if (bufferedBytes > threshold) {
      this.backpressureStreak += 1
      this.options.onBackpressure?.({ bufferedBytes, threshold, streak: this.backpressureStreak })
    } else {
      this.backpressureStreak = 0
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.timer) return
    const { baseBackoffMs, maxBackoffMs } = this.options
    const delay = Math.min(maxBackoffMs, baseBackoffMs * 2 ** this.retries)
    this.retries += 1
    this.timer = setTimeout(() => {
      this.timer = null
      this.connect()
    }, delay)
  }
}

/** 同源 WS 地址：dev 期由 vite 代理 /ws 到后端。 */
export function resolveWsUrl(path = '/ws'): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}${path}`
}
