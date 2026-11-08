import { useEffect } from 'react'

import { setSlaveApiPrefix } from '../api/client'
import { useSchemaQuery } from '../api/queries'
import { describeSchemaMismatch } from '../api/schema'
import { useUiStore } from '../store/uiStore'

/**
 * 启动期契约版本协商（T18）：探测 `GET /api/schema`，
 * 版本不一致时只记录降级告警，界面照常渲染。
 *
 * 同时读取 `roles` / `slaveApiPrefix`：合并模式下子站 API/WS 在 `/slave` 前缀，
 * 单角色模式下前缀为空。
 */
export function useSchemaHandshake(): void {
  const { data } = useSchemaQuery()
  const setSchemaWarning = useUiStore((s) => s.setSchemaWarning)
  const setAvailableRoles = useUiStore((s) => s.setAvailableRoles)

  useEffect(() => {
    if (!data) return
    setSchemaWarning(describeSchemaMismatch(data.schemaVersion))
    setSlaveApiPrefix(data.slaveApiPrefix ?? null)
    if (data.roles?.length) setAvailableRoles(data.roles)
  }, [data, setSchemaWarning, setAvailableRoles])
}
