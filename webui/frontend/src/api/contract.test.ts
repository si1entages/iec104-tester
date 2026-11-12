/**
 * 运行时契约校验单测（contract.ts / contracts.ts）。
 *
 * 重点锁死 2026-11-07 悬停翻译缺陷的失败形态：后端返回扁平
 * `{ok, format, segments}`，任何“嵌套 translation”或缺失 segments 的响应都必须
 * 被拒绝，而不是静默渲染失败。
 */
import { describe, expect, it } from 'vitest'

import { ApiContractError, arr, num, obj, optional, str } from './contract'
import {
  frameDecodeSchema,
  historyStatsSchema,
  okSchema,
  schemaResponseSchema,
  testStatusResponseSchema,
  commissionSessionResponseSchema,
  commissionSessionsResponseSchema,
  commissionStatusResponseSchema,
  commissionItemResponseSchema,
} from './contracts'

describe('contract DSL', () => {
  it('对象：必填缺失报路径，可选缺失跳过，未知字段忽略', () => {
    const schema = obj({ ok: str(), note: optional(num()) })
    // 未知字段忽略校验但保留原值（不复制对象，避免高频快照额外分配）
    expect(schema.parse({ ok: 'yes', extra: 1 }, '/x')).toEqual({ ok: 'yes', extra: 1 })
    expect(schema.parse({ ok: 'yes', note: 2 }, '/x')).toEqual({ ok: 'yes', note: 2 })

    try {
      schema.parse({ note: 1 }, '/x')
      expect.unreachable('应抛 ApiContractError')
    } catch (e) {
      expect(e).toBeInstanceOf(ApiContractError)
      expect((e as ApiContractError).path).toBe('/x.ok')
      expect((e as ApiContractError).message).toContain('必填字段缺失')
    }
  })

  it('数组：错误定位到下标', () => {
    const schema = arr(num())
    try {
      schema.parse([1, '2', 3], '/rows')
      expect.unreachable('应抛 ApiContractError')
    } catch (e) {
      expect((e as ApiContractError).path).toBe('/rows[1]')
    }
  })
})

describe('响应 schema', () => {
  it('frame decode：接受真实扁平响应', () => {
    const parsed = frameDecodeSchema.parse(
      {
        ok: true,
        format: 'I',
        segments: [{ title: 'APCI（传输控制头）', lines: ['I 帧'] }],
      },
      '/api/frames/decode',
    )
    expect(parsed).toMatchObject({ ok: true, format: 'I' })
    expect(parsed.segments).toHaveLength(1)
  })

  it('frame decode：拒绝嵌套 translation（旧前端错误假设）', () => {
    try {
      frameDecodeSchema.parse(
        { ok: true, translation: { format: 'I', segments: [] } },
        '/api/frames/decode',
      )
      expect.unreachable('应抛 ApiContractError')
    } catch (e) {
      expect(e).toBeInstanceOf(ApiContractError)
      // ok=true 时 format 必填；translation 不是契约字段
      expect((e as ApiContractError).path).toBe('/api/frames/decode.format')
    }
  })

  it('frame decode：错误响应必须带 error', () => {
    expect(frameDecodeSchema.parse({ ok: false, error: '非法 HEX 串' }, '/x')).toEqual({
      ok: false,
      error: '非法 HEX 串',
    })
    expect(() => frameDecodeSchema.parse({ ok: false }, '/x')).toThrow(ApiContractError)
  })

  it('通用命令响应：ok 必须是 boolean', () => {
    expect(() => okSchema.parse({ ok: 'true' }, '/api/master/stop')).toThrow(ApiContractError)
  })

  it('schema 响应 / 历史统计 / 测试状态：真实形状通过', () => {
    expect(
      schemaResponseSchema.parse(
        { ok: true, schemaVersion: 1, wsKinds: ['snapshot'], wsSchemaKey: 'schemaVersion' },
        '/api/schema',
      ).ok,
    ).toBe(true)

    expect(
      historyStatsSchema.parse(
        {
          data_records: 0,
          frame_records: 0,
          buffered_data: 0,
          buffered_frames: 0,
          oldest_data: 0,
          newest_data: 0,
          db_size_bytes: 0,
          dropped_records: 0,
        },
        '/api/history/stats',
      ).data_records,
    ).toBe(0)

    expect(
      testStatusResponseSchema.parse({ ok: true, running: false, run: null }, '/api/tests/status')
        .run,
    ).toBeNull()
  })
})

describe('WP2 对点/传动验收契约', () => {
  const item = {
    ioa: 1, name: '开关A', kind: 'YX', group: 1, expected: true,
    tolerance: 0, actual: true, quality: 'GOOD', verdict: 'pass',
    note: '', operator: '甲', checked_at: 1, tx_frame: '6804',
    rx_frame: '6806', tx_time: 1, rx_time: 2, reason: '',
  }
  const summary = { total: 1, pending: 0, pass: 1, fail: 0, manual: 0, done: 1 }
  const session = {
    id: 'c-1', name: '验收', created_at: 1, operator: '甲', status: 'done',
    started_at: 1, finished_at: 2, cursor: 1, note: '',
    summary, point_count: 1, items: [item],
  }

  it('会话明细：合法形状通过，缺 items 拒绝', () => {
    expect(commissionSessionResponseSchema.parse({ ok: true, session }, '/x')).toBeTruthy()
    expect(() => commissionSessionResponseSchema.parse(
      { ok: true, session: { ...session, items: undefined } }, '/x')).toThrow(ApiContractError)
  })

  it('会话列表：status 必须含 running/session_id/cursor/total', () => {
    const status = { ok: true, running: false, session_id: null, cursor: 0, total: 0 }
    expect(commissionSessionsResponseSchema.parse(
      { ok: true, sessions: [{ ...session, items: undefined }], status }, '/x')).toBeTruthy()
    expect(() => commissionSessionsResponseSchema.parse(
      { ok: true, sessions: [], status: { ok: true, running: false } }, '/x'))
      .toThrow(ApiContractError)
  })

  it('结论枚举：非法 verdict 拒绝', () => {
    expect(() => commissionSessionResponseSchema.parse(
      { ok: true, session: { ...session, items: [{ ...item, verdict: 'bogus' }] } }, '/x'))
      .toThrow(ApiContractError)
  })

  it('单条改判响应与状态响应', () => {
    expect(commissionItemResponseSchema.parse({ ok: true, item }, '/x')).toBeTruthy()
    expect(commissionStatusResponseSchema.parse(
      { ok: true, running: true, session_id: 'c-1', cursor: 1, total: 3 }, '/x')).toBeTruthy()
  })
})
