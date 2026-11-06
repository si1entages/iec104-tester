/**
 * REST 客户端底层（T11）：与 aiohttp 后端同源，无需拼 BASE（dev 期由 vite 代理 /api）。
 * 契约：HTTP 200 + JSON `{ok, ...}`；失败含 `error` 字符串；参数非法为 400。
 * 权威契约见 `webui/api_contract.md`。
 */

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export type QueryValue = string | number | boolean | null | undefined

/** 访问令牌在 localStorage 的键（B7：服务端 --auth-token 启用时使用） */
export const TOKEN_KEY = 'iec104_token'

/** 读取本地保存的访问令牌（无 / 存储不可用时返回空串） */
export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

/** 拼接查询串；空值（undefined/null/空串）自动跳过。 */
export function buildUrl(path: string, params?: Record<string, QueryValue>): string {
  const url = path.startsWith('/') ? path : `/${path}`
  if (!params) return url
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.append(key, String(value))
  }
  const qs = search.toString()
  return qs ? `${url}?${qs}` : url
}

async function readBody(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  const contentType = res.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    try {
      return JSON.parse(text)
    } catch {
      return text
    }
  }
  return text
}

function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'error' in body) {
    const err = (body as { error?: unknown }).error
    if (typeof err === 'string' && err) return err
  }
  if (typeof body === 'string' && body.trim()) return body.trim().slice(0, 300)
  return `HTTP ${status}`
}

interface RequestOptions {
  params?: Record<string, QueryValue>
  /** JSON 请求体 */
  json?: unknown
  /** 原始文本请求体（用于 /api/points/yaml、/api/points/import） */
  text?: string
  contentType?: string
}

async function send(method: string, path: string, options: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const init: RequestInit = { method, headers }
  if (options.text !== undefined) {
    headers['Content-Type'] = options.contentType ?? 'text/plain;charset=utf-8'
    init.body = options.text
  } else if (options.json !== undefined || method === 'POST') {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(options.json ?? {})
  }
  return fetch(buildUrl(path, options.params), init)
}

async function asJson<T>(res: Response): Promise<T> {
  const body = await readBody(res)
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status))
  return body as T
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, QueryValue>,
): Promise<T> {
  return asJson<T>(await send('GET', path, { params }))
}

export async function apiPost<T>(path: string, json?: unknown): Promise<T> {
  return asJson<T>(await send('POST', path, { json }))
}

/** POST 原始文本（YAML / 点表导入），响应仍是 JSON。 */
export async function apiPostText<T>(path: string, text: string): Promise<T> {
  return asJson<T>(await send('POST', path, { text }))
}

/** 取文本响应（YAML / CSV）。 */
export async function apiGetText(
  path: string,
  params?: Record<string, QueryValue>,
): Promise<string> {
  const res = await send('GET', path, { params })
  const text = await res.text()
  if (!res.ok) throw new ApiError(res.status, errorMessage(text, res.status))
  return text
}
