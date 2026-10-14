/** 与 `webui/api_contract.md` 对齐的 REST/WS 类型定义（T10 首版，T11 完善）。 */

export type Role = 'master' | 'slave'

export interface Status {
  role: Role
  /** 会话是否已有引擎（连接中/已连接/监听中/连接失败都算） */
  started?: boolean
  running?: boolean
  /** 主站连接状态机字符串 */
  state?: string
  host?: string
  port?: number
  addr?: number
  points?: number
  dropped?: number
  tx?: number
  rx?: number
  vs?: number
  vr?: number
  window?: string
  clients?: number
  client_list?: string[]
  [key: string]: unknown
}

export interface Point {
  ioa: number
  type: string
  name: string
  group?: number | string
  enabled: boolean
  value?: number | boolean | string | null
  quality?: string
}

export interface PointsResponse {
  points: Point[]
}

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'

export interface LogRow {
  ts: number
  level: LogLevel | string
  source: string
  category: string
  message: string
  data?: Record<string, unknown>
}

export interface LogStats {
  total?: number
  by_level?: Record<string, number>
  [key: string]: unknown
}

export interface LogsResponse {
  ok: boolean
  logs: LogRow[]
  stats?: LogStats
}

export interface LogQueryParams {
  level_min?: string
  category?: string
  source?: string
  q?: string
  limit?: number
}

export interface Frame {
  direction: string
  len: number
  hex: string
  client?: string
}

export interface EngineEvent {
  type: string
  data: Record<string, unknown>
}

/** WS 线上消息：`{ kind, ts, data }`（见 `webui/events.py` EventBus.publish） */
export interface WsSnapshotData {
  points: Point[]
  status: Status
  frames?: Frame[]
  events?: EngineEvent[]
  logs?: LogRow[]
}

export type WsMessage =
  | { kind: 'snapshot'; ts?: number; data: WsSnapshotData }
  | { kind: 'frame'; ts?: number; data: Frame }
  | { kind: 'event'; ts?: number; data: EngineEvent }
  | { kind: 'log'; ts?: number; data: LogRow }
