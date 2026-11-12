/**
 * WP1~WP10 新增共享 hook 的单测（v1.11 覆盖率补真）。
 *
 * 这 4 个模块只做「API 调用 + 本地状态编排」，不渲染 UI：用 vi.mock 桩掉
 * queries/endpoints 后可直接 renderHook 驱动，避免 jsdom 下 React Query 的
 * 轮询定时器把用例拖成异步噪声（setup.ts 已用 focusManager 停掉后台刷新）。
 * 重点锁死现场语义：guard 的 busy/error 生命周期、期望值 bool>number>string、
 * 否定确认（ok=false）原样呈现、空名字拦截、无活动方案时 restore 静默。
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ── 桩：查询 hook 只返回固定快照，端点全部可观测 ──────────────────────
const invalidateQueries = vi.fn(async () => {})
vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>()
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries }),
  }
})

const api = vi.hoisted(() => ({
  commission: {
    create: vi.fn(), run: vi.fn(), stop: vi.fn(), delete: vi.fn(), verdict: vi.fn(),
  },
  audit: { verify: vi.fn() },
  profiles: {
    apply: vi.fn(), save: vi.fn(), remove: vi.fn(), restore: vi.fn(),
    importYaml: vi.fn(),
  },
  sniff: { start: vi.fn(), stop: vi.fn() },
}))
vi.mock('../api/endpoints', () => ({ api }))

const queryData = vi.hoisted(() => ({
  sessions: { sessions: [], status: { running: false } } as unknown,
  points: [] as unknown,
  detail: { session: { items: [], summary: {} } } as unknown,
  audit: { records: [], stats: {} } as unknown,
  profiles: { profiles: [], active: '' } as unknown,
  sniff: { running: false, frames: 0, stats: {}, capability: null } as unknown,
}))
const qhooks = vi.hoisted(() => ({
  useCommissionSessionsQuery: vi.fn(),
  useCommissionSessionQuery: vi.fn(),
  usePointsQuery: vi.fn(),
  useAuditRecordsQuery: vi.fn(),
  useProfilesQuery: vi.fn(),
  useSniffQuery: vi.fn(),
}))
vi.mock('../api/queries', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/queries')>()
  return { ...actual, ...qhooks }
})

vi.mock('../i18n', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../i18n')>()
  return { ...actual, useT: () => (k: string) => k }
})

import { useAudit } from './useAudit'
import { useCommission } from './useCommission'
import { useProfiles } from './useProfiles'
import { useSniffer } from './useSniffer'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function resetMocks() {
  vi.clearAllMocks()
  qhooks.useCommissionSessionsQuery.mockReturnValue({ data: queryData.sessions })
  qhooks.useCommissionSessionQuery.mockReturnValue({ data: queryData.detail })
  qhooks.usePointsQuery.mockReturnValue({ data: queryData.points })
  qhooks.useAuditRecordsQuery.mockReturnValue({ data: queryData.audit, isLoading: false })
  qhooks.useProfilesQuery.mockReturnValue({ data: queryData.profiles, isLoading: false })
  qhooks.useSniffQuery.mockReturnValue({ data: queryData.sniff })
}

beforeEach(resetMocks)

describe('useAudit（WP4a）', () => {
  it('verify 成功写入结果，busy 归位；失败把错误落到 error', async () => {
    const ok = { valid: true, total: 3, broken_at: null, reason: '' }
    api.audit.verify.mockResolvedValueOnce(ok).mockRejectedValueOnce(new Error('链断了'))
    const { result } = renderHook(() => useAudit(), { wrapper })

    await act(async () => { await result.current.verify() })
    expect(result.current.verifyResult).toEqual(ok)
    expect(result.current.busy).toBe(false)

    await act(async () => { await result.current.verify() })
    expect(result.current.error).toBe('链断了')
    expect(result.current.busy).toBe(false)
  })

  it('refresh 使审计记录失效；changeOperator 同步本地存储', () => {
    const { result } = renderHook(() => useAudit(), { wrapper })
    act(() => result.current.refresh())
    expect(invalidateQueries).toHaveBeenCalled()
    act(() => result.current.changeOperator('张三'))
    expect(result.current.operator).toBe('张三')
    expect(localStorage.getItem('iec104_operator')).toBe('张三')
  })

  it('无记录时给空数组，不把 undefined 泄漏给视图', () => {
    qhooks.useAuditRecordsQuery.mockReturnValue({ data: undefined, isLoading: true })
    const { result } = renderHook(() => useAudit(), { wrapper })
    expect(result.current.records).toEqual([])
    expect(result.current.loading).toBe(true)
  })
})

describe('useSniffer（WP9）', () => {
  it('start 后 refresh；后端 ok=false（HTTP 200）原样呈现错误', async () => {
    api.sniff.start.mockResolvedValueOnce({ ok: false, error: '需要 Npcap 权限' })
    const { result } = renderHook(() => useSniffer(), { wrapper })
    await act(async () => { result.current.actions.start() })
    await waitFor(() => expect(result.current.error).toBe('需要 Npcap 权限'))
    expect(invalidateQueries).toHaveBeenCalled()
  })

  it('stop 成功后 running/frames 从查询快照派生；异常落到 error', async () => {
    api.sniff.stop.mockRejectedValueOnce(new Error('未在运行'))
    qhooks.useSniffQuery.mockReturnValue({
      data: { running: true, frames: 12, stats: { rx: 12 }, capability: { ok: true } },
    })
    const { result } = renderHook(() => useSniffer(), { wrapper })
    expect(result.current.running).toBe(true)
    expect(result.current.frames).toBe(12)

    await act(async () => { result.current.actions.stop() })
    await waitFor(() => expect(result.current.error).toBe('未在运行'))
    expect(result.current.busy).toBe(false)
  })

  it('无状态快照时给安全默认值', () => {
    qhooks.useSniffQuery.mockReturnValue({ data: undefined })
    const { result } = renderHook(() => useSniffer(), { wrapper })
    expect(result.current.running).toBe(false)
    expect(result.current.frames).toBe(0)
  })
})

describe('useProfiles（WP5）', () => {
  it('首次取列表自动选中活动方案', () => {
    qhooks.useProfilesQuery.mockReturnValue({
      data: { profiles: [{ name: '现场A' }], active: '现场A' }, isLoading: false,
    })
    const { result } = renderHook(() => useProfiles(), { wrapper })
    expect(result.current.selected).toBe('现场A')
    expect(result.current.active).toBe('现场A')
  })

  it('save 空名字直接拦截（不调 API）；正常保存返回方案名', async () => {
    api.profiles.save.mockResolvedValue({ name: '方案1', ok: true })
    const { result } = renderHook(() => useProfiles(), { wrapper })
    act(() => result.current.actions.save('  '))
    expect(api.profiles.save).not.toHaveBeenCalled()
    expect(result.current.error).toBe('profiles.nameRequired')

    await act(async () => { result.current.actions.save(' 方案1 ') })
    expect(api.profiles.save).toHaveBeenCalledWith('方案1')
    expect(result.current.selected).toBe('方案1')
  })

  it('apply 拼接应用项；remove 清空选择；restore 无活动方案静默', async () => {
    api.profiles.apply.mockResolvedValue({ name: 'A', applied: ['host', 'ca'], ok: true })
    api.profiles.remove.mockResolvedValue({ ok: true })
    api.profiles.restore.mockRejectedValueOnce(new Error('no active'))
    const { result } = renderHook(() => useProfiles(), { wrapper })

    await act(async () => { result.current.actions.apply('A') })
    expect(result.current.message).toBe('A · host, ca')

    await act(async () => { result.current.actions.remove('A') })
    expect(result.current.selected).toBe('')

    await act(async () => { await result.current.actions.restore() })
    expect(result.current.error).toBe('')
  })

  it('summaryOf 按可用字段拼接，缺字段不产生 undefined 片段', () => {
    const { result } = renderHook(() => useProfiles(), { wrapper })
    expect(result.current.actions.summaryOf({
      name: 'X', summary: { mode: 'master', host: '127.0.0.1', port: 2404,
        common_addr: 1, ca_length: 2, ioa_length: 3, cot_length: 2, point_table: 'pt.yaml' },
    } as never)).toContain('CA=1')
    expect(result.current.actions.summaryOf({
      name: 'Y', summary: {},
    } as never)).toBe('')
  })

  it('importText 空名字拦截，正常导入走 importYaml', async () => {
    api.profiles.importYaml.mockResolvedValue({ name: 'Z', ok: true })
    const { result } = renderHook(() => useProfiles(), { wrapper })
    act(() => result.current.actions.importText('', 'a: 1'))
    expect(api.profiles.importYaml).not.toHaveBeenCalled()
    await act(async () => { result.current.actions.importText(' Z ', 'a: 1') })
    expect(api.profiles.importYaml).toHaveBeenCalledWith('Z', 'a: 1')
  })
})

describe('useCommission（WP2）', () => {
  it('create 的期望值按 bool > number > string 解析，command_ioas 只收合法数字', async () => {
    api.commission.create.mockResolvedValue({ session: { id: 's1', items: [], summary: {} } })
    const { result } = renderHook(() => useCommission(), { wrapper })

    act(() => {
      result.current.setNewName('验收1')
      result.current.setOperator('张三')
      result.current.toggle(1001)
      result.current.setDraft(1001, { value: 'ON' })
      result.current.setDraft(1002, { value: '42.5' })
      result.current.setDraft(1003, { value: '自定义' })
      result.current.setDraft(1004, { value: 'OFF', commandIoa: '20001' })
      result.current.setDraft(1005, { value: 'true', commandIoa: 'nan' })
    })
    await act(async () => { result.current.actions.create() })

    const body = api.commission.create.mock.calls[0][0]
    expect(body.name).toBe('验收1')
    expect(body.operator).toBe('张三')
    expect(body.ioas).toEqual([1001])
    expect(body.expected).toEqual({
      1001: true, 1002: 42.5, 1003: '自定义', 1004: false, 1005: true,
    })
    expect(body.command_ioas).toEqual({ 1004: 20001 })
    expect(result.current.activeId).toBe('s1')
    expect(result.current.drafts).toEqual({})
  })

  it('run/stop/remove/verdict 无 activeId 时零请求；有 id 时走对应端点', async () => {
    api.commission.run.mockResolvedValue({ ok: true })
    api.commission.stop.mockResolvedValue({ ok: true })
    api.commission.delete.mockResolvedValue({ ok: true })
    api.commission.verdict.mockResolvedValue({ ok: true })
    const { result } = renderHook(() => useCommission(), { wrapper })

    act(() => {
      result.current.actions.run()
      result.current.actions.stop()
      result.current.actions.remove()
      result.current.actions.setVerdict({ ioa: 1 } as never, 'pass', '')
    })
    expect(api.commission.run).not.toHaveBeenCalled()

    act(() => result.current.setActiveId('s2'))
    act(() => {
      result.current.actions.run()
      result.current.actions.stop()
      result.current.actions.setVerdict({ ioa: 7 } as never, 'fail', '偏差大')
    })
    await waitFor(() => expect(api.commission.run).toHaveBeenCalledWith('s2', ''))
    expect(api.commission.stop).toHaveBeenCalledWith('s2')
    expect(api.commission.verdict).toHaveBeenCalledWith('s2', {
      ioa: 7, verdict: 'fail', note: '偏差大', operator: '',
    })
  })

  it('toggle/selectAll/evidenceMap 与 detail 快照一致；API 失败落到 error', async () => {
    api.commission.create.mockRejectedValueOnce(new Error('会话数超限'))
    qhooks.useCommissionSessionQuery.mockReturnValue({
      data: { session: { items: [{ ioa: 9, verdict: 'pass' }], summary: { total: 1 } } },
    })
    const { result } = renderHook(() => useCommission(), { wrapper })

    act(() => result.current.toggle(1))
    act(() => result.current.toggle(1))
    act(() => result.current.selectAll([{ ioa: 9 }, { ioa: 10 }] as never))
    expect([...result.current.selected].sort((a, b) => a - b)).toEqual([9, 10])
    expect(result.current.evidenceMap.get(9)?.verdict).toBe('pass')

    await act(async () => { result.current.actions.create() })
    expect(result.current.error).toBe('会话数超限')
    expect(result.current.busy).toBe(false)
  })

  it('sessions/detail 缺省时给空集合，running 由 status 派生', () => {
    qhooks.useCommissionSessionsQuery.mockReturnValue({ data: undefined })
    qhooks.useCommissionSessionQuery.mockReturnValue({ data: undefined })
    const { result } = renderHook(() => useCommission(), { wrapper })
    expect(result.current.sessions).toEqual([])
    expect(result.current.items).toEqual([])
    expect(result.current.running).toBe(false)
  })
})
