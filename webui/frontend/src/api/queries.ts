import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'

import { api } from './endpoints'
import type {
  LogQueryParams,
  LogRow,
  OkResponse,
  Point,
  RecentResponse,
  SchemaResponse,
  Status,
} from './types'

/** 实时日志缓冲上限（与旧原生 UI 的 500 条保持一致）。 */
export const MAX_LIVE_LOGS = 500

export const queryKeys = {
  schema: ['schema'] as const,
  status: ['status'] as const,
  points: ['points'] as const,
  recent: ['recent'] as const,
  logs: (params: LogQueryParams) => ['logs', params] as const,
  liveLogs: ['logs', 'live'] as const,
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
    queryKey: queryKeys.status,
    queryFn: api.status,
    // WS 快照会持续覆盖缓存；轮询只作为断线兜底
    refetchInterval: 5000,
  })
}

export function usePointsQuery() {
  return useQuery<Point[]>({
    queryKey: queryKeys.points,
    queryFn: async () => (await api.points()).points,
  })
}

export function useRecentQuery() {
  return useQuery<RecentResponse>({
    queryKey: queryKeys.recent,
    queryFn: api.recent,
    refetchInterval: 5000,
  })
}

export function useLogsQuery(params: LogQueryParams) {
  return useQuery({
    queryKey: queryKeys.logs(params),
    queryFn: () => api.logs({ ...params, limit: params.limit ?? 200 }),
    refetchInterval: 10000,
  })
}

/**
 * 实时日志：数据存在 React Query 缓存里（服务端数据不落 Zustand），
 * 由 WS 桥接层用 `appendLiveLog` 增量写入。
 */
export function useLiveLogs(): LogRow[] {
  const { data } = useQuery<LogRow[]>({
    queryKey: queryKeys.liveLogs,
    queryFn: () => [],
    enabled: false,
    initialData: [],
    staleTime: Infinity,
    gcTime: Infinity,
  })
  return data
}

// ── 实时日志缓存写入（给 WS 桥接层用）──────────────────────────────────

export function appendLiveLog(client: QueryClient, row: LogRow): void {
  client.setQueryData<LogRow[]>(queryKeys.liveLogs, (prev) =>
    [...(prev ?? []), row].slice(-MAX_LIVE_LOGS),
  )
}

export function replaceLiveLogs(client: QueryClient, rows: LogRow[]): void {
  client.setQueryData<LogRow[]>(queryKeys.liveLogs, rows.slice(-MAX_LIVE_LOGS))
}

export function clearLiveLogs(client: QueryClient): void {
  client.setQueryData<LogRow[]>(queryKeys.liveLogs, [])
}

// ── 命令（mutations）──────────────────────────────────────────────────

function useInvalidateAfterCommand() {
  const client = useQueryClient()
  // 命令会改变运行状态与点值：返回后立刻让 status/points 失效，
  // 不等 WS 快照（断线时也能对齐）
  return () => {
    void client.invalidateQueries({ queryKey: queryKeys.status })
    void client.invalidateQueries({ queryKey: queryKeys.points })
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
