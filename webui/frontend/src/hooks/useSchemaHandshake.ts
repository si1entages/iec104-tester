import { useEffect } from 'react'

import { useSchemaQuery } from '../api/queries'
import { describeSchemaMismatch } from '../api/schema'
import { useUiStore } from '../store/uiStore'

/**
 * 启动期契约版本协商（T18）：探测 `GET /api/schema`，
 * 版本不一致时只记录降级告警，界面照常渲染。
 */
export function useSchemaHandshake(): void {
  const { data } = useSchemaQuery()
  const setSchemaWarning = useUiStore((s) => s.setSchemaWarning)

  useEffect(() => {
    if (!data) return
    setSchemaWarning(describeSchemaMismatch(data.schemaVersion))
  }, [data, setSchemaWarning])
}
