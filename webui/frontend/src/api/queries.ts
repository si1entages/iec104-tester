import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api } from './endpoints'
import { applyPatches, mergePointValues } from '../lib/pointValue'
import type { PointPatch } from '../lib/pointValue'
import { useUiStore } from '../store/uiStore'
import type {
  AlarmsSnapshot,
  EngineEvent,
  Frame,
  HistoryDataParams,
  HistoryDataRecord,
  HistoryFramesParams,
  HistoryFrameRecord,
  HistoryRowsResponse,
  HistoryStatsResponse,
  LogQueryParams,
  LogRow,
  MultiStatusResponse,
  MultiSummaryResponse,
  OkResponse,
  Point,
  RecentResponse,
  SchemaResponse,
  SimulationStatusResponse,
  Status,
  CaptureFramesResponse,
  CaptureStatus,
  TestScriptInfo,
  TestStatusResponse,
} from './types'

/** 实时日志缓冲上限（与旧原生 UI 的 500 条保持一致）。 */
export const MAX_LIVE_LOGS = 500
/** 实时报文缓冲上限（报文查看器） */
export const MAX_LIVE_FRAMES = 2000
/** 实时事件缓冲上限 */
export const MAX_LIVE_EVENTS = 500

/** 当前工作台角色：查询键按角色隔离，切换主站/子站互不覆盖、切回不重新加载. */
function activeRole() {
  return useUiStore.getState().activeRole
}

export const queryKeys = {
  schema: ['schema'] as const,
  status: () => ['status', activeRole()] as const,
  points: () => ['points', activeRole()] as const,
  recent: () => ['recent', activeRole()] as const,
  logs: (params: LogQueryParams) => ['logs', activeRole(), params] as const,
  liveLogs: () => ['logs', activeRole(), 'live'] as const,
  liveFrames: () => ['frames', activeRole(), 'live'] as const,
  liveEvents: () => ['events', activeRole(), 'live'] as const,
  multiStatus: () => ['multi', activeRole(), 'status'] as const,
  multiSummary: () => ['multi', activeRole(), 'summary'] as const,
  historyStats: () => ['history', activeRole(), 'stats'] as const,
  historyData: (params: HistoryDataParams) =>
    ['history', activeRole(), 'data', params] as const,
  historyFrames: (params: HistoryFramesParams) =>
    ['history', activeRole(), 'frames', params] as const,
  simulationStatus: () => ['simulation', activeRole(), 'status'] as const,
  captureStatus: () => ['capture', activeRole(), 'status'] as const,
  captureFrames: (offset: number, limit: number) =>
    ['capture', activeRole(), 'frames', offset, limit] as const,
  testScripts: () => ['tests', activeRole(), 'scripts'] as const,
  testStatus: () => ['tests', activeRole(), 'status'] as const,
  alarms: () => ['alarms', activeRole()] as const,
}

// ── 查询 ───────────────────────────────────────────────────────────────

/** 契约版本探测；只在挂载时取一次（版本不会在运行期变化）。 */
export function useSchemaQuery() {
  return useQuery<SchemaResponse>({
    queryKey: queryKeys.schema,
    queryFn: api.schema,
    staleTime: Infinity,
    retry: 1,
  })
}

export function useStatusQuery() {
  return useQuery<Status>({
    queryKey: queryKeys.status(),
    queryFn: api.status,
    // WS 快照会持续覆盖缓存；轮询只作为断线兜底
    refetchInterval: 5000,
  })
}

export function usePointsQuery() {
  return useQuery<Point[]>({
    queryKey: queryKeys.points(),
    queryFn: async () => (await api.points()).points,
    // 十万点表：不再自动轮询，值由 WS（增量补丁/快照刷新）驱动
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  })
}

export function useRecentQuery() {
  return useQuery<RecentResponse>({
    queryKey: queryKeys.recent(),
    queryFn: api.recent,
    refetchInterval: 5000,
  })
}

/**
 * 多站运行状态（T16）。只在多站页挂载时轮询——页面卸载即停止，不新增常驻资源。
 */
export function useMultiStatusQuery() {
  return useQuery<MultiStatusResponse>({
    queryKey: queryKeys.multiStatus(),
    queryFn: api.multi.status,
    refetchInterval: 2000,
  })
}

/** 多站聚合汇总（T16）。同样只在页面挂载期间轮询。 */
export function useMultiSummaryQuery() {
  return useQuery<MultiSummaryResponse>({
    queryKey: queryKeys.multiSummary(),
    queryFn: api.multi.summary,
    refetchInterval: 2000,
  })
}

export function useLogsQuery(params: LogQueryParams) {
  return useQuery({
    queryKey: queryKeys.logs(params),
    queryFn: () => api.logs({ ...params, limit: params.limit ?? 200 }),
    refetchInterval: 10000,
  })
}

/** 历史库统计（轻量，页面挂载期间低频轮询即可） */
export function useHistoryStatsQuery() {
  return useQuery<HistoryStatsResponse>({
    queryKey: queryKeys.historyStats(),
    queryFn: api.history.stats,
    staleTime: 5000,
    refetchInterval: 15000,
  })
}

/**
 * 数据历史查询。不做自动轮询——历史是静态存量数据，
 * 由页面「查询」按钮变更 params（queryKey 含 params）触发请求。
 */
export function useHistoryDataQuery(params: HistoryDataParams, enabled = true) {
  return useQuery<HistoryRowsResponse<HistoryDataRecord>>({
    queryKey: queryKeys.historyData(params),
    queryFn: () => api.history.data(params),
    enabled,
    refetchOnWindowFocus: false,
    staleTime: 0,
  })
}

/** 报文历史查询，同 useHistoryDataQuery。 */
export function useHistoryFramesQuery(params: HistoryFramesParams, enabled = true) {
  return useQuery<HistoryRowsResponse<HistoryFrameRecord>>({
    queryKey: queryKeys.historyFrames(params),
    queryFn: () => api.history.frames(params),
    enabled,
    refetchOnWindowFocus: false,
    staleTime: 0,
  })
}

/** 网络异常模拟状态（仅在状态页挂载期间轮询，统计计数实时更新） */
export function useSimulationStatusQuery() {
  return useQuery<SimulationStatusResponse>({
    queryKey: queryKeys.simulationStatus(),
    queryFn: api.simulation.status,
    refetchInterval: 3000,
    staleTime: 1000,
  })
}

function useDerivedArray<T>(key: readonly unknown[]): T[] {
  const { data } = useQuery<T[]>({
    queryKey: key,
    queryFn: () => [],
    enabled: false,
    initialData: [],
    staleTime: Infinity,
    gcTime: Infinity,
  })
  return data
}

/** 实时日志（由 WS 桥写入 React Query 缓存）。 */
export function useLiveLogs(): LogRow[] {
  return useDerivedArray<LogRow>(queryKeys.liveLogs())
}

/** 实时报文（报文查看器）。 */
export function useLiveFrames(): Frame[] {
  return useDerivedArray<Frame>(queryKeys.liveFrames())
}

/** 实时引擎事件。 */
export function useLiveEvents(): EngineEvent[] {
  return useDerivedArray<EngineEvent>(queryKeys.liveEvents())
}

// ── 缓存写入（给 WS 桥接层用）──────────────────────────────────────────

function appendCapped<T>(list: T[] | undefined, row: T, cap: number): T[] {
  const next = list ? list.concat(row) : [row]
  return next.length > cap ? next.slice(next.length - cap) : next
}

export function appendLiveLog(client: QueryClient, row: LogRow): void {
  appendLiveLogs(client, [row])
}

/**
 * 批量写入实时日志（WS 桥高频日志的节流合并入口）：
 * 整批一次 setQueryData，避免逐条触发渲染。
 */
export function appendLiveLogs(client: QueryClient, rows: LogRow[]): void {
  if (rows.length === 0) return
  client.setQueryData<LogRow[]>(queryKeys.liveLogs(), (prev) => {
    const next = prev ? prev.concat(rows) : rows.slice()
    return next.length > MAX_LIVE_LOGS ? next.slice(next.length - MAX_LIVE_LOGS) : next
  })
}

export function replaceLiveLogs(client: QueryClient, rows: LogRow[]): void {
  client.setQueryData<LogRow[]>(queryKeys.liveLogs(), rows.slice(-MAX_LIVE_LOGS))
}

export function clearLiveLogs(client: QueryClient): void {
  client.setQueryData<LogRow[]>(queryKeys.liveLogs(), [])
}

export function appendFrame(client: QueryClient, frame: Frame): void {
  client.setQueryData<Frame[]>(queryKeys.liveFrames(), (prev) =>
    appendCapped(prev, frame, MAX_LIVE_FRAMES),
  )
}

export function replaceFrames(client: QueryClient, frames: Frame[]): void {
  client.setQueryData<Frame[]>(queryKeys.liveFrames(), frames.slice(-MAX_LIVE_FRAMES))
}

export function clearFrames(client: QueryClient): void {
  client.setQueryData<Frame[]>(queryKeys.liveFrames(), [])
}

export function appendEvent(client: QueryClient, event: EngineEvent): void {
  client.setQueryData<EngineEvent[]>(queryKeys.liveEvents(), (prev) =>
    appendCapped(prev, event, MAX_LIVE_EVENTS),
  )
}

export function replaceEvents(client: QueryClient, events: EngineEvent[]): void {
  client.setQueryData<EngineEvent[]>(queryKeys.liveEvents(), events.slice(-MAX_LIVE_EVENTS))
}

// ── 点表写入（diff 合并，避免整表重建）─────────────────────────────────

/** 用快照对齐点表：仅变化行换新对象，无变化则保持原数组引用。 */
export function mergePointsSnapshot(client: QueryClient, points: Point[]): void {
  client.setQueryData<Point[]>(queryKeys.points(), (prev) => mergePointValues(prev, points))
}

/** 用事件补丁就近更新点表（不触发网络请求）。 */
export function patchPoints(client: QueryClient, patches: PointPatch[]): void {
  if (patches.length === 0) return
  client.setQueryData<Point[]>(queryKeys.points(), (prev) => applyPatches(prev, patches))
}

// ── 命令（mutations）──────────────────────────────────────────────────

function useInvalidateAfterCommand() {
  const client = useQueryClient()
  // 命令会改变运行状态与点值：返回后立刻让 status/points 失效，
  // 不等 WS 快照（断线时也能对齐）；
  // 多站命令同理，顺带刷新多站状态/汇总，避免等下一个轮询周期。
  return () => {
    void client.invalidateQueries({ queryKey: queryKeys.status() })
    void client.invalidateQueries({ queryKey: queryKeys.points() })
    void client.invalidateQueries({ queryKey: queryKeys.multiStatus() })
    void client.invalidateQueries({ queryKey: queryKeys.multiSummary() })
  }
}

/** 带参数的命令（如 master.start({host, port})）。 */
export function useCommand<B, R extends OkResponse = OkResponse>(fn: (body: B) => Promise<R>) {
  const onSettled = useInvalidateAfterCommand()
  return useMutation<R, Error, B>({
    mutationFn: (body: B) => fn(body),
    onSettled,
  })
}

/** 无参数命令（如 master.stop()）。 */
export function useCommandNoArgs<R extends OkResponse = OkResponse>(fn: () => Promise<R>) {
  const onSettled = useInvalidateAfterCommand()
  return useMutation<R, Error, void>({
    mutationFn: () => fn(),
    onSettled,
  })
}

/** 值守告警（T93）：2s 轮询（评估在服务端 1Hz，轮询时延足够值守场景）。 */
export function useAlarmsQuery() {
  return useQuery<AlarmsSnapshot>({
    queryKey: queryKeys.alarms(),
    queryFn: api.alarms,
    refetchInterval: 2000,
  })
}

/** 报文录制/回放状态；录制中 1s 轮询，停止后降低频率。 */
export function useCaptureStatusQuery() {
  return useQuery<CaptureStatus>({
    queryKey: queryKeys.captureStatus(),
    queryFn: api.capture.status,
    refetchInterval: (query) => (query.state.data?.recording ? 1000 : 5000),
  })
}

export function useCaptureFramesQuery(offset: number, limit: number, enabled: boolean) {
  return useQuery<CaptureFramesResponse>({
    queryKey: queryKeys.captureFrames(offset, limit),
    queryFn: () => api.capture.frames(offset, limit),
    enabled,
    staleTime: 0,
  })
}

/** 测试脚本列表（静态，挂载时取一次）。 */
export function useTestScriptsQuery() {
  return useQuery<TestScriptInfo[]>({
    queryKey: queryKeys.testScripts(),
    queryFn: async () => (await api.tests.scripts()).scripts,
    staleTime: 30_000,
  })
}

/** 测试运行状态；运行中 1s 轮询，空闲 5s。 */
export function useTestStatusQuery() {
  return useQuery<TestStatusResponse>({
    queryKey: queryKeys.testStatus(),
    queryFn: api.tests.status,
    refetchInterval: (query) => (query.state.data?.running ? 1000 : 5000),
  })
}
