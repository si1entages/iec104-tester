/**
 * 契约版本（T18）。必须与后端 `webui/events.py::SCHEMA_VERSION` 保持一致，
 * 由 `webui/contract_check.py` 自检强制校验。
 *
 * 递增规则（见 webui/api_contract.md §1）：
 *   - 破坏性变更（删字段 / 改类型 / 改语义）→ +1，前端必须适配
 *   - 纯新增可选字段 → 不递增，前端忽略未知字段
 */
import { tNow } from '../i18n'

export const SCHEMA_VERSION = 1

/** WS 消息信封中承载版本的键名（后端 /api/schema 的 wsSchemaKey 与此一致）。 */
export const SCHEMA_KEY = 'schemaVersion'

export function isSchemaMismatch(remote?: unknown): boolean {
  return typeof remote === 'number' && Number.isFinite(remote) && remote !== SCHEMA_VERSION
}

/** 生成给用户看的不匹配说明；未提供远端版本时返回 null（视为未知，不告警）。 */
export function describeSchemaMismatch(remote?: unknown): string | null {
  if (!isSchemaMismatch(remote)) return null
  return tNow('schema.mismatch', {
    remote: String(remote),
    local: String(SCHEMA_VERSION),
  })
}
