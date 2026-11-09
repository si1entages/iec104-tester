/**
 * 点值与增量补丁（T12）。
 *
 * 点表快照（`GET /api/points`、WS `snapshot`）里 `type` 是**类别码**
 * （`YX`/`YC`/`YK`/`YM`），而 WS `event`（`data_received`）里携带的是 ASDU
 * `type_id`（整数）与对象数据。这里负责两者之间的映射与就地合并。
 *
 * 关于事件对象数据：后端 `webui/session.py::jsonable` 会把非基础类型转成
 * `str(obj)`，因此 `objects[i].data` 形如
 * `"SinglePoint(value=True, quality=QualityDescriptor(raw=0))"`。
 * 本模块用**严格正则**解析它；解析失败一律返回空补丁，由快照刷新兜底
 * （绝不因为格式变化而崩溃或写坏数据）。
 */

import type { EngineEvent, Point } from '../api/types'

export type PointCategory = 'YX' | 'YC' | 'YK' | 'YM'

export interface PointPatch {
  key: string
  value: Point['value']
}

const YX_TYPES = new Set([1, 2, 3, 4, 20, 30, 31, 71])
const YC_TYPES = new Set([9, 10, 11, 12, 13, 14, 21, 34, 35, 36])
const YM_TYPES = new Set([15, 16, 37])

export function categoryOfTypeId(typeId: number): PointCategory | null {
  if (YX_TYPES.has(typeId)) return 'YX'
  if (YC_TYPES.has(typeId)) return 'YC'
  if (YM_TYPES.has(typeId)) return 'YM'
  return null
}

/** 点表行唯一键：`类别-IOA`（如 `YX-1`、`YC-4001`）。 */
export function pointKey(point: Pick<Point, 'type' | 'ioa'>): string {
  return `${point.type}-${point.ioa}`
}

/** 解析后端 `str(数据对象)` 形态；失败返回 null。 */
export function parseObjectRepr(repr: unknown, category: PointCategory): Point['value'] | null {
  if (typeof repr !== 'string') return null
  const m = /^\w+\(value=([^,)]+)/.exec(repr.trim())
  if (!m) return null
  const raw = m[1].trim()
  if (category === 'YX') {
    if (raw === 'True') return 'ON'
    if (raw === 'False') return 'OFF'
    // 双点/成组单点可能是数值
    const n = Number(raw)
    if (Number.isFinite(n)) return n === 0 ? 'OFF' : 'ON'
    return null
  }
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

interface RawObject {
  ioa?: unknown
  data?: unknown
}

/** 从 WS `event` 里提取点值补丁（不支持的形状 → 空数组）。 */
export function extractPatches(event: EngineEvent | undefined): PointPatch[] {
  if (!event) return []
  const payload = event.data as Record<string, unknown> | undefined
  if (!payload) return []
  const typeId = payload.type_id
  const objects = payload.objects
  if (typeof typeId !== 'number' || !Array.isArray(objects)) return []
  const category = categoryOfTypeId(typeId)
  if (!category) return []

  const patches: PointPatch[] = []
  for (const raw of objects as RawObject[]) {
    if (typeof raw?.ioa !== 'number') continue
    const value = parseObjectRepr(raw.data, category)
    if (value === null) continue
    patches.push({ key: `${category}-${raw.ioa}`, value })
  }
  return patches
}

/** 把补丁就地应用到点表：仅被改动的行换新对象，其余保持引用（避免整表重建）。 */
export function applyPatches(
  points: Point[] | undefined,
  patches: PointPatch[],
  changedRows?: Point[],
): Point[] {
  if (!points || patches.length === 0) return points ?? []
  const byKey = new Map(patches.map((p) => [p.key, p.value]))
  let changed = false
  const next = points.slice()
  for (let i = 0; i < next.length; i += 1) {
    const row = next[i]
    const key = pointKey(row)
    if (!byKey.has(key)) continue
    const value = byKey.get(key)
    if (row.value === value) {
      byKey.delete(key)
      continue
    }
    const updated = { ...row, value }
    next[i] = updated
    changedRows?.push(updated)
    byKey.delete(key)
    changed = true
  }
  return changed ? next : points
}

/**
 * 合并两次快照：逐位比较，只为变化的行创建新对象，
 * 全无变化时**返回原数组引用**（让 React 直接跳过重渲染）。
 */
export function mergePointValues(
  prev: Point[] | undefined,
  next: Point[],
  changedRows?: Point[],
): Point[] {
  if (!prev) return next
  if (prev.length !== next.length) return next
  let changed = false
  const out = prev.slice()
  for (let i = 0; i < next.length; i += 1) {
    const a = prev[i]
    const b = next[i]
    if (
      a.ioa === b.ioa &&
      a.type === b.type &&
      a.value === b.value &&
      a.enabled === b.enabled &&
      a.name === b.name &&
      a.quality === b.quality &&
      a.subtype === b.subtype &&
      a.sbo === b.sbo &&
      a.unit === b.unit &&
      a.decimal_places === b.decimal_places
    ) {
      continue
    }
    out[i] = b
    changedRows?.push(b)
    changed = true
  }
  return changed ? out : prev
}

/** T93：点值是否陈旧（ts=0 表示从未收到过数据，不算陈旧；阈值与告警一致 60s）. */
export function isStalePoint(p: Pick<Point, 'ts'>, staleSeconds = 60): boolean {
  return typeof p.ts === 'number' && p.ts > 0 && Date.now() - p.ts > staleSeconds * 1000
}
