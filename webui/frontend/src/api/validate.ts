/**
 * 零依赖运行时校验（T11）。
 *
 * 为什么不用 zod：本工程刻意压缩依赖面（安装风险 + 体积），而契约校验只需
 * 「形状足够、绝不抛异常」的守卫函数——不匹配时返回 false 由调用方降级，
 * 比引入 schema 库更轻且不会因版本升级改变行为。
 *
 * 约定：所有 `isXxx` 必须是**纯判定**，不得抛异常；宽进严出，
 * 只校验消费端真正会读取的字段。
 */

import type { LogRow, LogsResponse, Point, PointsResponse, Status, WsMessage } from './types'

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isStatus(value: unknown): value is Status {
  if (!isRecord(value)) return false
  // role 是唯一必读字段；其余允许缺省（连接未建立时后端只给 role + running）
  return value.role === 'master' || value.role === 'slave'
}

export function isPoint(value: unknown): value is Point {
  if (!isRecord(value)) return false
  return typeof value.ioa === 'number' && typeof value.type === 'string'
}

export function isPointsResponse(value: unknown): value is PointsResponse {
  if (!isRecord(value)) return false
  const points = value.points
  return Array.isArray(points) && points.every(isPoint)
}

export function isLogRow(value: unknown): value is LogRow {
  if (!isRecord(value)) return false
  return (
    typeof value.ts === 'number' &&
    typeof value.level === 'string' &&
    typeof value.message === 'string'
  )
}

export function isLogsResponse(value: unknown): value is LogsResponse {
  if (!isRecord(value)) return false
  const logs = value.logs
  return Array.isArray(logs) && logs.every(isLogRow)
}

/** 判断一条 WS 消息是否具备最小可用形状（kind + data）。 */
export function isWsMessage(value: unknown): value is WsMessage {
  if (!isRecord(value)) return false
  if (typeof value.kind !== 'string') return false
  if (!isRecord(value.data) && typeof value.data !== 'object') return false
  return true
}

/** 从任意信封里安全地取出 schemaVersion（缺省/非法 → undefined）。 */
export function readSchemaVersion(value: unknown): number | undefined {
  if (!isRecord(value)) return undefined
  const v = value.schemaVersion
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined
}
