/**
 * 全部 REST 端点（T11/T08/T09/T16 + 历史查询页）——与 `webui/api_contract.md` §2 一一对应
 * （50 个 /api/* 端点，含 /api/schema）。
 * 端点集合由 `webui/contract_check.py` 与 `src/api/endpoints.test.ts` 双向自检，防止契约漂移。
 *
 * 每个 JSON 响应都必须传入 `contracts.ts` 的 schema：`apiGet/apiPost` 会**运行时校验**
 * 真实响应，返回类型也由 schema 推断——新增端点漏挂 schema 会直接 `tsc` 报错。
 */

import { apiDelete, apiGet, apiGetText, apiPost, apiPostBytes, apiPostText, apiUrl } from './client'
import {
  authProbeResponseSchema,
  auditRecordsResponseSchema,
  profileApplyResponseSchema,
  profileDetailResponseSchema,
  profileSaveResponseSchema,
  pointDeleteResponseSchema,
  pointUpsertResponseSchema,
  profilesResponseSchema,
  sniffStatusSchema,
  auditUsersResponseSchema,
  auditVerifyResponseSchema,
  commissionItemResponseSchema,
  commissionSessionResponseSchema,
  commissionSessionsResponseSchema,
  commissionStatusResponseSchema,
  captureActionResultSchema,
  captureExportResponseSchema,
  captureFilesResponseSchema,
  captureFramesResponseSchema,
  captureLoadResponseSchema,
  capturePlaybackActionSchema,
  captureDiffSchema,
  captureStatusSchema,
  alarmsHistorySchema,
  alarmsSnapshotSchema,
  designBaselineSchema,
  designDiffSchema,
  doctorResponseSchema,
  frameDecodeSchema,
  historyDataRecordSchema,
  historyFrameRecordSchema,
  historyRowsSchema,
  historyStatsResponseSchema,
  logsResponseSchema,
  looseOkSchema,
  multiStartResponseSchema,
  multiStatusResponseSchema,
  multiSummaryResponseSchema,
  okSchema,
  paramStateResponseSchema,
  paramsResponseSchema,
  pointsResponseSchema,
  recentResponseSchema,
  scdPreviewSchema,
  schemaResponseSchema,
  sessionExportSchema,
  simulationSetResponseSchema,
  simulationStatusResponseSchema,
  statusSchema,
  testRunActionSchema,
  testScriptsResponseSchema,
  testStatusResponseSchema,
  timelineActionSchema,
  timelineStateSchema,
  xlsxImportSchema,
  xlsxPreviewSchema,
} from './contracts'
import type {
  BatchPointsRequest,
  BitstringRequest,
  CommissionCreateRequest,
  CommissionVerdictRequest,
  DelayRequest,
  EpRequest,
  FileRequest,
  GiRequest,
  HistoryDataParams,
  HistoryFramesParams,
  ImportFormat,
  LogQueryParams,
  DoctorRequest,
  MasterStartRequest,
  MultiStartRequest,
  ParamRequest,
  PointUpsertRequest,
  PsRequest,
  ReadRequest,
  ResponseBehavior,
  SetpointRequest,
  SimRequest,
  SimulationRequest,
  SlaveStartRequest,
  SlaveStepRequest,
  StepRequest,
  YcRequest,
  YkRequest,
  YmRequest,
  YxRequest,
} from './types'

export const LOGS_EXPORT_URL = '/api/logs/export'
export const POINTS_CSV_URL = '/api/export/points.csv'
/** xlsx 点表导出（T95）：浏览器直下 <a href download> */
export const POINTS_XLSX_URL = '/api/points/xlsx'
export const DIAGNOSTICS_EXPORT_URL = '/api/diagnostics/export'
export const HISTORY_EXPORT_URL = '/api/history/export'
export const CAPTURE_FILES_URL = '/api/capture/files'
export const CAPTURE_DOWNLOAD_PATH = '/api/capture/download/{name}'
export const TEST_REPORT_PATH = '/api/tests/reports/{run_id}/{name}'
/** 对点/传动验收记录导出（WP2）：xlsx / json / html 三种格式 */
export const COMMISSION_EXPORT_PATH = '/api/commission/sessions/{id}/export'
export const COMMISSION_GET_PATH = '/api/commission/sessions/{id}'
export const COMMISSION_RUN_PATH = '/api/commission/sessions/{id}/run'
export const COMMISSION_STOP_PATH = '/api/commission/sessions/{id}/stop'
export const COMMISSION_VERDICT_PATH = '/api/commission/sessions/{id}/verdict'
/** 路径模板（供文档驱动端点自检定位字面量；实际调用用已编码的 id 替换） */
const commissionPath = (template: string, id: string) =>
  template.replace('{id}', encodeURIComponent(id))
export const commissionExportUrl = (id: string, format: 'xlsx' | 'json' | 'html') =>
  apiUrl(`${commissionPath(COMMISSION_EXPORT_PATH, id)}?format=${format}`)
export const PROFILES_PATH = '/api/profiles'
export const PROFILE_GET_PATH = '/api/profiles/{name}'
export const PROFILE_APPLY_PATH = '/api/profiles/{name}/apply'
export const PROFILE_EXPORT_PATH = '/api/profiles/{name}/export'
export const PROFILE_RESTORE_PATH = '/api/profiles/restore'
export const PROFILE_IMPORT_PATH = '/api/profiles/import'
const profilePath = (template: string, name: string) =>
  template.replace('{name}', encodeURIComponent(name))
/** 方案 YAML 下载（WP5） */
export const profileExportUrl = (name: string) =>
  apiUrl(profilePath(PROFILE_EXPORT_PATH, name))
export const REPORT_EXPORT_PATH = '/api/export/report'
/** 多格式报告下载（WP8）：html | xlsx | pdf（含逐点证据 + 审计流水） */
export const reportDownloadUrl = (format: 'html' | 'xlsx' | 'pdf', title?: string) => {
  const q = new URLSearchParams({ format })
  if (title) q.set('title', title)
  return apiUrl(`${REPORT_EXPORT_PATH}?${q.toString()}`)
}
/** 操作审计导出（WP4a）：json / csv */
export const auditExportUrl = (format: 'json' | 'csv') =>
  apiUrl(`/api/audit/export?format=${format}`)
export const captureDownloadUrl = (name: string) =>
  apiUrl(CAPTURE_DOWNLOAD_PATH.replace('{name}', encodeURIComponent(name)))
export const testReportUrl = (runId: string, name: string) =>
  apiUrl(
    TEST_REPORT_PATH
      .replace('{run_id}', encodeURIComponent(runId))
      .replace('{name}', encodeURIComponent(name)),
  )
export const exportReportUrl = (
  title: string,
  opts?: { conclusion?: string; conclusion_kind?: string },
): string => {
  const q = new URLSearchParams({ title })
  if (opts?.conclusion) q.set('conclusion', opts.conclusion)
  if (opts?.conclusion_kind) q.set('conclusion_kind', opts.conclusion_kind)
  return `/api/export/report.html?${q.toString()}`
}

function logsQuery(params: LogQueryParams): Record<string, string | number | undefined> {
  return {
    level_min: params.level_min,
    category: params.category,
    source: params.source,
    q: params.q,
    limit: params.limit,
  }
}

function historyQuery(
  params: HistoryDataParams & HistoryFramesParams,
): Record<string, string | number | undefined> {
  return {
    point_type: params.point_type,
    ioa: params.ioa,
    direction: params.direction,
    start: params.start,
    end: params.end,
    limit: params.limit,
  }
}

export const api = {
  // ── 状态与点表 ───────────────────────────────────────────────────────
  schema: () => apiGet('/api/schema', schemaResponseSchema),
  /** 认证探测（公开；契约 §2.13）：token 显式传入时用 query 携带 */
  auth: (token?: string) =>
    apiGet('/api/auth', authProbeResponseSchema, token ? { token } : undefined),
  status: () => apiGet('/api/status', statusSchema),
  points: () => apiGet('/api/points', pointsResponseSchema),
  recent: () => apiGet('/api/recent', recentResponseSchema),
  /** 单帧逐段翻译（契约 §2.9，第二批体验改造 ④） */
  framesDecode: (hex: string) =>
    apiGet('/api/frames/decode', frameDecodeSchema, { hex }),

  // ── 主站命令 ─────────────────────────────────────────────────────────
  master: {
    start: (body: MasterStartRequest = {}) =>
      apiPost('/api/master/start', okSchema, body),
    stop: () => apiPost('/api/master/stop', okSchema),
    gi: (body: GiRequest = {}) => apiPost('/api/master/gi', okSchema, body),
    clock: () => apiPost('/api/master/clock', okSchema),
    clockOffset: (samples: number) =>
      apiPost('/api/master/clock_offset', looseOkSchema, { samples }),
    /** 连接医生（T94）：分层自检（TCP → STARTDT → 数据流），结论随报告附存（契约 §2.14a） */
    doctor: (body: DoctorRequest) => apiPost('/api/master/doctor', doctorResponseSchema, body),
    ci: () => apiPost('/api/master/ci', okSchema),
    reset: () => apiPost('/api/master/reset', okSchema),
    test: () => apiPost('/api/master/test', okSchema),
    read: (body: ReadRequest) => apiPost('/api/master/read', okSchema, body),
    yk: (body: YkRequest) => apiPost('/api/master/yk', okSchema, body),
    setpoint: (body: SetpointRequest) =>
      apiPost('/api/master/setpoint', okSchema, body),
    step: (body: StepRequest) => apiPost('/api/master/step', okSchema, body),
    bitstring: (body: BitstringRequest) =>
      apiPost('/api/master/bitstring', okSchema, body),
    delay: (body: DelayRequest) => apiPost('/api/master/delay', okSchema, body),
    param: (body: ParamRequest) => apiPost('/api/master/param', okSchema, body),
    file: (body: FileRequest) => apiPost('/api/master/file', okSchema, body),
    // T08 参数状态查询（契约 §2.6）
    paramState: (ioa: number) =>
      apiGet('/api/master/param_state', paramStateResponseSchema, { ioa }),
    params: () => apiGet('/api/master/params', paramsResponseSchema),
  },

  // ── 值守告警（T93）：2s 轮询（WS 契约不变）────────────────────
  alarms: () => apiGet('/api/alarms', alarmsSnapshotSchema),
  alarmsHistory: () => apiGet('/api/alarms/history', alarmsHistorySchema),
  alarmsAck: (id: number) => apiPost('/api/alarms/ack', okSchema, { id }),
  alarmsConfig: (body: Record<string, unknown>) =>
    apiPost('/api/alarms/config', alarmsSnapshotSchema, body),

  // ── 子站命令 ─────────────────────────────────────────────────────────
  slave: {
    start: (body: SlaveStartRequest = {}) =>
      apiPost('/api/slave/start', okSchema, body),
    stop: () => apiPost('/api/slave/stop', okSchema),
    yx: (body: YxRequest) => apiPost('/api/slave/yx', okSchema, body),
    yc: (body: YcRequest) => apiPost('/api/slave/yc', okSchema, body),
    ym: (body: YmRequest) => apiPost('/api/slave/ym', okSchema, body),
    ep: (body: EpRequest) => apiPost('/api/slave/ep', okSchema, body),
    ps: (body: PsRequest) => apiPost('/api/slave/ps', okSchema, body),
    response: (body: ResponseBehavior) =>
      apiPost('/api/slave/response', okSchema, body),
    sim: (body: SimRequest) => apiPost('/api/slave/sim', okSchema, body),
    // T09 步位置（契约 §2.7）
    step: (body: SlaveStepRequest) => apiPost('/api/slave/step', okSchema, body),
  },

  // ── 多站（T16，契约 §2.8）────────────────────────────────────────────
  multi: {
    start: (body: MultiStartRequest) => apiPost('/api/multi/start', multiStartResponseSchema, body),
    stop: () => apiPost('/api/multi/stop', okSchema),
    status: () => apiGet('/api/multi/status', multiStatusResponseSchema),
    summary: () => apiGet('/api/multi/summary', multiSummaryResponseSchema),
  },

  // ── 点表批量与导入导出 ───────────────────────────────────────────────
  batchPoints: (body: BatchPointsRequest) =>
    apiPost('/api/points/batch', looseOkSchema, body),
  pointsYaml: () => apiGetText('/api/points/yaml'),
  importPointsYaml: (text: string) =>
    apiPostText('/api/points/yaml', looseOkSchema, text),
  importPoints: (text: string, format: ImportFormat = 'auto') =>
    apiPostText(
      format === 'auto' ? '/api/points/import' : `/api/points/import?format=${format}`,
      looseOkSchema,
      text,
    ),
  /** Excel 点表预览（T95，无副作用解析） */
  pointsXlsxPreview: (data: ArrayBuffer) =>
    apiPostBytes('/api/points/xlsx/preview', xlsxPreviewSchema, data),
  /** Excel 点表导入（T95，整表替换 + 自动建立设计基准） */
  pointsXlsxImport: (data: ArrayBuffer) =>
    apiPostBytes('/api/points/xlsx/import', xlsxImportSchema, data),
  /** 设计基准管理（T95）：set=把当前点表快照为基准，clear=清除 */
  pointsDesign: (action: 'set' | 'clear') =>
    apiPost('/api/points/design', designBaselineSchema, { action }),
  /** 设计 vs 实测差异清单（T95，缺/多/值域） */
  designDiff: () => apiGet('/api/points/design-diff', designDiffSchema),
  /** 注入时间线状态（T97） */
  timeline: () => apiGet('/api/bridge/timeline', timelineStateSchema),
  /** 保存时间线编排（T97，覆盖旧序列） */
  timelineSet: (steps: import('./types').TimelineStep[]) =>
    apiPost('/api/bridge/timeline', timelineActionSchema, { steps }),
  /** 运行时间线（T97，异步启动；结果轮询 timeline()） */
  timelineRun: () => apiPost('/api/bridge/timeline/run', timelineActionSchema),
  timelineStop: () => apiPost('/api/bridge/timeline/stop', timelineActionSchema),
  /** SCD/CID/ICD → 104 点表预览（无副作用；返回的 YAML 可直接投 importPoints('yaml')） */
  scdPreview: (text: string, commonAddr?: number) =>
    apiPostText(
      commonAddr === undefined ? '/api/scd/preview' : `/api/scd/preview?common_addr=${commonAddr}`,
      scdPreviewSchema,
      text,
    ),
  exportPointsCsv: () => apiGetText(POINTS_CSV_URL),
  exportSession: () => apiGet('/api/export/session.json', sessionExportSchema),
  /** 报告导出（T87 可带曲线快照）——返回 HTML 文本，调用方用 Blob 打开 */
  exportReport: (body: Record<string, unknown>) =>
    apiPostText('/api/export/report.html', looseOkSchema, JSON.stringify(body)),

  // ── 透明桥（T74；仅 bridge 角色应用注册这两个端点）────────────────
  loadtest: {
    start: (body: { duration_s?: number; events_per_s?: number; connections?: number }) =>
      apiPost('/api/loadtest/start', looseOkSchema, body),
    stop: () => apiPost('/api/loadtest/stop', looseOkSchema),
    status: () => apiGet('/api/loadtest/status', looseOkSchema),
  },
  bridge: {
    start: (body: {
      listen_host?: string
      listen_port?: number
      upstream_host?: string
      upstream_port?: number
    }) => apiPost('/api/bridge/start', looseOkSchema, body),
    stop: () => apiPost('/api/bridge/stop', looseOkSchema),
    condition: (body: Record<string, unknown>) =>
      apiPost('/api/bridge/condition', looseOkSchema, body),
  },

  // ── 日志 ─────────────────────────────────────────────────────────────
  logs: (params: LogQueryParams = {}) =>
    apiGet('/api/logs', logsResponseSchema, logsQuery(params)),

  // ── 历史库查询（契约 §2.11）──────────────────────────────────────────
  history: {
    stats: () => apiGet('/api/history/stats', historyStatsResponseSchema),
    data: (params: HistoryDataParams = {}) =>
      apiGet('/api/history/data', historyRowsSchema(historyDataRecordSchema), historyQuery(params)),
    frames: (params: HistoryFramesParams = {}) =>
      apiGet('/api/history/frames', historyRowsSchema(historyFrameRecordSchema), historyQuery(params)),
  },

  // ── 网络异常模拟（契约 §2.12）────────────────────────────────────────
  simulation: {
    status: () => apiGet('/api/simulation', simulationStatusResponseSchema),
    set: (body: SimulationRequest) =>
      apiPost('/api/simulation', simulationSetResponseSchema, body),
    reset: () => apiPost('/api/simulation/reset', okSchema),
    disconnect: (duration: number) =>
      apiPost('/api/simulation/disconnect', okSchema, { duration }),
  },

  // ── 报文录制/回放（E2，契约 §2.14）──────────────────────────────────
  capture: {
    status: () => apiGet('/api/capture/status', captureStatusSchema),
    files: () => apiGet(CAPTURE_FILES_URL, captureFilesResponseSchema),
    start: (name?: string) =>
      apiPost('/api/capture/start', captureActionResultSchema, name ? { name } : {}),
    stop: () => apiPost('/api/capture/stop', captureActionResultSchema),
    pause: () => apiPost('/api/capture/pause', captureActionResultSchema),
    resume: () => apiPost('/api/capture/resume', captureActionResultSchema),
    export: (name: string, format: string) =>
      apiPost('/api/capture/export', captureExportResponseSchema, { name, format }),
    load: (name: string) =>
      apiPost('/api/capture/load', captureLoadResponseSchema, { name }),
    frames: (offset = 0, limit = 200) =>
      apiGet('/api/capture/frames', captureFramesResponseSchema, { offset, limit }),
    /** 两段录制对比（T96）：规格化签名多重集 diff */
    diff: (a: string, b: string, maxEntries?: number) =>
      apiPost('/api/capture/diff', captureDiffSchema,
        maxEntries ? { a, b, max_entries: maxEntries } : { a, b }),
    play: (speed: number) =>
      apiPost('/api/capture/play', capturePlaybackActionSchema, { speed }),
    stopPlayback: () =>
      apiPost('/api/capture/playback/stop', capturePlaybackActionSchema),
    pausePlayback: () =>
      apiPost('/api/capture/playback/pause', capturePlaybackActionSchema),
    step: (direction: 'forward' | 'backward') =>
      apiPost('/api/capture/step', capturePlaybackActionSchema, { direction }),
  },

  // ── 自动化测试中心（E1，契约 §2.15）────────────────────────────────
  tests: {
    scripts: () => apiGet('/api/tests/scripts', testScriptsResponseSchema),
    run: (scripts: string[]) => apiPost('/api/tests/run', testRunActionSchema, { scripts }),
    stop: () => apiPost('/api/tests/stop', okSchema),
    status: () => apiGet('/api/tests/status', testStatusResponseSchema),
    reportUrl: testReportUrl,
  },

  // ── 对点 / 传动验收（WP2，契约 §2.4c）────────────────────────────
  commission: {
    sessions: () => apiGet('/api/commission/sessions', commissionSessionsResponseSchema),
    create: (body: CommissionCreateRequest) =>
      apiPost('/api/commission/sessions', commissionSessionResponseSchema, body),
    get: (id: string) =>
      apiGet(commissionPath(COMMISSION_GET_PATH, id), commissionSessionResponseSchema),
    run: (id: string, operator = '') =>
      apiPost(commissionPath(COMMISSION_RUN_PATH, id),
        commissionStatusResponseSchema, { operator }),
    stop: (id: string) =>
      apiPost(commissionPath(COMMISSION_STOP_PATH, id), commissionStatusResponseSchema),
    verdict: (id: string, body: CommissionVerdictRequest) =>
      apiPost(commissionPath(COMMISSION_VERDICT_PATH, id),
        commissionItemResponseSchema, body),
    delete: (id: string) =>
      apiDelete(commissionPath(COMMISSION_GET_PATH, id), okSchema),
    exportUrl: commissionExportUrl,
  },

  // ── 操作审计（WP4a，契约 §2.4d）────────────────────────────────────
  audit: {
    records: (params?: {
      limit?: number
      operator?: string
      action?: string
      result?: string
      since?: number
    }) => {
      const q: Record<string, string | number | undefined> = {
        limit: params?.limit,
        operator: params?.operator || undefined,
        action: params?.action || undefined,
        result: params?.result || undefined,
        since: params?.since,
      }
      return apiGet('/api/audit/records', auditRecordsResponseSchema, q)
    },
    verify: () => apiGet('/api/audit/verify', auditVerifyResponseSchema),
    exportUrl: auditExportUrl,
    users: () => apiGet('/api/auth/users', auditUsersResponseSchema),
  },

  // ── 工程配置方案（WP5，契约 §2.4f）──────────────────────────────────
  profiles: {
    list: () => apiGet(PROFILES_PATH, profilesResponseSchema),
    get: (name: string) =>
      apiGet(profilePath(PROFILE_GET_PATH, name), profileDetailResponseSchema),
    save: (name: string, config?: Record<string, unknown>) =>
      apiPost(profilePath(PROFILE_GET_PATH, name), profileSaveResponseSchema,
        config ? { config } : {}),
    apply: (name: string) =>
      apiPost(profilePath(PROFILE_APPLY_PATH, name), profileApplyResponseSchema),
    restore: () => apiPost(PROFILE_RESTORE_PATH, profileApplyResponseSchema),
    remove: (name: string) => apiDelete(profilePath(PROFILE_GET_PATH, name), okSchema),
    importYaml: (name: string, text: string) =>
      apiPostText(`${PROFILE_IMPORT_PATH}?name=${encodeURIComponent(name)}`,
        profileSaveResponseSchema, text),
    exportUrl: profileExportUrl,
  },

  // ── 点表在线编辑（WP10a）──────────────────────────────────────────
  pointEdit: {
    upsert: (body: PointUpsertRequest) =>
      apiPost('/api/points/upsert', pointUpsertResponseSchema, body),
    remove: (ptype: string, ioa: number) =>
      apiDelete(`/api/points/delete?type=${encodeURIComponent(ptype)}&ioa=${ioa}`,
        pointDeleteResponseSchema),
  },

  // ── 旁路真实网卡抓包（WP9，契约 §2.14b）────────────────────────────
  sniff: {
    status: () => apiGet('/api/sniff/status', sniffStatusSchema),
    start: (body: { port?: number; iface?: string } = {}) =>
      apiPost('/api/sniff/start', looseOkSchema, body),
    stop: () => apiPost('/api/sniff/stop', looseOkSchema),
    exportUrl: (raw = false) =>
      apiUrl(`/api/sniff/export${raw ? '?raw=1' : ''}`),
  },
}
