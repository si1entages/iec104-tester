import { useQuery } from '@tanstack/react-query'

import { apiGet } from './client'
import type { LogQueryParams, LogsResponse, Point, PointsResponse, Status } from './types'

export const queryKeys = {
  status: ['status'] as const,
  points: ['points'] as const,
  logs: (params: LogQueryParams) => ['logs', params] as const,
}

export function useStatusQuery() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: () => apiGet<Status>('/api/status'),
    // WS 快照会持续覆盖缓存；轮询只作为断线兜底
    refetchInterval: 5000,
  })
}

export function usePointsQuery() {
  return useQuery({
    queryKey: queryKeys.points,
    queryFn: async () => (await apiGet<PointsResponse>('/api/points')).points as Point[],
  })
}

export function useLogsQuery(params: LogQueryParams) {
  return useQuery({
    queryKey: queryKeys.logs(params),
    queryFn: () =>
      apiGet<LogsResponse>('/api/logs', {
        level_min: params.level_min,
        category: params.category,
        source: params.source,
        q: params.q,
        limit: params.limit ?? 200,
      }),
    refetchInterval: 10000,
  })
}
