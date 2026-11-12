/** 工程配置方案卡片的共享逻辑（WP5）——Carbon / PF 两套件复用。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../api/endpoints'
import { useT } from '../i18n'
import { queryKeys, useProfilesQuery } from '../api/queries'
import type { ProfileInfo } from '../api/types'

export function useProfiles() {
  const t = useT()
  const client = useQueryClient()
  const profilesQuery = useProfilesQuery()
  const [selected, setSelected] = useState('')
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const profiles = profilesQuery.data?.profiles ?? []
  const active = profilesQuery.data?.active ?? ''

  // 首次拿到列表时：优先选中「活动方案」（后端记录的上次应用项）——
  // 这就是"刷新后参数还原"的落点。
  const seeded = useRef(false)
  useEffect(() => {
    if (seeded.current || selected) return
    if (active) {
      setSelected(active)
      seeded.current = true
    } else if (profiles.length > 0) {
      setSelected(profiles[0].name)
      seeded.current = true
    }
  }, [active, profiles, selected])

  const refresh = useCallback(() => {
    void client.invalidateQueries({ queryKey: queryKeys.profiles() })
    // 方案会改连接/阈值 → 状态与告警卡片要跟着刷新
    void client.invalidateQueries({ queryKey: queryKeys.status() })
    void client.invalidateQueries({ queryKey: queryKeys.alarms() })
  }, [client])

  const guard = useCallback(async (fn: () => Promise<string>) => {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      setMessage(await fn())
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [refresh])

  /** 应用方案（切换现场口径） */
  const apply = useCallback((name: string) => {
    if (!name) return
    void guard(async () => {
      const r = await api.profiles.apply(name)
      setSelected(name)
      return `${r.name} · ${r.applied.join(', ')}`
    })
  }, [guard])

  /** 保存当前生效参数到方案（新建或覆盖） */
  const save = useCallback((name: string) => {
    const target = (name || '').trim()
    if (!target) {
      setError(t('profiles.nameRequired'))
      return
    }
    void guard(async () => {
      const r = await api.profiles.save(target)
      setSelected(r.name)
      setNewName('')
      return r.name
    })
  }, [guard, t])

  /** 另存为：把当前参数存成新名字 */
  const saveAs = useCallback((name: string) => save(name), [save])

  const remove = useCallback((name: string) => {
    if (!name) return
    void guard(async () => {
      await api.profiles.remove(name)
      setSelected('')
      seeded.current = true
      return name
    })
  }, [guard])

  /** 浏览器刷新后恢复上次方案（挂载时一次；无活动方案则静默跳过） */
  const restore = useCallback(async () => {
    try {
      const r = await api.profiles.restore()
      if (r.ok) {
        setSelected(r.name)
        refresh()
      }
    } catch {
      // 无活动方案/未启用：静默（这是常态，不是错误）
    }
  }, [refresh])

  const importText = useCallback((name: string, text: string) => {
    const target = (name || '').trim()
    if (!target) {
      setError(t('profiles.nameRequired'))
      return
    }
    void guard(async () => {
      const r = await api.profiles.importYaml(target, text)
      setSelected(r.name)
      return r.name
    })
  }, [guard, t])

  const summaryOf = useCallback((p: ProfileInfo): string => {
    const s = p.summary
    const bits: string[] = []
    if (s.mode) bits.push(s.mode)
    if (s.host) bits.push(`${s.host}:${s.port ?? '-'}`)
    if (s.common_addr !== null && s.common_addr !== undefined) bits.push(`CA=${s.common_addr}`)
    if (s.ca_length) bits.push(`${s.ca_length}/${s.ioa_length}/${s.cot_length}B`)
    if (s.point_table) bits.push(s.point_table)
    return bits.join(' · ')
  }, [])

  return {
    profiles, active, loading: profilesQuery.isLoading,
    selected, setSelected, newName, setNewName,
    busy, error, message, refresh,
    actions: { apply, save, saveAs, remove, restore, importText, summaryOf },
  }
}
