/**
 * 全部 REST 端点（T11）——与 `webui/api_contract.md` §2 一一对应（35 个 + /api/schema）。
 * 端点集合由 `webui/contract_check.py` 自检，防止契约漂移。
 */

import { apiGet, apiGetText, apiPost, apiPostText } from './client'
import type {
  BatchPointsRequest,
  BitstringRequest,
  CommandResponse,
  DelayRequest,
  EpRequest,
  FileRequest,
  GiRequest,
  ImportFormat,
  LogQueryParams,
  LogsResponse,
  MasterStartRequest,
  OkResponse,
  ParamRequest,
  PointsResponse,
  PsRequest,
  ReadRequest,
  RecentResponse,
  ResponseBehavior,
  SchemaResponse,
  SetpointRequest,
  SimRequest,
  SlaveStartRequest,
  SessionExport,
  Status,
  StepRequest,
  YcRequest,
  YkRequest,
  YmRequest,
  YxRequest,
} from './types'

export const LOGS_EXPORT_URL = '/api/logs/export'
export const POINTS_CSV_URL = '/api/export/points.csv'

function logsQuery(params: LogQueryParams): Record<string, string | number | undefined> {
  return {
    level_min: params.level_min,
    category: params.category,
    source: params.source,
    q: params.q,
    limit: params.limit,
  }
}

export const api = {
  // ── 状态与点表 ───────────────────────────────────────────────────────
  schema: () => apiGet<SchemaResponse>('/api/schema'),
  status: () => apiGet<Status>('/api/status'),
  points: () => apiGet<PointsResponse>('/api/points'),
  recent: () => apiGet<RecentResponse>('/api/recent'),

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
}
