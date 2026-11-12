/** 点表在线编辑的共享逻辑（WP10a）——Carbon / PF 复用。 */

import { useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../api/endpoints'
import { queryKeys } from '../api/queries'
import type { Point, PointUpsertRequest } from '../api/types'

export interface PointDraft {
  ioa: string
  name: string
  group: string
  enabled: boolean
  type: PointUpsertRequest['type']
  subtype: string
  unit: string
  min_value: string
  max_value: string
  decimal_places: string
  sbo: boolean
}

/** 从现有点生成编辑草稿；null 表示「新增」 */
export function draftFromPoint(p: Point | null): PointDraft {
  if (!p) {
    return {
      ioa: '', name: '', group: '1', enabled: true, type: 'YX',
      subtype: '', unit: '', min_value: '', max_value: '',
      decimal_places: '', sbo: false,
    }
  }
  const validTypes = ['YX', 'YC', 'YK', 'YM', 'STEP']
  return {
    ioa: String(p.ioa),
    name: p.name ?? '',
    group: String(p.group ?? 1),
    enabled: p.enabled,
    type: (validTypes.includes(p.type) ? p.type : 'YX') as PointDraft['type'],
    subtype: p.subtype ?? '',
    unit: p.unit ?? '',
    min_value: p.min_value !== undefined ? String(p.min_value) : '',
    max_value: p.max_value !== undefined ? String(p.max_value) : '',
    decimal_places: p.decimal_places !== undefined ? String(p.decimal_places) : '',
    sbo: Boolean(p.sbo),
  }
}

/** 按类型把草稿收敛成后端 point 字段（只带该类型有意义的键） */
export function draftToPayload(d: PointDraft): PointUpsertRequest['point'] {
  const out: PointUpsertRequest['point'] = {
    ioa: Number(d.ioa),
    name: d.name,
    group: Number(d.group) || 1,
    enabled: d.enabled,
  }
  if (d.type === 'YX') {
    if (d.subtype) out.subtype = d.subtype
  } else if (d.type === 'YC') {
    if (d.subtype) out.subtype = d.subtype
    if (d.unit) out.unit = d.unit
    if (d.min_value !== '') out.min_value = Number(d.min_value)
    if (d.max_value !== '') out.max_value = Number(d.max_value)
    if (d.decimal_places !== '') out.decimal_places = Number(d.decimal_places)
  } else if (d.type === 'YK') {
    out.sbo = d.sbo
  } else if (d.type === 'STEP') {
    if (d.min_value !== '') out.min_value = Number(d.min_value)
    if (d.max_value !== '') out.max_value = Number(d.max_value)
  }
  return out
}

/** Validation error codes; the UI layer translates them via i18n. */
export type PointEditError =
  | 'ioa'
  | 'group'
  | 'min'
  | 'max'
  | 'decimals'
  | ''

/** Local validation: returns an error code, empty string means valid. */
export function validateDraft(d: PointDraft): PointEditError {
  if (!/^\d+$/.test(d.ioa.trim()) || Number(d.ioa) < 0) return 'ioa'
  if (d.group.trim() !== '' && !/^\d+$/.test(d.group.trim())) return 'group'
  if (d.min_value !== '' && Number.isNaN(Number(d.min_value))) return 'min'
  if (d.max_value !== '' && Number.isNaN(Number(d.max_value))) return 'max'
  if (d.decimal_places !== '' && Number.isNaN(Number(d.decimal_places))) return 'decimals'
  return ''
}

export function usePointEdit() {
  const client = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    void client.invalidateQueries({ queryKey: queryKeys.points() })
  }, [client])

  const save = useCallback(async (d: PointDraft): Promise<boolean> => {
    setError('')
    const bad = validateDraft(d)
    if (bad) {
      // 错误码由界面层翻译（本模块保持与 i18n 解耦）
      setError(`pointEdit.err.${bad}`)
      return false
    }
    setBusy(true)
    try {
      const r = await api.pointEdit.upsert({
        type: d.type, point: draftToPayload(d),
      })
      if (!r.ok) {
        setError(r.error ?? 'pointEdit.err.saveFailed')
        return false
      }
      refresh()
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setBusy(false)
    }
  }, [refresh])

  const remove = useCallback(async (ptype: string, ioa: number): Promise<boolean> => {
    setBusy(true)
    setError('')
    try {
      const r = await api.pointEdit.remove(ptype, ioa)
      if (!r.ok) {
        setError(r.error ?? 'pointEdit.err.deleteFailed')
        return false
      }
      refresh()
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setBusy(false)
    }
  }, [refresh])

  return { save, remove, busy, error, setError, refresh }
}
