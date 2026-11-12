/**
 * 与 `webui/api_contract.md` 对齐的 REST/WS 类型定义。
 * 权威契约见该文档；本文件是它的 TypeScript 投影（T11）。
 */

export type Role = 'master' | 'slave' | 'bridge'

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
  /** 当前模拟是否包含遥信 / 遥测（仅 simulation=true 时有意义） */
  simulation_yx?: boolean
  simulation_yc?: boolean
  /** 冗余双通道运行态（仅主站启用时存在）（E3） */
  redundancy?: RedundancyStatus
  /** 链路可观测快照（WP6；无引擎时 state/sequence 为 null，transport 仍有目标） */
  link?: LinkSnapshot
  /** 生效的 ASDU 地址字段字节数（WP1；由 --config / --ca-length 等注入） */
  asdu_address?: {
    ca_length: number
    ioa_length: number
    cot_length: number
  }
  /** 桥角色运行统计（running 时存在）（T74） */
  bridge_stats?: Record<string, number>
  /** 桥角色当前配置（running 时存在） */
  bridge_cfg?: {
    listen_host?: string
    listen_port?: number
    upstream_host?: string
    upstream_port?: number
  }
  /** 桥角色合规监视（running 时存在）（T79） */
  compliance?: {
    violation_total?: number
    counts?: Record<string, number>
    frames_seen?: number
    violations?: Array<{ ts?: number; side?: string; kind?: string; detail?: string }>
  }
  /** 桥角色网络条件注入（running 时存在）（T85） */
  injection?: Record<string, number>
  condition?: string
  condition_active?: boolean
  schemaVersion?: number
}

/** 主站冗余双通道运行态（`MasterRedundancy.status()` 的 TS 投影） */
export interface RedundancyStatus {
  enabled: boolean
  active: 'primary' | 'standby' | null
  primary_connected: boolean
  standby_connected: boolean
  standby_host: string
  standby_port: number
  switch_timeout: number
  dedup_window: number
  failovers: number
}

/** `POST /api/master/start` 的冗余配置（省略时沿用 CLI/--config） */
export interface RedundancyOptions {
  enabled?: boolean
  standby_host?: string
  standby_port?: number
  switch_timeout?: number
  dedup_window?: number
}

export interface Point {
  ioa: number
  type: string
  name: string
  group?: number | string
  enabled: boolean
  value?: number | boolean | string | null
  quality?: string
  /** 类型细分：YX single/double；YC short_float/normalized/scaled；YK single/double */
  subtype?: string
  /** 仅 YK：是否需要选择-执行（SBO） */
  sbo?: boolean
  /** WP4b：命令点（YK/YC/STEP）的防误操作闭锁条件；空/缺省 = 未配置 */
  interlock?: InterlockCondition[]
  /** 仅 YC：工程单位（设计规范 §5.3，界面按 `值 + 单位` 显示） */
  unit?: string
  /** 仅 YC：显式小数位（缺省按量级推断） */
  decimal_places?: number
  /** T93：最后更新时间（毫秒 epoch；0=未收到过数据） */
  ts?: number
  /** 仅 YC：限值（值守告警 T93 限值规则） */
  min_value?: number
  max_value?: number
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

// ── 报文值域解码树（WP7，契约 §2.9）───────────────────────────────────

/** 五位品质位（按 IEC 60870-5-101；SIQ/DIQ 的 bit0 是值本身，无 OV） */
export interface QualityBits {
  iv: boolean
  nt: boolean
  sb: boolean
  bl: boolean
  ov: boolean
}

/** 单个信息对象（SQ=1 时已展开为 base+i） */
export interface FrameObject {
  index: number
  ioa: number
  /** SQ=1 时的对象内序号（0 起）；SQ=0 无此键 */
  sq_index?: number
  value_display: string
  value: number | boolean | string | null
  quality: string
  quality_bits: QualityBits | null
  quality_raw: number | null
  timestamp: string | null
  raw_hex: string | null
}

export interface FrameApciTree {
  length: number
  asdu_length: number
  frame_type: string
  tx_seq: number | null
  rx_seq: number | null
  u_func: number | null
  u_func_name: string | null
}

export interface FrameAsduTree {
  type_id: number
  type_name: string
  sq: boolean
  num: number
  cot: number
  cot_name: string
  pn: boolean
  test: boolean
  origin_addr: number
  common_addr: number
  object_count: number
}

/** 结构化解码树（WP7）：与 segments 文本互补，供表格展开子表 */
export interface FrameTree {
  ok: boolean
  error?: string
  format: 'I' | 'S' | 'U' | '?'
  apci: FrameApciTree | null
  asdu: FrameAsduTree | null
  objects: FrameObject[]
}

/** 与后端契约 §2.9 一致：成功响应是**扁平**结构，没有 `translation` 包裹层 */
export interface FrameDecodeResponse {
  ok: boolean
  error?: string
  format?: FrameTranslation['format']
  segments?: FrameSegment[]
  /** WP7：结构化树（纯新增键；旧消费方忽略） */
  tree?: FrameTree | null
}

/** `GET /api/schema` */
export interface SchemaResponse {
  ok: true
  schemaVersion: number
  wsKinds: string[]
  wsSchemaKey: string
  /** 可用角色：单角色模式一个；合并模式 master + slave */
  roles?: Role[]
  /** 合并模式下子站 API/WS 前缀（如 /slave） */
  slaveApiPrefix?: string
}

/** `GET /api/export/session.json`（帧/事件按 `EventBus.recent()` 原样导出为 WS 信封） */
export interface SessionExport {
  role: Role
  status: Status
  frames: WsEnvelope<'frame', Frame>[]
  events: WsEnvelope<'event', EngineEvent>[]
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
  redundancy?: RedundancyOptions
}

/** 1–16 = 组召唤；20 = 站召唤（默认） */
export interface GiRequest {
  qoi?: number
}

/** 防误操作闭锁条件（WP4b）：引用的遥信须处于期望位置 */
export interface InterlockCondition {
  ioa: number
  /** 期望位置：true=合位，false=分位 */
  value: boolean
  label?: string
}

export interface YkRequest {
  ioa: number
  /** 单命令 0=分/1=合；双命令 1=分/2=合 */
  state?: 0 | 1 | 2 | 3
  select?: boolean
  double?: boolean
  /** true → C_SC_TA_1 / C_DC_TA_1（带时标） */
  with_time?: boolean
  /** true → COT=8 DEACT 撤销帧（D1）；撤销 SBO 选择时与 select=true 同发 */
  deactivate?: boolean
  /** WP4b：闭锁不满足时强制下发（需 admin；服务端写强制解锁审计） */
  force?: boolean
}

export type SetpointKind = 'short_float' | 'normalized' | 'scaled'

export interface SetpointRequest {
  ioa: number
  value: number
  kind?: SetpointKind
  select?: boolean
  with_time?: boolean
  /** WP4b：闭锁不满足时强制下发（需 admin） */
  force?: boolean
}

export interface StepRequest {
  ioa: number
  /** 1 = 降一步，2 = 升一步 */
  state: 1 | 2
  select?: boolean
  /** WP4b：闭锁不满足时强制下发（需 admin） */
  force?: boolean
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
  substituted?: boolean
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
  /** 是否模拟遥信（默认 true；与 yc_enabled 至少一个为 true） */
  yx_enabled?: boolean
  /** 是否模拟遥测（默认 true；与 yx_enabled 至少一个为 true） */
  yc_enabled?: boolean
  yx_interval?: number
  yc_interval?: number
  /** YX 每周期翻转概率（0~1，每周期对范围内每点独立判定） */
  yx_change_rate?: number
  /** 仅对点表未声明量程的 YC 点生效：当前值 ± 比例浮动；声明量程的点直接在 [min,max] 内随机 */
  yc_change_range?: number
  /** YX 模拟范围：selected=仅 yx_ioas 列出的点；all=全部 YX 点（默认） */
  yx_scope?: 'selected' | 'all'
  /** YC 模拟范围：selected=仅 yc_ioas；all=全部 YC 点（默认） */
  yc_scope?: 'selected' | 'all'
  /** scope=selected 时的 YX 点集（点表外 IOA 被跳过） */
  yx_ioas?: number[]
  /** scope=selected 时的 YC 点集 */
  yc_ioas?: number[]
}

export type BatchAction = 'enable' | 'disable' | 'group'

export interface BatchPointsRequest {
  type: string
  ioas: number[]
  action: BatchAction
  group?: number | null
}

export type ImportFormat = 'csv' | 'yaml' | 'json' | 'auto'

/** SCD/CID/ICD（IEC 61850-6 SCL + 80-1 映射）预览响应（契约 §2.4a） */
export interface DoctorStep {
  key: string
  ok: boolean
  /** 后端生成的面向用户的人话结论（诊断输出，同引擎日志为中文） */
  detail: string
  evidence?: Record<string, unknown>
}

export interface DoctorReport {
  ok: boolean
  conclusion: string
  duration_ms: number
  steps: DoctorStep[]
}

export interface DoctorResponse {
  ok: boolean
  report: DoctorReport
}

export interface DoctorRequest {
  host: string
  port: number
  addr?: number
  observe_seconds?: number
}

export interface Alarm {
  id: number
  kind: 'limit' | 'stale' | 'jump' | 'comm'
  ioa: number | null
  message: string
  ts: number
  age_s: number
  acked: boolean
  cleared: boolean
}

export interface AlarmsSnapshot {
  ok: boolean
  config: {
    stale_seconds: number
    comm_seconds: number
    jump_delta: number | null
    debounce: number
    sound: boolean
  }
  active: Alarm[]
  new_since_poll: number
  history_total: number
}

export interface AlarmsHistory {
  ok: boolean
  history: Alarm[]
  total: number
}

export interface ScdPreviewResponse {
  ok: boolean
  /** 生成的点表 YAML 文本（可直接投给 /api/points/import?format=yaml） */
  yaml: string
  station_name: string
  common_addr: number
  stats: Record<string, number>
  warnings: string[]
}

// ── Excel 点表 + 设计基准比对（T95，契约 §2.4 / §4.14）─────────────────

export interface XlsxPreviewResponse {
  ok: boolean
  /** 各类型解析计数（仅 >0 的键） */
  stats: Record<string, number>
  /** 行级解析错误（坏行跳过不阻断） */
  errors: string[]
  /** 前 100 行摘要 */
  rows: XlsxPreviewRow[]
  total: number
  error?: string
}

export interface XlsxPreviewRow {
  ioa: number
  name: string
}

export interface XlsxImportResponse {
  ok: boolean
  points: number
  errors: string[]
  stats: Record<string, number>
  design: boolean
  error?: string
}

export interface DesignBaselineResponse {
  ok: boolean
  has_design: boolean
  points?: number
  error?: string
}

export interface DesignDiffPointLite {
  ioa: number
  type: string
  name: string
}

// ── 桥注入时间线（T97，契约 §2.4a / §4.15）────────────────────────────

export type TimelineExpect = 'none' | 'loss' | 'k-exceed' | 't1' | 'disconnect'

export interface TimelineStep {
  label: string
  duration_s: number
  condition: Record<string, number | string>
  expect: TimelineExpect
}

export interface TimelineViolation {
  ts: number
  kind: string
  side: string
  detail: string
}

export interface TimelineStepResult {
  label: string
  expect?: string
  ok?: boolean
  skipped?: boolean
  condition?: string
  detail: string
  observed?: {
    dropped: number
    disconnects: number
    clients: number
    violations: TimelineViolation[]
  }
  window_s?: number
}

export interface TimelineResult {
  ok: boolean
  steps: TimelineStepResult[]
  started_at: number
  duration_s: number
  stopped?: boolean
}

export interface TimelineState {
  ok: boolean
  running: boolean
  steps: TimelineStep[]
  last_result: TimelineResult | null
}

export interface TimelineAction {
  ok: boolean
  error?: string
  running?: boolean
  steps?: number
  stopping?: boolean
}

export interface DesignMismatch {
  ioa: number
  design: { type: string; min_value?: number; max_value?: number }
  actual: { type: string; min_obs?: number; max_obs?: number }
  reason: string
}

export interface DesignDiffResponse {
  ok: boolean
  has_design: boolean
  summary: { missing: number; extra: number; mismatch: number }
  missing: DesignDiffPointLite[]
  extra: DesignDiffPointLite[]
  mismatch: DesignMismatch[]
  truncated: boolean
  error?: string
}

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

/** `GET /api/master/param_state?ioa=<int>`（未连接时返回 `{ok:false,error}`） */
export interface ParamStateResponse {
  ok: boolean
  error?: string
  ioa?: number
  /** 从未下发过参数命令时为 null */
  state?: ParameterStateEntry | null
}

/** `GET /api/master/params`（未连接时返回 `{ok:false,error}`） */
export interface ParamsResponse {
  ok: boolean
  error?: string
  params?: ParameterStateEntry[]
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

// ── 历史库查询（契约 §2.11 / §4.9）──────────────────────────────────────

export interface HistoryDataRecord {
  id: number
  ts: number
  point_type: string
  ioa: number
  value: string
  quality: string
  source: string
}

export interface HistoryFrameRecord {
  id: number
  ts: number
  direction: string
  frame_type: string
  hex: string
  parsed: string
  client: string
}

export interface HistoryStats {
  data_records: number
  frame_records: number
  buffered_data: number
  buffered_frames: number
  oldest_data: number
  newest_data: number
  db_size_bytes: number
  dropped_records: number
}

export interface HistoryDataParams {
  point_type?: string
  ioa?: number
  start?: number
  end?: number
  limit?: number
}

export interface HistoryFramesParams {
  direction?: string
  start?: number
  end?: number
  limit?: number
}

export interface HistoryRowsResponse<T> {
  ok: boolean
  enabled: boolean
  rows: T[]
}

export interface HistoryStatsResponse {
  ok: boolean
  enabled: boolean
  stats: HistoryStats
}

// ── 网络异常模拟（契约 §2.12 / §4.10）──────────────────────────────────

export interface NetworkCondition {
  delay_ms: number
  delay_variance_ms: number
  loss_rate: number
  duplicate_rate: number
  corrupt_rate: number
  corrupt_bits: number
  reorder_rate: number
  reorder_window: number
  disconnect_rate: number
  disconnect_duration_s: number
  bandwidth_bps: number
  direction: string
  active: boolean
}

export type SimStats = Record<string, number>

export interface SimulationStatusResponse {
  ok: boolean
  enabled: boolean
  installed: boolean
  active: boolean
  describe: string
  condition: NetworkCondition
  stats: SimStats
  presets: string[]
}

export interface SimulationRequest {
  enabled: boolean
  preset?: string
  condition?: Partial<NetworkCondition>
}

/** 认证探测（契约 §2.13）：是否需要令牌、本次携带的令牌是否有效；
 * WP4a 纯新增 mode/operator/role（旧消费方可忽略） */
export interface AuthProbeResponse {
  ok: boolean
  required: boolean
  valid: boolean
  mode?: 'none' | 'token' | 'users'
  operator?: string
  role?: string
}

// ── 点表在线编辑（WP10a）──────────────────────────────────────────────

/** 点定义编辑载荷：type 由外层带；point.ioa 必填，其余可省略（就地改字段） */
export interface PointUpsertRequest {
  type: 'YX' | 'YC' | 'YK' | 'YM' | 'STEP'
  point: {
    ioa: number
    name?: string
    group?: number
    enabled?: boolean
    subtype?: string
    inverted?: boolean
    unit?: string
    min_value?: number
    max_value?: number
    dead_band?: number
    scale?: number
    offset?: number
    decimal_places?: number
    command_type?: string
    sbo?: boolean
    timeout_ms?: number
    step_size?: number
  }
}

export interface PointUpsertResponse {
  ok: boolean
  created: boolean
  error?: string
  point?: { ioa: number; type: string; name: string; group: number; enabled: boolean }
}

export interface PointDeleteResponse {
  ok: boolean
  deleted: boolean
  error?: string
}

// ── 旁路真实网卡抓包（WP9，契约 §2.14b）───────────────────────────────

export interface SniffCapability {
  available: boolean
  backend: string
  reason: string
  requires_root: boolean
}

export interface SniffStats {
  packets: number
  apdus: number
  bytes: number
  dropped: number
  errors: number
  last_error: string
}

export interface SniffStatus {
  ok: boolean
  running: boolean
  capability: SniffCapability
  stats: SniffStats
  frames: number
  port: number
}

// ── 链路可观测（WP6，契约 §2.4g）─────────────────────────────────────

export interface LinkTimerInfo {
  timeout: number
  /** false 表示未在计时（此时 remaining=0 是"没在计时"，不是"只剩 0 秒"） */
  active: boolean
  elapsed: number
  remaining: number
}

export interface LinkStateTransition {
  ts: number
  from: string
  to: string
}

export interface LinkStateSnapshot {
  state: string
  since_seconds: number
  timers: Record<string, LinkTimerInfo>
  history: LinkStateTransition[]
}

export interface LinkSequenceSnapshot {
  k: number
  w: number
  send_seq: number
  recv_seq: number
  last_ack_rx: number
  /** 已发送未确认 I 帧数——t1 超时的直接前因 */
  unacked: number
  window_available: boolean
  i_frame_count: number
}

export interface LinkTransportSnapshot {
  target: string
  connected: boolean
  tls: boolean
  reconnect_count: number
  max_reconnects: number
  reconnect_interval: number
  reconnect_in_seconds: number | null
  ever_connected: boolean
  last_error: string
  last_error_at: number
}

export interface LinkSnapshot {
  role: Role
  state: LinkStateSnapshot | null
  sequence: LinkSequenceSnapshot | null
  transport: LinkTransportSnapshot | null
  redundancy?: RedundancyStatus | null
  /** 仅子站：当前客户端数 */
  clients?: number
  /** 仅子站：快照取自哪条连接 */
  client_id?: string
}

// ── 操作审计（WP4a，契约 §2.4d）───────────────────────────────────────

export type AuditResult = 'ok' | 'fail'

/** 单条审计记录：hash = SHA256(prev_hash ‖ canonical_json) */
export interface AuditRecord {
  id: number
  ts: number
  operator: string
  role: string
  source_ip: string
  action: string
  target: string
  result: AuditResult
  reason: string
  tx_frame: string
  rx_frame: string
  prev_hash: string
  hash: string
}

export interface AuditStats {
  total: number
  operators: number
  fails: number
  last_ts: number | null
}

export interface AuditRecordsResponse {
  ok: boolean
  records: AuditRecord[]
  stats: AuditStats
}

export interface AuditVerifyResponse {
  ok: boolean
  valid: boolean
  total: number
  broken_at: number | null
  reason: string
}

export interface AuditUser {
  name: string
  role: string
}

export interface AuditUsersResponse {
  ok: boolean
  users: AuditUser[]
}

// ── 工程配置方案（WP5，契约 §2.4f）────────────────────────────────────

export interface ProfileSummary {
  mode: string
  host: string
  port: number | null
  common_addr: number | null
  ca_length: number | null
  ioa_length: number | null
  cot_length: number | null
  point_table: string
  note: string
  timers: Record<string, number | null>
  flow_control: Record<string, number | null>
}

export interface ProfileInfo {
  name: string
  updated_at: number
  size: number
  summary: ProfileSummary
}

export interface ProfilesResponse {
  ok: boolean
  profiles: ProfileInfo[]
  active: string
}

/** 方案内容（后端不限制具体节，按 AppConfig 子集透传） */
export type ProfileConfig = Record<string, unknown>

export interface ProfileDetailResponse {
  ok: boolean
  name: string
  config: ProfileConfig
  summary: ProfileSummary
}

export interface ProfileSaveResponse {
  ok: boolean
  name: string
  path: string
}

export interface ProfileApplyResponse {
  ok: boolean
  name: string
  applied: string[]
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


// ── 报文录制/回放（E2）─────────────────────────────────────────────────

export interface CaptureFileInfo {
  name: string
  size: number
  mtime: number
}

export interface CaptureFrame {
  timestamp: number
  absolute_time: number
  direction: string
  frame_type: string
  length: number
  hex: string
  metadata: Record<string, unknown>
}

export interface CapturePlayback {
  loaded: boolean
  file?: string
  state?: string
  index?: number
  total?: number
  progress?: number
  duration?: number
  current?: CaptureFrame | null
}

export interface CaptureDiffEntry {
  signature: string
  count_a: number
  count_b: number
  delta: number
}

/** 两段录制对比（T96，契约 §2.14） */
export interface CaptureDiffResponse {
  ok: boolean
  identical: boolean
  total_a: number
  total_b: number
  unique_a: number
  unique_b: number
  diff_total: number
  entries: CaptureDiffEntry[]
  truncated: boolean
  file_a?: string
  file_b?: string
  error?: string
}

export interface CaptureActionResult extends OkResponse {
  recording?: boolean
  paused?: boolean
  frames?: number
  rx?: number
  tx?: number
  dropped?: number
  elapsed?: number
  file?: string | null
}

export interface CaptureStatus {
  ok: boolean
  recording: boolean
  paused: boolean
  frames: number
  rx: number
  tx: number
  dropped: number
  elapsed: number
  file: string | null
  files: CaptureFileInfo[]
  playback: CapturePlayback
}

export interface CaptureFramesResponse {
  ok: boolean
  total: number
  offset: number
  rows: CaptureFrame[]
}


// ── 自动化测试中心（E1）───────────────────────────────────────────────

export interface TestScriptInfo {
  id: string
  name: string
  description: string
  role: string
  steps: number
  tags?: string[]
  timeout?: number
  error?: string
}

export interface TestReportInfo {
  name: string
  format: string
  size: number
}

export interface TestRun {
  id: string
  status: 'running' | 'passed' | 'failed' | 'stopped' | 'error'
  scripts: string[]
  started_at: number
  ended_at: number | null
  returncode: number | null
  summary: { scripts: number; passed: number; failed: number } | null
  lines: string[]
  results: { script: string; returncode: number }[]
  reports: TestReportInfo[]
}

export interface TestStatusResponse {
  ok: boolean
  running: boolean
  run: TestRun | null
}

// ── 对点 / 传动验收（WP2）────────────────────────────────────────────
export type CommissionVerdict = 'pending' | 'pass' | 'fail' | 'manual'
export type CommissionStatus = 'idle' | 'running' | 'done' | 'stopped'

export interface CommissionItem {
  ioa: number
  name: string
  kind: 'YX' | 'YC' | 'YK' | 'STEP'
  group: number
  command_ioa?: number | null
  expected?: number | boolean | string | null
  tolerance: number
  actual?: number | boolean | string | null
  quality: string
  verdict: CommissionVerdict
  note: string
  operator: string
  checked_at: number
  tx_frame: string
  rx_frame: string
  tx_time: number
  rx_time: number
  reason: string
}

export interface CommissionSummary {
  total: number
  pending: number
  pass: number
  fail: number
  manual: number
  done: number
}

export interface CommissionSession {
  id: string
  name: string
  created_at: number
  operator: string
  status: CommissionStatus
  started_at: number
  finished_at: number
  cursor: number
  note: string
  summary: CommissionSummary
  point_count: number
  items: CommissionItem[]
}

export interface CommissionSessionSummary {
  id: string
  name: string
  created_at: number
  operator: string
  status: CommissionStatus
  started_at: number
  finished_at: number
  cursor: number
  note: string
  summary: CommissionSummary
  point_count: number
}

export interface CommissionStatusResponse {
  ok: boolean
  running: boolean
  session_id: string | null
  cursor: number
  total: number
}

export interface CommissionSessionsResponse {
  ok: boolean
  sessions: CommissionSessionSummary[]
  status: CommissionStatusResponse
}

export interface CommissionSessionResponse {
  ok: boolean
  session: CommissionSession
}

export interface CommissionItemResponse {
  ok: boolean
  item: CommissionItem
}

export interface CommissionCreateRequest {
  name?: string
  operator?: string
  ioas?: number[]
  expected?: Record<string, number | boolean | string>
  command_ioas?: Record<string, number>
}

export interface CommissionVerdictRequest {
  ioa: number
  verdict: CommissionVerdict
  note?: string
  operator?: string
}
