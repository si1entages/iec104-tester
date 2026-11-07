/**
 * 全部 REST 端点（T11/T08/T09/T16 + 历史查询页）——与 `webui/api_contract.md` §2 一一对应
 * （50 个 /api/* 端点，含 /api/schema）。
 * 端点集合由 `webui/contract_check.py` 与 `src/api/endpoints.test.ts` 双向自检，防止契约漂移。
 */

import { apiGet, apiGetText, apiPost, apiPostText } from './client'
import type {
  AuthProbeResponse,
  BatchPointsRequest,
  BitstringRequest,
  CaptureActionResult,
  CaptureFramesResponse,
  CaptureStatus,
  CommandResponse,
  DelayRequest,
  EpRequest,
  FileRequest,
  FrameDecodeResponse,
  GiRequest,
  HistoryDataParams,
  HistoryDataRecord,
  HistoryFramesParams,
  HistoryFrameRecord,
  HistoryRowsResponse,
  HistoryStatsResponse,
  ImportFormat,
  LogQueryParams,
  LogsResponse,
  MasterStartRequest,
  MultiStartRequest,
  MultiStartResponse,
  MultiStatusResponse,
  MultiSummaryResponse,
  OkResponse,
  ParamRequest,
  ParamsResponse,
  ParamStateResponse,
  PointsResponse,
  PsRequest,
  ReadRequest,
  RecentResponse,
  ResponseBehavior,
  SchemaResponse,
  SetpointRequest,
  SimRequest,
  SimulationRequest,
  SimulationStatusResponse,
  SlaveStartRequest,
  SlaveStepRequest,
  SessionExport,
  Status,
  StepRequest,
  TestScriptInfo,
  TestStatusResponse,
  YcRequest,
  YkRequest,
  YmRequest,
  YxRequest,
} from './types'

export const LOGS_EXPORT_URL = '/api/logs/export'
export const POINTS_CSV_URL = '/api/export/points.csv'
export const DIAGNOSTICS_EXPORT_URL = '/api/diagnostics/export'
export const HISTORY_EXPORT_URL = '/api/history/export'
export const CAPTURE_FILES_URL = '/api/capture/files'
export const CAPTURE_DOWNLOAD_PATH = '/api/capture/download/{name}'
export const TEST_REPORT_PATH = '/api/tests/reports/{run_id}/{name}'
export const captureDownloadUrl = (name: string) =>
  CAPTURE_DOWNLOAD_PATH.replace('{name}', encodeURIComponent(name))
export const testReportUrl = (runId: string, name: string) =>
  TEST_REPORT_PATH
    .replace('{run_id}', encodeURIComponent(runId))
    .replace('{name}', encodeURIComponent(name))

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
  schema: () => apiGet<SchemaResponse>('/api/schema'),
  /** 认证探测（公开；契约 §2.13）：token 显式传入时用 query 携带 */
  auth: (token?: string) =>
    apiGet<AuthProbeResponse>('/api/auth', token ? { token } : undefined),
  status: () => apiGet<Status>('/api/status'),
  points: () => apiGet<PointsResponse>('/api/points'),
  recent: () => apiGet<RecentResponse>('/api/recent'),
  /** 单帧逐段翻译（契约 §2.9，第二批体验改造 ④） */
  framesDecode: (hex: string) =>
    apiGet<FrameDecodeResponse>('/api/frames/decode', { hex }),

  // ── 主站命令 ─────────────────────────────────────────────────────────
  master: {
    start: (body: MasterStartRequest = {}) =>
      apiPost<CommandResponse>('/api/master/start', body),
    stop: () => apiPost<CommandResponse>('/api/master/stop'),
    gi: (body: GiRequest = {}) => apiPost<CommandResponse>('/api/master/gi', body),
    clock: () => apiPost<CommandResponse>('/api/master/clock'),
    ci: () => apiPost<CommandResponse>('/api/master/ci'),
    reset: () => apiPost<CommandResponse>('/api/master/reset'),
    test: () => apiPost<CommandResponse>('/api/master/test'),
    read: (body: ReadRequest) => apiPost<CommandResponse>('/api/master/read', body),
    yk: (body: YkRequest) => apiPost<CommandResponse>('/api/master/yk', body),
    setpoint: (body: SetpointRequest) =>
      apiPost<CommandResponse>('/api/master/setpoint', body),
    step: (body: StepRequest) => apiPost<CommandResponse>('/api/master/step', body),
    bitstring: (body: BitstringRequest) =>
      apiPost<CommandResponse>('/api/master/bitstring', body),
    delay: (body: DelayRequest) => apiPost<CommandResponse>('/api/master/delay', body),
    param: (body: ParamRequest) => apiPost<CommandResponse>('/api/master/param', body),
    file: (body: FileRequest) => apiPost<CommandResponse>('/api/master/file', body),
    // T08 参数状态查询（契约 §2.6）
    paramState: (ioa: number) =>
      apiGet<ParamStateResponse>('/api/master/param_state', { ioa }),
    params: () => apiGet<ParamsResponse>('/api/master/params'),
  },

  // ── 子站命令 ─────────────────────────────────────────────────────────
  slave: {
    start: (body: SlaveStartRequest = {}) =>
      apiPost<CommandResponse>('/api/slave/start', body),
    stop: () => apiPost<CommandResponse>('/api/slave/stop'),
    yx: (body: YxRequest) => apiPost<CommandResponse>('/api/slave/yx', body),
    yc: (body: YcRequest) => apiPost<CommandResponse>('/api/slave/yc', body),
    ym: (body: YmRequest) => apiPost<CommandResponse>('/api/slave/ym', body),
    ep: (body: EpRequest) => apiPost<CommandResponse>('/api/slave/ep', body),
    ps: (body: PsRequest) => apiPost<CommandResponse>('/api/slave/ps', body),
    response: (body: ResponseBehavior) =>
      apiPost<CommandResponse>('/api/slave/response', body),
    sim: (body: SimRequest) => apiPost<CommandResponse>('/api/slave/sim', body),
    // T09 步位置（契约 §2.7）
    step: (body: SlaveStepRequest) => apiPost<CommandResponse>('/api/slave/step', body),
  },

  // ── 多站（T16，契约 §2.8）────────────────────────────────────────────
  multi: {
    start: (body: MultiStartRequest) => apiPost<MultiStartResponse>('/api/multi/start', body),
    stop: () => apiPost<CommandResponse>('/api/multi/stop'),
    status: () => apiGet<MultiStatusResponse>('/api/multi/status'),
    summary: () => apiGet<MultiSummaryResponse>('/api/multi/summary'),
  },

  // ── 点表批量与导入导出 ───────────────────────────────────────────────
  batchPoints: (body: BatchPointsRequest) =>
    apiPost<OkResponse & Record<string, unknown>>('/api/points/batch', body),
  pointsYaml: () => apiGetText('/api/points/yaml'),
  importPointsYaml: (text: string) =>
    apiPostText<OkResponse & Record<string, unknown>>('/api/points/yaml', text),
  importPoints: (text: string, format: ImportFormat = 'auto') =>
    apiPostText<OkResponse & Record<string, unknown>>(
      format === 'auto' ? '/api/points/import' : `/api/points/import?format=${format}`,
      text,
    ),
  exportPointsCsv: () => apiGetText(POINTS_CSV_URL),
  exportSession: () => apiGet<SessionExport>('/api/export/session.json'),

  // ── 日志 ─────────────────────────────────────────────────────────────
  logs: (params: LogQueryParams = {}) =>
    apiGet<LogsResponse>('/api/logs', logsQuery(params)),

  // ── 历史库查询（契约 §2.11）──────────────────────────────────────────
  history: {
    stats: () => apiGet<HistoryStatsResponse>('/api/history/stats'),
    data: (params: HistoryDataParams = {}) =>
      apiGet<HistoryRowsResponse<HistoryDataRecord>>('/api/history/data', historyQuery(params)),
    frames: (params: HistoryFramesParams = {}) =>
      apiGet<HistoryRowsResponse<HistoryFrameRecord>>('/api/history/frames', historyQuery(params)),
  },

  // ── 网络异常模拟（契约 §2.12）────────────────────────────────────────
  simulation: {
    status: () => apiGet<SimulationStatusResponse>('/api/simulation'),
    set: (body: SimulationRequest) =>
      apiPost<OkResponse & { status?: SimulationStatusResponse }>('/api/simulation', body),
    reset: () => apiPost<OkResponse>('/api/simulation/reset'),
    disconnect: (duration: number) =>
      apiPost<OkResponse>('/api/simulation/disconnect', { duration }),
  },

  // ── 报文录制/回放（E2，契约 §2.14）──────────────────────────────────
  capture: {
    status: () => apiGet<CaptureStatus>('/api/capture/status'),
    files: () => apiGet<{ ok: boolean; files: import('./types').CaptureFileInfo[] }>(CAPTURE_FILES_URL),
    start: (name?: string) =>
      apiPost<CaptureActionResult>('/api/capture/start', name ? { name } : {}),
    stop: () => apiPost<CaptureActionResult>('/api/capture/stop'),
    pause: () => apiPost<CaptureActionResult>('/api/capture/pause'),
    resume: () => apiPost<CaptureActionResult>('/api/capture/resume'),
    export: (name: string, format: string) =>
      apiPost<OkResponse & { file: string; frames: number }>('/api/capture/export', { name, format }),
    load: (name: string) =>
      apiPost<OkResponse & { file: string; frames: number } & CaptureStatus['playback']>(
        '/api/capture/load', { name }),
    frames: (offset = 0, limit = 200) =>
      apiGet<CaptureFramesResponse>('/api/capture/frames', { offset, limit }),
    play: (speed: number) =>
      apiPost<CaptureStatus['playback'] & OkResponse>('/api/capture/play', { speed }),
    stopPlayback: () => apiPost<CaptureStatus['playback'] & OkResponse>('/api/capture/playback/stop'),
    pausePlayback: () => apiPost<CaptureStatus['playback'] & OkResponse>('/api/capture/playback/pause'),
    step: (direction: 'forward' | 'backward') =>
      apiPost<CaptureStatus['playback'] & OkResponse>('/api/capture/step', { direction }),
  },

  // ── 自动化测试中心（E1，契约 §2.15）────────────────────────────────
  tests: {
    scripts: () => apiGet<{ ok: boolean; scripts: TestScriptInfo[] }>('/api/tests/scripts'),
    run: (scripts: string[]) => apiPost<OkResponse & { run?: TestStatusResponse['run'] }>('/api/tests/run', { scripts }),
    stop: () => apiPost<OkResponse>('/api/tests/stop'),
    status: () => apiGet<TestStatusResponse>('/api/tests/status'),
    reportUrl: testReportUrl,
  },
}
