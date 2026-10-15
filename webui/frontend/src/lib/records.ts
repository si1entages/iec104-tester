/**
 * WS/HTTP 记录归一化（T12）。
 *
 * `bridge.recent()` 与 WS 增量返回的都是**信封形态** `{kind, ts, schemaVersion, data}`，
 * 而 `GET /api/recent` 里的 frames/events 同样是信封。为了不让各组件到处判形状，
 * 统一在这里归一化；两种形态都能吃（兼容裸载荷）。
 */

import type { EngineEvent, Frame } from '../api/types'
import { isRecord } from '../api/validate'

export function normalizeFrame(raw: unknown): Frame | null {
  if (!isRecord(raw)) return null
  const payload = isRecord(raw.data) ? raw.data : raw
  const hex = payload.hex
  if (typeof hex !== 'string') return null
  return {
    ts: typeof raw.ts === 'number' ? raw.ts : undefined,
    direction: typeof payload.direction === 'string' ? payload.direction : '?',
    len: typeof payload.len === 'number' ? payload.len : Math.floor(hex.length / 2),
    hex,
    client: typeof payload.client === 'string' ? payload.client : undefined,
  }
}

export function normalizeFrames(raw: unknown): Frame[] {
  if (!Array.isArray(raw)) return []
  const out: Frame[] = []
  for (const item of raw) {
    const frame = normalizeFrame(item)
    if (frame) out.push(frame)
  }
  return out
}

export function normalizeEvent(raw: unknown): EngineEvent | null {
  if (!isRecord(raw)) return null
  const holder = isRecord(raw.data) ? raw.data : raw
  const type = holder.type
  if (typeof type !== 'string') return null
  return {
    ts: typeof raw.ts === 'number' ? raw.ts : undefined,
    type,
    data: isRecord(holder.data) ? holder.data : {},
  }
}

export function normalizeEvents(raw: unknown): EngineEvent[] {
  if (!Array.isArray(raw)) return []
  const out: EngineEvent[] = []
  for (const item of raw) {
    const event = normalizeEvent(item)
    if (event) out.push(event)
  }
  return out
}
