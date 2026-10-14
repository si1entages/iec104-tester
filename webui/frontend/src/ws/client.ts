import type { WsMessage } from '../api/types'

export type WsListener = (msg: WsMessage) => void

/**
 * 极简 WS 客户端：断线指数退避重连 + 订阅分发。
 * T11 将在此基础上补充背压提示、心跳与契约版本适配。
 */
export class WsClient {
  private readonly url: string
  private socket: WebSocket | null = null
  private listeners = new Set<WsListener>()
  private retries = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private disposed = false

  onOpen?: () => void
  onClose?: () => void

  constructor(url: string) {
    this.url = url
  }

  connect(): void {
    if (this.disposed || this.socket) return
    const socket = new WebSocket(this.url)
    this.socket = socket

    socket.onopen = () => {
      this.retries = 0
      this.onOpen?.()
    }
    socket.onmessage = (event) => {
      let msg: WsMessage
      try {
        msg = JSON.parse(event.data as string) as WsMessage
      } catch {
        return
      }
      for (const listener of this.listeners) listener(msg)
    }
    socket.onerror = () => {
      // onerror 后浏览器必定触发 onclose，重连逻辑统一放在 onclose
    }
    socket.onclose = () => {
      this.socket = null
      this.onClose?.()
      this.scheduleReconnect()
    }
  }

  send(payload: string): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(payload)
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
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.timer) return
    const delay = Math.min(30_000, 1_000 * 2 ** this.retries)
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
