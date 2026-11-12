// i18n-ignore-file — 本文件只有契约校验的诊断错误文案（console/ErrorBoundary），无 UI 文案
/**
 * REST 响应契约（单一真相）。
 *
 * 每个 schema 同时承担三件事：
 *  1. **运行时校验**：`apiGet/apiPost` 用它检查真实响应（`client.ts`）；
 *  2. **类型来源**：端点的返回类型由 schema 推断，不再手写泛型；
 *  3. **编译期防漂移**：文件末尾 `ContractKeyChecks` 把 schema 字段集与
 *     `types.ts` 里的响应接口逐项比对——接口多出/缺少字段会直接 `tsc` 失败。
 *
 * 2026-11-07 的悬停翻译缺陷（前端读 `r.translation`，后端实际返回
 * `{ok, format, segments}`）就是“接口手写、没人对拍真实响应”导致的；
 * 这里的键集校验 + `tests/e2e/specs/api-contract.spec.ts` 构成回归防线。
 *
 * 约定：
 *  - 必填 = 后端任何合法状态下都必须出现（缺失即契约破坏）；
 *  - 可选 = 状态相关或历史兼容字段；
 *  - 未知字段忽略（后端纯新增不破坏前端）。
 */

import {
  ApiContractError,
  arr,
  bool,
  dict,
  enumOf,
  literal,
  looseObj,
  nullable,
  num,
  obj,
  optional,
  refined,
  str,
  unionOf,
  unknown,
  type Schema,
} from './contract'
import type {
  AuthProbeResponse,
  FrameApciTree,
  FrameAsduTree,
  FrameObject,
  FrameTree,
  QualityBits,
  InterlockCondition,
  LinkSequenceSnapshot,
  LinkSnapshot,
  LinkStateSnapshot,
  LinkStateTransition,
  LinkTimerInfo,
  LinkTransportSnapshot,
  PointDeleteResponse,
  PointUpsertResponse,
  SniffCapability,
  SniffStats,
  SniffStatus,
  ProfileApplyResponse,
  ProfileInfo,
  ProfileSaveResponse,
  ProfileSummary,
  ProfilesResponse,
  AuditRecord,
  AuditRecordsResponse,
  AuditStats,
  AuditUser,
  AuditUsersResponse,
  AuditVerifyResponse,
  CaptureActionResult,
  CaptureDiffResponse,
  CaptureFileInfo,
  CaptureFrame,
  CaptureFramesResponse,
  CapturePlayback,
  CaptureStatus,
  CommissionItem,
  CommissionItemResponse,
  CommissionSession,
  CommissionSessionResponse,
  CommissionSessionSummary,
  CommissionSessionsResponse,
  CommissionStatusResponse,
  CommissionSummary,
  EngineEvent,
  Frame,
  Alarm,
  AlarmsHistory,
  AlarmsSnapshot,
  DoctorResponse,
  DoctorReport,
  DoctorStep,
  DesignBaselineResponse,
  DesignDiffResponse,
  TimelineAction,
  TimelineState,
  TimelineStep,
  FrameDecodeResponse,
  FrameSegment,
  FrameTranslation,
  HistoryDataRecord,
  HistoryFrameRecord,
  HistoryRowsResponse,
  ScdPreviewResponse,
  XlsxImportResponse,
  XlsxPreviewResponse,
  HistoryStats,
  HistoryStatsResponse,
  LogRow,
  LogsResponse,
  MultiStartResponse,
  MultiStatusResponse,
  MultiSummaryResponse,
  NetworkCondition,
  OkResponse,
  ParameterStateEntry,
  ParamStateResponse,
  ParamsResponse,
  Point,
  PointsResponse,
  RecentResponse,
  RedundancyStatus,
  SchemaResponse,
  SessionExport,
  SimulationStatusResponse,
  StationStatus,
  StationSummary,
  Status,
  TestRun,
  TestScriptInfo,
  TestStatusResponse,
} from './types'

// ── 编译期键集比对 ─────────────────────────────────────────────────────
type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
  ? true
  : false
type Assert<T extends true> = T
type SchemaKeys<S> = S extends Schema<infer T> ? keyof T : never

/** 通用命令响应：所有 POST 至少要有 `{ok, error?}`。 */
export const okSchema = obj({ ok: bool(), error: optional(str()) })
/** 开放命令响应（点表批量/导入等额外返回字段）。 */
export const looseOkSchema = looseObj({ ok: bool(), error: optional(str()) })

// ── 状态与点表 ─────────────────────────────────────────────────────────

const roleSchema = enumOf('master', 'slave', 'bridge')

const redundancyStatusSchema = obj({
  enabled: bool(),
  active: nullable(enumOf('primary', 'standby')),
  primary_connected: bool(),
  standby_connected: bool(),
  standby_host: str(),
  standby_port: num(),
  switch_timeout: num(),
  dedup_window: num(),
  failovers: num(),
})

// ── 点表在线编辑（WP10a）─────────────────────────────────────────────

export const pointUpsertResponseSchema = obj({
  ok: bool(),
  created: bool(),
  error: optional(str()),
  point: optional(obj({
    ioa: num(), type: str(), name: str(), group: num(), enabled: bool(),
  })),
})

export const pointDeleteResponseSchema = obj({
  ok: bool(),
  deleted: bool(),
  error: optional(str()),
})

// ── 旁路真实网卡抓包（WP9，契约 §2.14b）──────────────────────────────

export const sniffCapabilitySchema = obj({
  available: bool(),
  backend: str(),
  reason: str(),
  requires_root: bool(),
})

export const sniffStatsSchema = obj({
  packets: num(),
  apdus: num(),
  bytes: num(),
  dropped: num(),
  errors: num(),
  last_error: str(),
})

export const sniffStatusSchema = obj({
  ok: bool(),
  running: bool(),
  capability: sniffCapabilitySchema,
  stats: sniffStatsSchema,
  frames: num(),
  port: num(),
})

// ── 链路可观测（WP6，契约 §2.4g）────────────────────────────────────

export const linkTimerInfoSchema = obj({
  timeout: num(),
  active: bool(),
  elapsed: num(),
  remaining: num(),
})

export const linkStateTransitionSchema = obj({
  ts: num(),
  from: str(),
  to: str(),
})

export const linkStateSnapshotSchema = obj({
  state: str(),
  since_seconds: num(),
  timers: dict(linkTimerInfoSchema),
  history: arr(linkStateTransitionSchema),
})

export const linkSequenceSnapshotSchema = obj({
  k: num(),
  w: num(),
  send_seq: num(),
  recv_seq: num(),
  last_ack_rx: num(),
  unacked: num(),
  window_available: bool(),
  i_frame_count: num(),
})

export const linkTransportSnapshotSchema = obj({
  target: str(),
  connected: bool(),
  tls: bool(),
  reconnect_count: num(),
  max_reconnects: num(),
  reconnect_interval: num(),
  reconnect_in_seconds: nullable(num()),
  ever_connected: bool(),
  last_error: str(),
  last_error_at: num(),
})

export const linkSnapshotSchema = obj({
  role: roleSchema,
  state: nullable(linkStateSnapshotSchema),
  sequence: nullable(linkSequenceSnapshotSchema),
  transport: nullable(linkTransportSnapshotSchema),
  redundancy: optional(nullable(redundancyStatusSchema)),
  clients: optional(num()),
  client_id: optional(str()),
})

export const statusSchema = obj({
  role: roleSchema,
  started: optional(bool()),
  running: optional(bool()),
  state: optional(str()),
  host: optional(str()),
  port: optional(num()),
  addr: optional(num()),
  points: optional(num()),
  dropped: optional(num()),
  tx: optional(num()),
  rx: optional(num()),
  vs: optional(num()),
  vr: optional(num()),
  window: optional(str()),
  clients: optional(num()),
  client_list: optional(arr(str())),
  simulation: optional(bool()),
  simulation_yx: optional(bool()),
  simulation_yc: optional(bool()),
  redundancy: optional(redundancyStatusSchema),
  // WP6：链路可观测（后端只增键；无引擎时 state/sequence 为 null）
  link: optional(linkSnapshotSchema),
  // WP1：生效的 ASDU 地址字段字节数（后端只增键，旧消费者忽略）
  asdu_address: optional(obj({
    ca_length: num(),
    ioa_length: num(),
    cot_length: num(),
  })),
  schemaVersion: optional(num()),
  // 桥角色（T74）：running 时存在
  bridge_stats: optional(dict(num())),
  bridge_cfg: optional(obj({
    listen_host: optional(str()),
    listen_port: optional(num()),
    upstream_host: optional(str()),
    upstream_port: optional(num()),
  })),
  // 桥角色合规监视（T79）：running 时存在
  compliance: optional(obj({
    violation_total: optional(num()),
    counts: optional(dict(num())),
    frames_seen: optional(num()),
    violations: optional(arr(obj({
      ts: optional(num()),
      side: optional(str()),
      kind: optional(str()),
      detail: optional(str()),
    }))),
  })),

  // 桥角色网络条件注入（T85）
  injection: optional(dict(num())),
  condition: optional(str()),
  condition_active: optional(bool()),
})

export const interlockConditionSchema = obj({
  ioa: num(),
  value: bool(),
  label: optional(str()),
})

export const pointSchema = obj({
  ioa: num(),
  type: str(),
  name: str(),
  group: optional(unionOf(num(), str())),
  enabled: bool(),
  value: optional(nullable(unionOf(num(), bool(), str()))),
  quality: optional(str()),
  subtype: optional(str()),
  sbo: optional(bool()),
  unit: optional(str()),
  decimal_places: optional(num()),
  // T93：最后更新时间（毫秒 epoch，0=未收到过数据）+ YC 限值（值守告警用）
  ts: optional(num()),
  min_value: optional(num()),
  max_value: optional(num()),
  // WP4b：命令点的防误操作闭锁条件
  interlock: optional(arr(interlockConditionSchema)),
})

export const pointsResponseSchema = obj({ points: arr(pointSchema) })

/** SCD/CID/ICD（IEC 61850-6 SCL + 80-1 映射）预览响应（T72）：无副作用，返回可导入的点表 YAML。 */
export const scdPreviewSchema = obj({
  ok: bool(),
  yaml: str(),
  station_name: str(),
  common_addr: num(),
  stats: dict(num()),
  warnings: arr(str()),
})

// ── Excel 点表 + 设计基准比对（T95，契约 §2.4 / §4.14）─────────────────

export const xlsxPreviewSchema = obj({
  ok: bool(),
  stats: dict(num()),
  errors: arr(str()),
  rows: arr(obj({ ioa: num(), name: str() })),
  total: num(),
  error: optional(str()),
})

export const xlsxImportSchema = obj({
  ok: bool(),
  points: num(),
  errors: arr(str()),
  stats: dict(num()),
  design: bool(),
  error: optional(str()),
})

export const designBaselineSchema = obj({
  ok: bool(),
  has_design: bool(),
  points: optional(num()),
  error: optional(str()),
})

export const designMismatchSchema = obj({
  ioa: num(),
  design: obj({ type: str(), min_value: optional(num()), max_value: optional(num()) }),
  actual: obj({ type: str(), min_obs: optional(num()), max_obs: optional(num()) }),
  reason: str(),
})

// ── 桥注入时间线（T97，契约 §2.4a / §4.15）────────────────────────────

export const timelineStepSchema = obj({
  label: str(),
  duration_s: num(),
  condition: dict(unionOf(num(), str())),
  expect: enumOf('none', 'loss', 'k-exceed', 't1', 'disconnect'),
})

export const timelineStepResultSchema = obj({
  label: str(),
  expect: optional(str()),
  ok: optional(bool()),
  skipped: optional(bool()),
  condition: optional(str()),
  detail: str(),
  observed: optional(obj({
    dropped: num(),
    disconnects: num(),
    clients: num(),
    violations: arr(obj({ ts: num(), kind: str(), side: str(), detail: str() })),
  })),
  window_s: optional(num()),
})

export const timelineResultSchema = obj({
  ok: bool(),
  steps: arr(timelineStepResultSchema),
  started_at: num(),
  duration_s: num(),
  stopped: optional(bool()),
})

export const timelineStateSchema = obj({
  ok: bool(),
  running: bool(),
  steps: arr(timelineStepSchema),
  last_result: nullable(timelineResultSchema),
})

export const timelineActionSchema = obj({
  ok: bool(),
  error: optional(str()),
  running: optional(bool()),
  steps: optional(num()),
  stopping: optional(bool()),
})

export const designDiffSchema = obj({
  ok: bool(),
  has_design: bool(),
  summary: obj({ missing: num(), extra: num(), mismatch: num() }),
  missing: arr(obj({ ioa: num(), type: str(), name: str() })),
  extra: arr(obj({ ioa: num(), type: str(), name: str() })),
  mismatch: arr(designMismatchSchema),
  truncated: bool(),
  error: optional(str()),
})

export const frameSchema = obj({
  ts: optional(num()),
  direction: str(),
  len: num(),
  hex: str(),
  client: optional(str()),
})

export const engineEventSchema = obj({
  ts: optional(num()),
  type: str(),
  data: dict(unknown()),
})

export const recentResponseSchema = obj({
  frames: arr(unknown()),
  events: arr(unknown()),
})

export const frameSegmentSchema = obj({ title: str(), lines: arr(str()) })

export const frameTranslationSchema = obj({
  format: enumOf('I', 'S', 'U', '?'),
  segments: arr(frameSegmentSchema),
})

/** `GET /api/frames/decode`：扁平结构；ok=true 必须带 format + segments。 */
// ── 报文值域解码树（WP7，契约 §2.9）──────────────────────────────────

export const qualityBitsSchema = obj({
  iv: bool(), nt: bool(), sb: bool(), bl: bool(), ov: bool(),
})

export const frameObjectSchema = obj({
  index: num(),
  ioa: num(),
  sq_index: optional(num()),
  value_display: str(),
  value: nullable(unionOf(num(), bool(), str())),
  quality: str(),
  quality_bits: nullable(qualityBitsSchema),
  quality_raw: nullable(num()),
  timestamp: nullable(str()),
  raw_hex: nullable(str()),
})

export const frameApciTreeSchema = obj({
  length: num(),
  asdu_length: num(),
  frame_type: str(),
  tx_seq: nullable(num()),
  rx_seq: nullable(num()),
  u_func: nullable(num()),
  u_func_name: nullable(str()),
})

export const frameAsduTreeSchema = obj({
  type_id: num(),
  type_name: str(),
  sq: bool(),
  num: num(),
  cot: num(),
  cot_name: str(),
  pn: bool(),
  test: bool(),
  origin_addr: num(),
  common_addr: num(),
  object_count: num(),
})

export const frameTreeSchema = obj({
  ok: bool(),
  error: optional(str()),
  format: enumOf('I', 'S', 'U', '?'),
  apci: nullable(frameApciTreeSchema),
  asdu: nullable(frameAsduTreeSchema),
  objects: arr(frameObjectSchema),
})

export const frameDecodeSchema = refined(
  obj({
    ok: bool(),
    error: optional(str()),
    format: optional(enumOf('I', 'S', 'U', '?')),
    segments: optional(arr(frameSegmentSchema)),
    // WP7：结构化树（纯新增；可为 null——后端解析树失败时不影响 segments）
    tree: optional(nullable(frameTreeSchema)),
  }),
  (value, path) => {
    if (value.ok) {
      if (value.format === undefined) throw new ApiContractError(`${path}.format`, 'ok=true 时必填', undefined)
      if (value.segments === undefined) throw new ApiContractError(`${path}.segments`, 'ok=true 时必填', undefined)
    } else if (value.error === undefined) {
      throw new ApiContractError(`${path}.error`, 'ok=false 时必填', undefined)
    }
  },
)

export const schemaResponseSchema = obj({
  ok: literal(true),
  schemaVersion: num(),
  wsKinds: arr(str()),
  wsSchemaKey: str(),
  roles: optional(arr(roleSchema)),
  slaveApiPrefix: optional(str()),
})

const exportedFrameEnvelopeSchema = obj({
  kind: literal('frame'),
  schemaVersion: optional(num()),
  ts: optional(num()),
  data: frameSchema,
})

const exportedEventEnvelopeSchema = obj({
  kind: literal('event'),
  schemaVersion: optional(num()),
  ts: optional(num()),
  data: engineEventSchema,
})

export const sessionExportSchema = obj({
  role: roleSchema,
  status: statusSchema,
  frames: arr(exportedFrameEnvelopeSchema),
  events: arr(exportedEventEnvelopeSchema),
})

// ── 日志 ───────────────────────────────────────────────────────────────

export const logRowSchema = obj({
  ts: num(),
  level: str(),
  source: str(),
  category: str(),
  message: str(),
  data: optional(dict(unknown())),
})

/** LogStats 带索引签名，只锁定常用字段，未知统计项放行。 */
export const logStatsSchema = looseObj({
  total: optional(num()),
  by_level: optional(dict(num())),
  source: optional(str()),
})

export const logsResponseSchema = obj({
  ok: bool(),
  logs: arr(logRowSchema),
  stats: optional(logStatsSchema),
})

// ── 主站参数状态 ───────────────────────────────────────────────────────

const parameterResultSchema = enumOf('unknown', 'pending', 'ok', 'terminated', 'rejected', 'timeout')

export const parameterStateEntrySchema = obj({
  ioa: num(),
  loadResult: parameterResultSchema,
  loadCot: nullable(num()),
  loadUpdatedAt: nullable(num()),
  activationResult: parameterResultSchema,
  activationCot: nullable(num()),
  activationUpdatedAt: nullable(num()),
})

/** 未连接时后端返回 `{ok:false,error}`；ok=true 时 ioa/state 必填。 */
export const paramStateResponseSchema = refined(
  obj({
    ok: bool(),
    error: optional(str()),
    ioa: optional(num()),
    state: optional(nullable(parameterStateEntrySchema)),
  }),
  (value, path) => {
    if (value.ok && value.ioa === undefined) {
      throw new ApiContractError(`${path}.ioa`, 'ok=true 时必填', undefined)
    }
    if (value.ok && value.state === undefined) {
      throw new ApiContractError(`${path}.state`, 'ok=true 时必填（无状态为 null）', undefined)
    }
    if (!value.ok && value.error === undefined) {
      throw new ApiContractError(`${path}.error`, 'ok=false 时必填', undefined)
    }
  },
)

/** 未连接时后端返回 `{ok:false,error}`；ok=true 时 params 必填。 */
export const paramsResponseSchema = refined(
  obj({
    ok: bool(),
    error: optional(str()),
    params: optional(arr(parameterStateEntrySchema)),
  }),
  (value, path) => {
    if (value.ok && value.params === undefined) {
      throw new ApiContractError(`${path}.params`, 'ok=true 时必填', undefined)
    }
    if (!value.ok && value.error === undefined) {
      throw new ApiContractError(`${path}.error`, 'ok=false 时必填', undefined)
    }
  },
)

// ── 多站 ───────────────────────────────────────────────────────────────

export const stationStatusSchema = obj({
  station_id: str(),
  station_name: str(),
  port: num(),
  common_addr: num(),
  running: bool(),
  client_count: num(),
  yx_count: num(),
  yc_count: num(),
  yk_count: num(),
  ym_count: num(),
  simulation_active: bool(),
})

export const stationSummarySchema = obj({
  id: str(),
  name: str(),
  port: num(),
  clients: num(),
})

export const multiStartResponseSchema = obj({
  ok: bool(),
  stations: optional(num()),
  error: optional(str()),
})

export const multiStatusResponseSchema = obj({
  ok: bool(),
  running: bool(),
  stations: arr(stationStatusSchema),
})

export const multiSummaryResponseSchema = obj({
  ok: bool(),
  running: bool(),
  station_count: num(),
  total_clients: num(),
  uptime: num(),
  total_yx: optional(num()),
  total_yc: optional(num()),
  total_yk: optional(num()),
  total_ym: optional(num()),
  stations: arr(stationSummarySchema),
})

// ── 历史库查询 ─────────────────────────────────────────────────────────

export const historyDataRecordSchema = obj({
  id: num(),
  ts: num(),
  point_type: str(),
  ioa: num(),
  value: str(),
  quality: str(),
  source: str(),
})

export const historyFrameRecordSchema = obj({
  id: num(),
  ts: num(),
  direction: str(),
  frame_type: str(),
  hex: str(),
  parsed: str(),
  client: str(),
})

/** 未启用历史库时后端返回零值统计（与启用时同形状），字段均为必填。 */
export const historyStatsSchema = obj({
  data_records: num(),
  frame_records: num(),
  buffered_data: num(),
  buffered_frames: num(),
  oldest_data: num(),
  newest_data: num(),
  db_size_bytes: num(),
  dropped_records: num(),
})

export const historyRowsSchema = <T>(row: Schema<T>) =>
  obj({ ok: bool(), enabled: bool(), rows: arr(row) })

export const historyStatsResponseSchema = obj({
  ok: bool(),
  enabled: bool(),
  stats: historyStatsSchema,
})

// ── 网络异常模拟 ───────────────────────────────────────────────────────

export const networkConditionSchema = obj({
  delay_ms: num(),
  delay_variance_ms: num(),
  loss_rate: num(),
  duplicate_rate: num(),
  corrupt_rate: num(),
  corrupt_bits: num(),
  reorder_rate: num(),
  reorder_window: num(),
  disconnect_rate: num(),
  disconnect_duration_s: num(),
  bandwidth_bps: num(),
  direction: str(),
  active: bool(),
})

export const simulationStatusResponseSchema = obj({
  ok: bool(),
  enabled: bool(),
  installed: bool(),
  active: bool(),
  describe: str(),
  condition: networkConditionSchema,
  stats: dict(num()),
  presets: arr(str()),
})

export const simulationSetResponseSchema = obj({
  ok: bool(),
  error: optional(str()),
  status: optional(simulationStatusResponseSchema),
})

export const authProbeResponseSchema = obj({
  ok: bool(),
  required: bool(),
  valid: bool(),
  // WP4a 纯新增：旧消费方可忽略（schemaVersion 不递增）
  mode: optional(enumOf('none', 'token', 'users')),
  operator: optional(str()),
  role: optional(str()),
})

// ── 操作审计（WP4a，契约 §2.4d）───────────────────────────────────────

export const auditRecordSchema = obj({
  id: num(),
  ts: num(),
  operator: str(),
  role: str(),
  source_ip: str(),
  action: str(),
  target: str(),
  result: enumOf('ok', 'fail'),
  reason: str(),
  tx_frame: str(),
  rx_frame: str(),
  prev_hash: str(),
  hash: str(),
})

export const auditStatsSchema = obj({
  total: num(),
  operators: num(),
  fails: num(),
  last_ts: nullable(num()),
})

export const auditRecordsResponseSchema = obj({
  ok: bool(),
  records: arr(auditRecordSchema),
  stats: auditStatsSchema,
})

export const auditVerifyResponseSchema = obj({
  ok: bool(),
  valid: bool(),
  total: num(),
  broken_at: nullable(num()),
  reason: str(),
})

export const auditUserSchema = obj({
  name: str(),
  role: str(),
})

export const auditUsersResponseSchema = obj({
  ok: bool(),
  users: arr(auditUserSchema),
})

// ── 工程配置方案（WP5，契约 §2.4f）───────────────────────────────────

const numberMap = dict(nullable(num()))

export const profileSummarySchema = obj({
  mode: str(),
  host: str(),
  port: nullable(num()),
  common_addr: nullable(num()),
  ca_length: nullable(num()),
  ioa_length: nullable(num()),
  cot_length: nullable(num()),
  point_table: str(),
  note: str(),
  timers: numberMap,
  flow_control: numberMap,
})

export const profileInfoSchema = obj({
  name: str(),
  updated_at: num(),
  size: num(),
  summary: profileSummarySchema,
})

export const profilesResponseSchema = obj({
  ok: bool(),
  profiles: arr(profileInfoSchema),
  active: str(),
})

export const profileDetailResponseSchema = obj({
  ok: bool(),
  name: str(),
  config: unknown(),
  summary: profileSummarySchema,
})

export const profileSaveResponseSchema = obj({
  ok: bool(),
  name: str(),
  path: str(),
})

export const profileApplyResponseSchema = obj({
  ok: bool(),
  name: str(),
  applied: arr(str()),
})

// ── 报文录制/回放 ──────────────────────────────────────────────────────

export const captureFileInfoSchema = obj({
  name: str(),
  size: num(),
  mtime: num(),
})

export const captureFrameSchema = obj({
  timestamp: num(),
  absolute_time: num(),
  direction: str(),
  frame_type: str(),
  length: num(),
  hex: str(),
  metadata: dict(unknown()),
})

export const capturePlaybackSchema = obj({
  loaded: bool(),
  file: optional(str()),
  state: optional(str()),
  index: optional(num()),
  total: optional(num()),
  progress: optional(num()),
  duration: optional(num()),
  current: optional(nullable(captureFrameSchema)),
})

export const captureActionResultSchema = obj({
  ok: bool(),
  error: optional(str()),
  recording: optional(bool()),
  paused: optional(bool()),
  frames: optional(num()),
  rx: optional(num()),
  tx: optional(num()),
  dropped: optional(num()),
  elapsed: optional(num()),
  file: optional(nullable(str())),
})

/** 两段录制对比（T96，契约 §2.14）：规格化签名多重集 diff */
export const captureDiffSchema = obj({
  ok: bool(),
  identical: bool(),
  total_a: num(),
  total_b: num(),
  unique_a: num(),
  unique_b: num(),
  diff_total: num(),
  entries: arr(obj({
    signature: str(),
    count_a: num(),
    count_b: num(),
    delta: num(),
  })),
  truncated: bool(),
  file_a: optional(str()),
  file_b: optional(str()),
  error: optional(str()),
})

export const captureStatusSchema = obj({
  ok: bool(),
  recording: bool(),
  paused: bool(),
  frames: num(),
  rx: num(),
  tx: num(),
  dropped: num(),
  elapsed: num(),
  file: nullable(str()),
  files: arr(captureFileInfoSchema),
  playback: capturePlaybackSchema,
})

export const captureFramesResponseSchema = obj({
  ok: bool(),
  total: num(),
  offset: num(),
  rows: arr(captureFrameSchema),
})

export const captureFilesResponseSchema = obj({ ok: bool(), files: arr(captureFileInfoSchema) })

export const captureExportResponseSchema = obj({
  ok: bool(),
  error: optional(str()),
  file: str(),
  frames: num(),
})

export const captureLoadResponseSchema = obj({
  ok: bool(),
  error: optional(str()),
  file: str(),
  frames: num(),
  loaded: bool(),
  state: optional(str()),
  index: optional(num()),
  total: optional(num()),
  progress: optional(num()),
  duration: optional(num()),
  current: optional(nullable(captureFrameSchema)),
})

export const capturePlaybackActionSchema = obj({
  ok: bool(),
  error: optional(str()),
  loaded: bool(),
  file: optional(str()),
  state: optional(str()),
  index: optional(num()),
  total: optional(num()),
  progress: optional(num()),
  duration: optional(num()),
  current: optional(nullable(captureFrameSchema)),
})

// ── 自动化测试中心 ─────────────────────────────────────────────────────

export const testScriptInfoSchema = obj({
  id: str(),
  name: str(),
  description: str(),
  role: str(),
  steps: num(),
  tags: optional(arr(str())),
  timeout: optional(num()),
  error: optional(str()),
})

export const testReportInfoSchema = obj({
  name: str(),
  format: str(),
  size: num(),
})

export const testRunSchema = obj({
  id: str(),
  status: enumOf('running', 'passed', 'failed', 'stopped', 'error'),
  scripts: arr(str()),
  started_at: num(),
  ended_at: nullable(num()),
  returncode: nullable(num()),
  summary: nullable(obj({ scripts: num(), passed: num(), failed: num() })),
  lines: arr(str()),
  results: arr(obj({ script: str(), returncode: num() })),
  reports: arr(testReportInfoSchema),
})

export const testStatusResponseSchema = obj({
  ok: bool(),
  running: bool(),
  run: nullable(testRunSchema),
})

export const testScriptsResponseSchema = obj({ ok: bool(), scripts: arr(testScriptInfoSchema) })

export const testRunActionSchema = obj({
  ok: bool(),
  error: optional(str()),
  run: optional(testRunSchema),
})

export const doctorStepSchema = obj({
  key: str(),
  ok: bool(),
  detail: str(),
  evidence: optional(dict(unknown())),
})

export const doctorReportSchema = obj({
  ok: bool(),
  conclusion: str(),
  duration_ms: num(),
  steps: arr(doctorStepSchema),
})

export const doctorResponseSchema = obj({
  ok: bool(),
  report: doctorReportSchema,
})

export const alarmSchema = obj({
  id: num(),
  kind: enumOf('limit', 'stale', 'jump', 'comm'),
  ioa: nullable(num()),
  message: str(),
  ts: num(),
  age_s: num(),
  acked: bool(),
  cleared: bool(),
})

export const alarmsSnapshotSchema = obj({
  ok: bool(),
  config: obj({
    stale_seconds: num(),
    comm_seconds: num(),
    jump_delta: nullable(num()),
    debounce: num(),
    sound: bool(),
  }),
  active: arr(alarmSchema),
  new_since_poll: num(),
  history_total: num(),
})

export const alarmsHistorySchema = obj({
  ok: bool(),
  history: arr(alarmSchema),
  total: num(),
})

// ── 编译期契约检查（导出以避免 noUnusedLocals；不参与运行时）───────────
// ── 对点 / 传动验收（WP2）─────────────────────────────────────────
const commissionItemSchema = obj({
  ioa: num(),
  name: str(),
  kind: enumOf('YX', 'YC', 'YK', 'STEP'),
  group: num(),
  command_ioa: optional(nullable(num())),
  expected: optional(nullable(unionOf(num(), bool(), str()))),
  tolerance: num(),
  actual: optional(nullable(unionOf(num(), bool(), str()))),
  quality: str(),
  verdict: enumOf('pending', 'pass', 'fail', 'manual'),
  note: str(),
  operator: str(),
  checked_at: num(),
  tx_frame: str(),
  rx_frame: str(),
  tx_time: num(),
  rx_time: num(),
  reason: str(),
})

const commissionSummarySchema = obj({
  total: num(),
  pending: num(),
  pass: num(),
  fail: num(),
  manual: num(),
  done: num(),
})

// obj() 不暴露 .shape，公共字段用显式 shape 常量复用
const commissionSessionBaseShape = {
  id: str(),
  name: str(),
  created_at: num(),
  operator: str(),
  status: enumOf('idle', 'running', 'done', 'stopped'),
  started_at: num(),
  finished_at: num(),
  cursor: num(),
  note: str(),
  summary: commissionSummarySchema,
  point_count: num(),
}

export const commissionSessionSummarySchema = obj(commissionSessionBaseShape)

export const commissionSessionSchema = obj({
  ...commissionSessionBaseShape,
  items: arr(commissionItemSchema),
})

export const commissionStatusResponseSchema = obj({
  ok: bool(),
  running: bool(),
  session_id: nullable(str()),
  cursor: num(),
  total: num(),
})

export const commissionSessionsResponseSchema = obj({
  ok: bool(),
  sessions: arr(commissionSessionSummarySchema),
  status: commissionStatusResponseSchema,
})

export const commissionSessionResponseSchema = obj({
  ok: bool(),
  session: commissionSessionSchema,
})

export const commissionItemResponseSchema = obj({
  ok: bool(),
  item: commissionItemSchema,
})

export type ContractKeyChecks = [
  Assert<Equal<SchemaKeys<typeof okSchema>, keyof OkResponse>>,
  Assert<Equal<SchemaKeys<typeof statusSchema>, keyof Status>>,
  Assert<Equal<SchemaKeys<typeof redundancyStatusSchema>, keyof RedundancyStatus>>,
  Assert<Equal<SchemaKeys<typeof pointSchema>, keyof Point>>,
  Assert<Equal<SchemaKeys<typeof interlockConditionSchema>, keyof InterlockCondition>>,
  Assert<Equal<SchemaKeys<typeof pointsResponseSchema>, keyof PointsResponse>>,
  Assert<Equal<SchemaKeys<typeof scdPreviewSchema>, keyof ScdPreviewResponse>>,
  Assert<Equal<SchemaKeys<typeof xlsxPreviewSchema>, keyof XlsxPreviewResponse>>,
  Assert<Equal<SchemaKeys<typeof xlsxImportSchema>, keyof XlsxImportResponse>>,
  Assert<Equal<SchemaKeys<typeof designBaselineSchema>, keyof DesignBaselineResponse>>,
  Assert<Equal<SchemaKeys<typeof designDiffSchema>, keyof DesignDiffResponse>>,
  Assert<Equal<SchemaKeys<typeof timelineStepSchema>, keyof TimelineStep>>,
  Assert<Equal<SchemaKeys<typeof timelineStateSchema>, keyof TimelineState>>,
  Assert<Equal<SchemaKeys<typeof timelineActionSchema>, keyof TimelineAction>>,
  Assert<Equal<SchemaKeys<typeof frameSchema>, keyof Frame>>,
  Assert<Equal<SchemaKeys<typeof engineEventSchema>, keyof EngineEvent>>,
  Assert<Equal<SchemaKeys<typeof recentResponseSchema>, keyof RecentResponse>>,
  Assert<Equal<SchemaKeys<typeof frameSegmentSchema>, keyof FrameSegment>>,
  Assert<Equal<SchemaKeys<typeof frameTranslationSchema>, keyof FrameTranslation>>,
  Assert<Equal<SchemaKeys<typeof frameDecodeSchema>, keyof FrameDecodeResponse>>,
  Assert<Equal<SchemaKeys<typeof frameObjectSchema>, keyof FrameObject>>,
  Assert<Equal<SchemaKeys<typeof frameApciTreeSchema>, keyof FrameApciTree>>,
  Assert<Equal<SchemaKeys<typeof frameAsduTreeSchema>, keyof FrameAsduTree>>,
  Assert<Equal<SchemaKeys<typeof frameTreeSchema>, keyof FrameTree>>,
  Assert<Equal<SchemaKeys<typeof qualityBitsSchema>, keyof QualityBits>>,
  Assert<Equal<SchemaKeys<typeof doctorStepSchema>, keyof DoctorStep>>,
  Assert<Equal<SchemaKeys<typeof doctorReportSchema>, keyof DoctorReport>>,
  Assert<Equal<SchemaKeys<typeof doctorResponseSchema>, keyof DoctorResponse>>,
  Assert<Equal<SchemaKeys<typeof alarmSchema>, keyof Alarm>>,
  Assert<Equal<SchemaKeys<typeof alarmsSnapshotSchema>, keyof AlarmsSnapshot>>,
  Assert<Equal<SchemaKeys<typeof alarmsHistorySchema>, keyof AlarmsHistory>>,
  Assert<Equal<SchemaKeys<typeof schemaResponseSchema>, keyof SchemaResponse>>,
  Assert<Equal<SchemaKeys<typeof sessionExportSchema>, keyof SessionExport>>,
  Assert<Equal<SchemaKeys<typeof logRowSchema>, keyof LogRow>>,
  Assert<Equal<SchemaKeys<typeof logsResponseSchema>, keyof LogsResponse>>,
  Assert<Equal<SchemaKeys<typeof parameterStateEntrySchema>, keyof ParameterStateEntry>>,
  Assert<Equal<SchemaKeys<typeof paramStateResponseSchema>, keyof ParamStateResponse>>,
  Assert<Equal<SchemaKeys<typeof paramsResponseSchema>, keyof ParamsResponse>>,
  Assert<Equal<SchemaKeys<typeof multiStartResponseSchema>, keyof MultiStartResponse>>,
  Assert<Equal<SchemaKeys<typeof multiStatusResponseSchema>, keyof MultiStatusResponse>>,
  Assert<Equal<SchemaKeys<typeof multiSummaryResponseSchema>, keyof MultiSummaryResponse>>,
  Assert<Equal<SchemaKeys<typeof stationStatusSchema>, keyof StationStatus>>,
  Assert<Equal<SchemaKeys<typeof stationSummarySchema>, keyof StationSummary>>,
  Assert<Equal<SchemaKeys<typeof historyDataRecordSchema>, keyof HistoryDataRecord>>,
  Assert<Equal<SchemaKeys<typeof historyFrameRecordSchema>, keyof HistoryFrameRecord>>,
  Assert<Equal<SchemaKeys<typeof historyStatsSchema>, keyof HistoryStats>>,
  Assert<Equal<SchemaKeys<ReturnType<typeof historyRowsSchema<HistoryDataRecord>>>, keyof HistoryRowsResponse<HistoryDataRecord>>>,
  Assert<Equal<SchemaKeys<typeof historyStatsResponseSchema>, keyof HistoryStatsResponse>>,
  Assert<Equal<SchemaKeys<typeof networkConditionSchema>, keyof NetworkCondition>>,
  Assert<Equal<SchemaKeys<typeof simulationStatusResponseSchema>, keyof SimulationStatusResponse>>,
  Assert<Equal<SchemaKeys<typeof authProbeResponseSchema>, keyof AuthProbeResponse>>,
  Assert<Equal<SchemaKeys<typeof captureFileInfoSchema>, keyof CaptureFileInfo>>,
  Assert<Equal<SchemaKeys<typeof captureFrameSchema>, keyof CaptureFrame>>,
  Assert<Equal<SchemaKeys<typeof capturePlaybackSchema>, keyof CapturePlayback>>,
  Assert<Equal<SchemaKeys<typeof captureActionResultSchema>, keyof CaptureActionResult>>,
  Assert<Equal<SchemaKeys<typeof captureDiffSchema>, keyof CaptureDiffResponse>>,
  Assert<Equal<SchemaKeys<typeof captureStatusSchema>, keyof CaptureStatus>>,
  Assert<Equal<SchemaKeys<typeof captureFramesResponseSchema>, keyof CaptureFramesResponse>>,
  Assert<Equal<SchemaKeys<typeof testScriptInfoSchema>, keyof TestScriptInfo>>,
  Assert<Equal<SchemaKeys<typeof testRunSchema>, keyof TestRun>>,
  Assert<Equal<SchemaKeys<typeof testStatusResponseSchema>, keyof TestStatusResponse>>,
  Assert<Equal<SchemaKeys<typeof commissionItemSchema>, keyof CommissionItem>>,
  Assert<Equal<SchemaKeys<typeof commissionSummarySchema>, keyof CommissionSummary>>,
  Assert<Equal<SchemaKeys<typeof commissionSessionSummarySchema>, keyof CommissionSessionSummary>>,
  Assert<Equal<SchemaKeys<typeof commissionSessionSchema>, keyof CommissionSession>>,
  Assert<Equal<SchemaKeys<typeof commissionStatusResponseSchema>, keyof CommissionStatusResponse>>,
  Assert<Equal<SchemaKeys<typeof commissionSessionsResponseSchema>, keyof CommissionSessionsResponse>>,
  Assert<Equal<SchemaKeys<typeof commissionSessionResponseSchema>, keyof CommissionSessionResponse>>,
  Assert<Equal<SchemaKeys<typeof commissionItemResponseSchema>, keyof CommissionItemResponse>>,
  Assert<Equal<SchemaKeys<typeof auditRecordSchema>, keyof AuditRecord>>,
  Assert<Equal<SchemaKeys<typeof auditStatsSchema>, keyof AuditStats>>,
  Assert<Equal<SchemaKeys<typeof auditRecordsResponseSchema>, keyof AuditRecordsResponse>>,
  Assert<Equal<SchemaKeys<typeof auditVerifyResponseSchema>, keyof AuditVerifyResponse>>,
  Assert<Equal<SchemaKeys<typeof auditUserSchema>, keyof AuditUser>>,
  Assert<Equal<SchemaKeys<typeof auditUsersResponseSchema>, keyof AuditUsersResponse>>,
  Assert<Equal<SchemaKeys<typeof profileInfoSchema>, keyof ProfileInfo>>,
  Assert<Equal<SchemaKeys<typeof profileSummarySchema>, keyof ProfileSummary>>,
  Assert<Equal<SchemaKeys<typeof profilesResponseSchema>, keyof ProfilesResponse>>,
  Assert<Equal<SchemaKeys<typeof profileSaveResponseSchema>, keyof ProfileSaveResponse>>,
  Assert<Equal<SchemaKeys<typeof profileApplyResponseSchema>, keyof ProfileApplyResponse>>,
  Assert<Equal<SchemaKeys<typeof linkTimerInfoSchema>, keyof LinkTimerInfo>>,
  Assert<Equal<SchemaKeys<typeof linkStateTransitionSchema>, keyof LinkStateTransition>>,
  Assert<Equal<SchemaKeys<typeof linkStateSnapshotSchema>, keyof LinkStateSnapshot>>,
  Assert<Equal<SchemaKeys<typeof linkSequenceSnapshotSchema>, keyof LinkSequenceSnapshot>>,
  Assert<Equal<SchemaKeys<typeof linkTransportSnapshotSchema>, keyof LinkTransportSnapshot>>,
  Assert<Equal<SchemaKeys<typeof linkSnapshotSchema>, keyof LinkSnapshot>>,
  Assert<Equal<SchemaKeys<typeof sniffCapabilitySchema>, keyof SniffCapability>>,
  Assert<Equal<SchemaKeys<typeof sniffStatsSchema>, keyof SniffStats>>,
  Assert<Equal<SchemaKeys<typeof sniffStatusSchema>, keyof SniffStatus>>,
  Assert<Equal<SchemaKeys<typeof pointUpsertResponseSchema>, keyof PointUpsertResponse>>,
  Assert<Equal<SchemaKeys<typeof pointDeleteResponseSchema>, keyof PointDeleteResponse>>,
]
