import { describe, expect, it } from 'vitest'

import { newStation, toStationConfigs, validateDraft } from './stationDraft'

describe('多站草稿（T16 纯函数层）', () => {
  it('默认草稿两站，端口不撞车', () => {
    const draft = [newStation(1), newStation(2)]
    expect(draft.map((s) => s.station_id)).toEqual(['station-1', 'station-2'])
    expect(draft.map((s) => s.port)).toEqual([2404, 2405])
    expect(validateDraft(draft)).toEqual([])
  })

  it('toStationConfigs：只取启用的站，并剥掉本地 enabled 字段', () => {
    const draft = [newStation(1), { ...newStation(2), enabled: false }]
    const out = toStationConfigs(draft)
    expect(out).toHaveLength(1)
    expect(out[0].station_id).toBe('station-1')
    expect('enabled' in out[0]).toBe(false)
  })

  it('全部停用时直接拒绝（没有可启动内容）', () => {
    const draft = [newStation(1), newStation(2)].map((s) => ({ ...s, enabled: false }))
    expect(validateDraft(draft)).toContain('至少要启用一个站，否则没有可启动的内容')
    expect(toStationConfigs(draft)).toEqual([])
  })

  it('station_id 必填且唯一', () => {
    expect(validateDraft([{ ...newStation(1), station_id: '' }])).toContain('第 1 行：station_id 必填')

    const dup = [newStation(1), { ...newStation(2), station_id: 'station-1' }]
    expect(validateDraft(dup).some((m) => m.startsWith('station_id 重复'))).toBe(true)
  })

  it('端口越界与端口重复都被拦下', () => {
    expect(validateDraft([{ ...newStation(1), port: 70000 }]).some((m) => m.includes('端口必须'))).toBe(true)
    expect(validateDraft([{ ...newStation(1), port: -1 }]).some((m) => m.includes('端口必须'))).toBe(true)

    const clash = [newStation(1), { ...newStation(2), port: 2404 }]
    expect(validateDraft(clash).some((m) => m.startsWith('端口重复'))).toBe(true)
  })

  it('公共地址与点数必须是非负整数', () => {
    expect(validateDraft([{ ...newStation(1), common_addr: -1 }]).some((m) => m.includes('公共地址'))).toBe(
      true,
    )
    expect(validateDraft([{ ...newStation(1), yx_count: -5 }]).some((m) => m.includes('yx_count'))).toBe(
      true,
    )
  })

  it('停用的站不参与校验（可以带着坏参数但不启动）', () => {
    const draft = [newStation(1), { ...newStation(2), enabled: false, port: 99999, station_id: '' }]
    expect(validateDraft(draft)).toEqual([])
  })
})
