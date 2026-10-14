/**
 * 与 `webui/api_contract.md` 对齐的 REST/WS 类型定义。
 * 权威契约见该文档；本文件是它的 TypeScript 投影（T11）。
 */

export type Role = 'master' | 'slave'

/** 所有命令端点的通用响应；失败含 `error`。 */
export interface OkResponse {
  ok: boolean
  error?: string
}

export type CommandResponse = OkResponse

// ── 状态与点表 ─────────────────────────────────────────────────────────

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
  /** 背压丢弃累计（订阅队列满时丢最旧） */
  dropped?: number
  tx?: number
  rx?: number
  vs?: number
  vr?: number
  window?: string
  clients?: number
  client_list?: string[]
  simulation?: boolean
  schemaVersion?: number
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

export interface RecentResponse {
  frames: Frame[]
  events: EngineEvent[]
}

/** `GET /api/schema` */
export interface SchemaResponse {
  ok: true
  schemaVersion: number
  wsKinds: string[]
  wsSchemaKey: string
}

/** `GET /api/export/session.json` */
export interface SessionExport {
  role: Role
  status: Status
  frames: Frame[]
  events: EngineEvent[]
}

// ── 日志 ───────────────────────────────────────────────────────────────

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
  source?: string
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

// ── 请求体 ─────────────────────────────────────────────────────────────

export interface MasterStartRequest {
  host?: string
  port?: number
  addr?: number
  reconnect?: boolean
  gi_interval?: number
}

/** 1–16 = 组召唤；20 = 站召唤（默认） */
export interface GiRequest {
  qoi?: number
}

export interface YkRequest {
  ioa: number
  state?: 0 | 1
  select?: boolean
  double?: boolean
  /** true → C_SC_TA_1 / C_DC_TA_1（带时标） */
  with_time?: boolean
}

export type SetpointKind = 'short_float' | 'normalized' | 'scaled'

export interface SetpointRequest {
  ioa: number
  value: number
  kind?: SetpointKind
  select?: boolean
  with_time?: boolean
}

export interface StepRequest {
  ioa: number
  /** 1 = 降一步，2 = 升一步 */
  state: 1 | 2
  select?: boolean
}

export interface BitstringRequest {
  ioa: number
  /** 32bit 比特串 */
  value: number
}

export interface DelayRequest {
  /** 0–60000 ms */
  delay_ms: number
}

export interface ReadRequest {
  ioa: number
}

export type ParamKind = 'float' | 'normalized' | 'scaled' | 'activation'

export interface ParamRequest {
  kind: ParamKind
  ioa: number
  value?: number
  qualifier?: number
}

export type FileAction = 'directory' | 'select' | 'request'

export interface FileRequest {
  action: FileAction
  ioa?: number
  file_name?: number
}

export interface SlaveStartRequest {
  host?: string
  port?: number
  addr?: number
}

export interface YxRequest {
  ioa: number
  value: boolean
}

export interface YcRequest {
  ioa: number
  value: number
}

export interface YmRequest {
  ioa: number
  value: number
}

export interface EpRequest {
  ioa: number
  /** 0–65535 */
  event_value?: number
  with_time?: boolean
}

export interface PsRequest {
  ioa: number
  /** 长度 1–8，元素 0/1 */
  states: number[]
}

/** 响应行为配置（延迟 / 错误注入 / 品质 / 连接行为），键由后端定义 */
export type ResponseBehavior = Record<string, unknown>

export interface SimRequest {
  enabled: boolean
  yx_interval?: number
  yc_interval?: number
  yx_change_rate?: number
  yc_change_range?: number
}

export type BatchAction = 'enable' | 'disable' | 'group'

export interface BatchPointsRequest {
  type: string
  ioas: number[]
  action: BatchAction
  group?: number | null
}

export type ImportFormat = 'csv' | 'yaml' | 'json' | 'auto'

// ── WebSocket ──────────────────────────────────────────────────────────

/** WS 信封：`{kind, schemaVersion, ts, data}` */
export interface WsEnvelope<K extends string, D> {
  kind: K
  schemaVersion?: number
  ts?: number
  data: D
}

export interface WsSnapshotData {
  schemaVersion?: number
  points: Point[]
  status: Status
  frames?: Frame[]
  events?: EngineEvent[]
  logs?: LogRow[]
}

export type WsMessage =
  | WsEnvelope<'snapshot', WsSnapshotData>
  | WsEnvelope<'frame', Frame>
  | WsEnvelope<'event', EngineEvent>
  | WsEnvelope<'log', LogRow>
