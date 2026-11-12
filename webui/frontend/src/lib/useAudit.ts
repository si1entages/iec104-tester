/** 操作审计页共享逻辑（WP4a）——Carbon / PF 两套件复用。 */

import { useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { getOperator, setOperator } from '../api/client'
import { api } from '../api/endpoints'
import { queryKeys, useAuditRecordsQuery } from '../api/queries'

export interface AuditVerifyResult {
  valid: boolean
  total: number
  broken_at: number | null
  reason: string
}

export function useAudit() {
  const client = useQueryClient()
  const recordsQuery = useAuditRecordsQuery()
  const [verifyResult, setVerifyResult] = useState<AuditVerifyResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [operator, setOperatorName] = useState(getOperator)

  const refresh = useCallback(() => {
    void client.invalidateQueries({ queryKey: queryKeys.auditRecords() })
  }, [client])

  const verify = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setVerifyResult(await api.audit.verify())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [])

  const changeOperator = useCallback((name: string) => {
    setOperatorName(name)
    setOperator(name)
  }, [])

  return {
    records: recordsQuery.data?.records ?? [],
    stats: recordsQuery.data?.stats,
    loading: recordsQuery.isLoading,
    verifyResult, verify,
    busy, error, refresh,
    operator, changeOperator,
  }
}
