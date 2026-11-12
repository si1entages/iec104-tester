/** 对点/传动验收页的共享状态逻辑（WP2）——Carbon / PF 两套件复用。 */

import { useCallback, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../api/endpoints'
import { queryKeys, useCommissionSessionQuery, useCommissionSessionsQuery, usePointsQuery } from '../api/queries'
import type { CommissionItem, CommissionVerdict, Point } from '../api/types'

export interface ExpectedDraft {
  value: string
  commandIoa: string
}

export function useCommission() {
  const client = useQueryClient()
  const sessionsQuery = useCommissionSessionsQuery()
  const pointsQuery = usePointsQuery()
  const [activeId, setActiveId] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [operator, setOperator] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [drafts, setDrafts] = useState<Record<number, ExpectedDraft>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const sessions = sessionsQuery.data?.sessions ?? []
  const status = sessionsQuery.data?.status
  const running = Boolean(status?.running)
  const detail = useCommissionSessionQuery(activeId, running)

  const refresh = useCallback(() => {
    void client.invalidateQueries({ queryKey: queryKeys.commissionSessions() })
    if (activeId) void client.invalidateQueries({ queryKey: queryKeys.commissionSession(activeId) })
  }, [client, activeId])

  const guard = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [refresh])

  const create = useCallback(() => guard(async () => {
    const expected: Record<string, number | boolean | string> = {}
    const command_ioas: Record<string, number> = {}
    for (const [k, d] of Object.entries(drafts)) {
      if (d.value.trim() !== '') {
        const raw: string = d.value.trim()
        // bool > number > string
        if (raw === 'true' || raw === 'ON' || raw === '1') expected[k] = true
        else if (raw === 'false' || raw === 'OFF' || raw === '0') expected[k] = false
        else expected[k] = Number.isNaN(Number(raw)) ? raw : Number(raw)
      }
      if (d.commandIoa.trim() !== '' && !Number.isNaN(Number(d.commandIoa))) {
        command_ioas[k] = Number(d.commandIoa)
      }
    }
    const out = await api.commission.create({
      name: newName,
      operator,
      ioas: selected.size > 0 ? [...selected] : undefined,
      expected,
      command_ioas: Object.keys(command_ioas).length ? command_ioas : undefined,
    })
    setActiveId(out.session.id)
    setNewName('')
    setDrafts({})
  }), [guard, drafts, newName, operator, selected])

  const run = useCallback(() => {
    if (!activeId) return
    void guard(() => api.commission.run(activeId, operator))
  }, [guard, activeId, operator])

  const stop = useCallback(() => {
    if (!activeId) return
    void guard(() => api.commission.stop(activeId))
  }, [guard, activeId])

  const remove = useCallback(() => {
    if (!activeId) return
    void guard(async () => {
      await api.commission.delete(activeId)
      setActiveId(null)
    })
  }, [guard, activeId])

  const setVerdict = useCallback((item: CommissionItem, verdict: CommissionVerdict, note: string) => {
    if (!activeId) return
    void guard(() => api.commission.verdict(activeId, {
      ioa: item.ioa, verdict, note, operator,
    }))
  }, [guard, activeId, operator])

  const toggle = useCallback((ioa: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(ioa)) next.delete(ioa)
      else next.add(ioa)
      return next
    })
  }, [])

  const selectAll = useCallback((points: Point[]) => {
    setSelected(new Set(points.map((p) => p.ioa)))
  }, [])

  const setDraft = useCallback((ioa: number, patch: Partial<ExpectedDraft>) => {
    setDrafts((prev) => {
      const cur = prev[ioa] ?? { value: '', commandIoa: '' }
      return {
        ...prev,
        [ioa]: {
          value: patch.value !== undefined ? patch.value : cur.value,
          commandIoa: patch.commandIoa !== undefined ? patch.commandIoa : cur.commandIoa,
        },
      }
    })
  }, [])

  const items = detail.data?.session.items ?? []
  const summary = detail.data?.session.summary
  const evidenceMap = useMemo(() => {
    const m = new Map<number, CommissionItem>()
    for (const it of items) m.set(it.ioa, it)
    return m
  }, [items])

  return {
    sessions, status, running, detail, activeId, setActiveId,
    newName, setNewName, operator, setOperator,
    selected, setSelected, drafts, setDraft, toggle, selectAll,
    busy, error, points: pointsQuery.data ?? [], items, summary, evidenceMap,
    actions: { create, run, stop, remove, setVerdict, refresh },
  }
}
