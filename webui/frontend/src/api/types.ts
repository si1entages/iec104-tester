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
  /** 由信封携带（裸帧缺省） */
  ts?: number
  direction: string
  len: number
  hex: string
  client?: string
}

export interface EngineEvent {
  ts?: number
  type: string
  data: Record<string, unknown>
}

export interface RecentResponse {
  /** 信封形态 `{kind, ts, data}`，见 normalizer */
  frames: unknown[]
  events: unknown[]
}

/** 报文逐段翻译（契约 §2.9，第二批体验改造 ④） */
export interface FrameSegment {
  title: string
  lines: string[]
}

export interface FrameTranslation {
  format: 'I' | 'S' | 'U' | '?'
  segments: FrameSegment[]
}

export interface FrameDecodeResponse {
  ok: boolean
  error?: string
  translation?: FrameTranslation
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

/** 可选 TLS 传输加密配置（T20），形态与多站 StationConfig.tls 一致 */
export interface TlsOptions {
  enabled?: boolean
  certfile?: string
  keyfile?: string
  cafile?: string
  verify?: boolean
  verify_client?: boolean
  server_hostname?: string
}

export interface MasterStartRequest {
  host?: string
  port?: number
  addr?: number
  reconnect?: boolean
  gi_interval?: number
  tls?: TlsOptions
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
  /** true → COT=8 DEACT 撤销帧（D1）；撤销 SBO 选择时与 select=true 同发 */
  deactivate?: boolean
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
  tls?: TlsOptions
}

/** `POST /api/slave/step`：置数并自发上送步位置（`M_ST_TB_1`, COT=3）（T09） */
export interface SlaveStepRequest {
  ioa: number
  /** -64..63 */
  value: number
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

// ── 子站应答行为（契约 §2.3 `POST /api/slave/response`）────────────────
// 与 `core/engine/slave_response.py::ResponseBehavior.from_dict` 一一对应；
// 缺失的分组/键一律取后端默认值。

/** 延迟（秒） */
export interface SlaveDelays {
  gi?: number
  command?: number
  data?: number
}

export interface SlaveErrors {
  drop_frames?: boolean
  /** 丢帧比例 0..1 */
  drop_rate?: number
  /** 损坏帧 */
  corrupt?: boolean
  /** 不响应 */
  no_response?: boolean
  /** 应答 COT 整体错位（+1），验证主站对 COT 的严格校验 */
  wrong_cot?: boolean
}

/** 品质描述词注入 */
export interface SlaveQuality {
  invalid?: boolean
  blocked?: boolean
  not_topical?: boolean
  overflow?: boolean
}

export interface SlaveConnectionBehavior {
  reject_startdt?: boolean
  auto_stopdt?: boolean
  send_testfr?: boolean
  testfr_interval?: number
}

export interface SlaveResponseBehavior {
  delays?: SlaveDelays
  errors?: SlaveErrors
  quality?: SlaveQuality
  connection?: SlaveConnectionBehavior
}

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

// ── 主站参数状态（T08，契约 §2.6 / §4.6）───────────────────────────────

export type ParameterResult =
  | 'unknown'
  | 'pending'
  | 'ok'
  | 'terminated'
  | 'rejected'
  | 'timeout'

/** 参数命令在目标 IOA 上的装载/激活推进快照 */
export interface ParameterStateEntry {
  ioa: number
  loadResult: ParameterResult
  /** 装载应答的传送原因 */
  loadCot: number | null
  /** monotonic 秒值（用于算时长，非绝对时间） */
  loadUpdatedAt: number | null
  activationResult: ParameterResult
  activationCot: number | null
  activationUpdatedAt: number | null
}

/** `GET /api/master/param_state?ioa=<int>` */
export interface ParamStateResponse {
  ok: boolean
  ioa: number
  /** 从未下发过参数命令时为 null */
  state: ParameterStateEntry | null
}

/** `GET /api/master/params` */
export interface ParamsResponse {
  ok: boolean
  params: ParameterStateEntry[]
}

// ── 多站（T16，契约 §2.8 / §4.7）───────────────────────────────────────

/** 多站单站配置（字段均有默认值，仅 `station_id` 必填） */
export interface StationConfig {
  station_id: string
  station_name?: string
  host?: string
  port?: number
  common_addr?: number
  max_connections?: number
  point_table_file?: string
  auto_generate?: boolean
  yx_count?: number
  yc_count?: number
  yk_count?: number
  ym_count?: number
  spontaneous_enabled?: boolean
  simulation_enabled?: boolean
  yx_interval?: number
  yc_interval?: number
  yx_change_rate?: number
  yc_change_range?: number
}

export interface StationStatus {
  station_id: string
  station_name: string
  port: number
  common_addr: number
  running: boolean
  client_count: number
  yx_count: number
  yc_count: number
  yk_count: number
  ym_count: number
  simulation_active: boolean
}

export interface StationSummary {
  id: string
  name: string
  port: number
  clients: number
}

export interface MultiStartRequest {
  stations: StationConfig[]
}

/**
 * `POST /api/multi/start` 响应。
 *
 * 注意：契约 §2.8 只写了 `{ok, stations?, error?}` 而**未规定 `stations` 的类型**；
 * 实现（`webui/session.py::multi_start`）返回的是**已启动站数（int）**，
 * 不是 `StationStatus[]`。这里按实现投影，并在测试里锁住该形状。
 */
export interface MultiStartResponse {
  ok: boolean
  /** 已启动站数（int，非数组） */
  stations?: number
  error?: string
}

export interface MultiStatusResponse {
  ok: boolean
  running: boolean
  stations: StationStatus[]
}

export interface MultiSummaryResponse {
  ok: boolean
  running: boolean
  station_count: number
  total_clients: number
  uptime: number
  /** 以下四项为实现的额外字段（契约 §4.7 只列了最小集） */
  total_yx?: number
  total_yc?: number
  total_yk?: number
  total_ym?: number
  stations: StationSummary[]
}

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
  /** 注意：`bridge.recent()` 返回的是**信封形态** `{kind, ts, data}`，用 normalizer 归一化 */
  frames?: unknown[]
  events?: unknown[]
  logs?: unknown[]
}

export type WsMessage =
  | WsEnvelope<'snapshot', WsSnapshotData>
  | WsEnvelope<'frame', Frame>
  | WsEnvelope<'event', EngineEvent>
  | WsEnvelope<'log', LogRow>
