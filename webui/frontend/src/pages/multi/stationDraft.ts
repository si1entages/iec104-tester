/**
 * 多站配置草稿（T16）——纯函数层，便于单测。
 *
 * 为什么需要「草稿」：后端只提供 **整体** 启动/停止
 * （`POST /api/multi/start` 用一次请求里的 `stations` 数组创建整个管理器），
 * 没有「往运行中的管理器里加/减一个站」的端点。因此：
 *
 * - **增删** 发生在草稿上（自由编辑，想改几次改几次）
 * - **启停** 生效时才把草稿提交给后端
 * - 草稿行多一个**纯本地**的 `enabled` 开关（不发给后端），
 *   用来表达「这一站本次不参与启动」—— 这是「单站启停」在整体 API 上的落地方式
 */

import type { StationConfig } from '../../api/types'
import { tNow } from '../../i18n'

/** 草稿行 = StationConfig + 本地参与开关 */
export interface DraftStation extends StationConfig {
  /** 纯本地字段，绝不发给后端；false = 本次不启动该站 */
  enabled: boolean
}

/** 生成一行默认配置（分散端口，避免新加的两站撞车） */
export function newStation(seq: number, basePort = 2404): DraftStation {
  return {
    station_id: `station-${seq}`,
    station_name: tNow('multi.defaultName', { n: seq }),
    host: '0.0.0.0',
    port: basePort + seq - 1,
    common_addr: seq,
    max_connections: 16,
    auto_generate: true,
    yx_count: 100,
    yc_count: 50,
    yk_count: 20,
    ym_count: 10,
    spontaneous_enabled: true,
    simulation_enabled: false,
    enabled: true,
  }
}

/** 草稿 → 后端请求体：只取启用的站，并剥掉本地 `enabled` 字段 */
export function toStationConfigs(draft: DraftStation[]): StationConfig[] {
  return draft
    .filter((s) => s.enabled)
    .map(({ enabled: _enabled, ...rest }) => rest as StationConfig)
}

/**
 * 校验草稿，返回人类可读的问题清单（空数组 = 通过）。
 *
 * 与后端校验保持一致（后端 400/业务失败会再兜一层），
 * 这里只是把错误在**提交前**就摊到界面上，避免静默失败。
 */
export function validateDraft(draft: DraftStation[]): string[] {
  const issues: string[] = []
  const active = draft.filter((s) => s.enabled)

  if (active.length === 0) {
    issues.push(tNow('multi.v.enableAtLeastOne'))
  }

  const seen = new Map<string, number>()
  active.forEach((s, i) => {
    const label = s.station_id?.trim() || tNow('multi.v.rowLabel', { n: i + 1 })

    if (!s.station_id || !s.station_id.trim()) {
      issues.push(tNow('multi.v.stationIdRequired', { label: tNow('multi.v.rowLabel', { n: i + 1 }) }))
    } else {
      const key = s.station_id.trim()
      const prev = seen.get(key)
      if (prev !== undefined) {
        issues.push(tNow('multi.v.stationIdDup', { id: key, a: prev + 1, b: i + 1 }))
      } else {
        seen.set(key, i)
      }
    }

    if (!s.host || !s.host.trim()) {
      issues.push(tNow('multi.v.hostRequired', { label }))
    }
    const port = s.port
    if (port === undefined || !Number.isInteger(port) || port < 0 || port > 65535) {
      issues.push(tNow('multi.v.portInvalid', { label, value: String(port) }))
    }
    const ca = s.common_addr
    if (ca === undefined || !Number.isInteger(ca) || ca < 0) {
      issues.push(tNow('multi.v.addrInvalid', { label, value: String(ca) }))
    }
    for (const [name, v] of [
      ['yx_count', s.yx_count],
      ['yc_count', s.yc_count],
      ['yk_count', s.yk_count],
      ['ym_count', s.ym_count],
    ] as const) {
      if (v !== undefined && (!Number.isInteger(v) || v < 0)) {
        issues.push(tNow('multi.v.countInvalid', { label, name, value: v }))
      }
    }
  })

  // 同一端口重复：端口冲突是启动失败最常见的原因，提前提示
  const byPort = new Map<number, string>()
  for (const s of active) {
    if (s.port === undefined) continue // 已在上面报过
    const prev = byPort.get(s.port)
    if (prev !== undefined) {
      issues.push(tNow('multi.v.portDup', {
        port: s.port,
        a: prev,
        b: s.station_id || tNow('multi.v.unnamed'),
      }))
    } else {
      byPort.set(s.port, s.station_id || tNow('multi.v.unnamed'))
    }
  }

  return issues
}
