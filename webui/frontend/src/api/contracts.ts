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
  CaptureActionResult,
  CaptureFileInfo,
  CaptureFrame,
  CaptureFramesResponse,
  CapturePlayback,
  CaptureStatus,
  EngineEvent,
  Frame,
  FrameDecodeResponse,
  FrameSegment,
  FrameTranslation,
  HistoryDataRecord,
  HistoryFrameRecord,
  HistoryRowsResponse,
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

const roleSchema = enumOf('master', 'slave')

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
  schemaVersion: optional(num()),
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
})

export const pointsResponseSchema = obj({ points: arr(pointSchema) })

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
export const frameDecodeSchema = refined(
  obj({
    ok: bool(),
    error: optional(str()),
    format: optional(enumOf('I', 'S', 'U', '?')),
    segments: optional(arr(frameSegmentSchema)),
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

// ── 编译期契约检查（导出以避免 noUnusedLocals；不参与运行时）───────────
export type ContractKeyChecks = [
  Assert<Equal<SchemaKeys<typeof okSchema>, keyof OkResponse>>,
  Assert<Equal<SchemaKeys<typeof statusSchema>, keyof Status>>,
  Assert<Equal<SchemaKeys<typeof redundancyStatusSchema>, keyof RedundancyStatus>>,
  Assert<Equal<SchemaKeys<typeof pointSchema>, keyof Point>>,
  Assert<Equal<SchemaKeys<typeof pointsResponseSchema>, keyof PointsResponse>>,
  Assert<Equal<SchemaKeys<typeof frameSchema>, keyof Frame>>,
  Assert<Equal<SchemaKeys<typeof engineEventSchema>, keyof EngineEvent>>,
  Assert<Equal<SchemaKeys<typeof recentResponseSchema>, keyof RecentResponse>>,
  Assert<Equal<SchemaKeys<typeof frameSegmentSchema>, keyof FrameSegment>>,
  Assert<Equal<SchemaKeys<typeof frameTranslationSchema>, keyof FrameTranslation>>,
  Assert<Equal<SchemaKeys<typeof frameDecodeSchema>, keyof FrameDecodeResponse>>,
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
  Assert<Equal<SchemaKeys<typeof captureStatusSchema>, keyof CaptureStatus>>,
  Assert<Equal<SchemaKeys<typeof captureFramesResponseSchema>, keyof CaptureFramesResponse>>,
  Assert<Equal<SchemaKeys<typeof testScriptInfoSchema>, keyof TestScriptInfo>>,
  Assert<Equal<SchemaKeys<typeof testRunSchema>, keyof TestRun>>,
  Assert<Equal<SchemaKeys<typeof testStatusResponseSchema>, keyof TestStatusResponse>>,
]
