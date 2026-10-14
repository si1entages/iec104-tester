/**
 * REST 客户端：与 aiohttp 后端同源，无需拼 BASE（dev 期由 vite 代理 /api）。
 * 契约：HTTP 200 + JSON `{ok, ...}`；失败含 `error` 字符串（见 api_contract.md）。
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
  return `HTTP ${status}`
}

async function request<T>(method: string, path: string, init?: {
  params?: Record<string, QueryValue>
  body?: unknown
}): Promise<T> {
  const url = buildUrl(path, init?.params)
  const headers: Record<string, string> = {}
  const options: RequestInit = { method, headers }
  if (init?.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(init.body)
  }
  const res = await fetch(url, options)
  const body = await readBody(res)
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status))
  return body as T
}

export function apiGet<T>(path: string, params?: Record<string, QueryValue>): Promise<T> {
  return request<T>('GET', path, { params })
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('POST', path, { body: body ?? {} })
}

/** 文本类响应（YAML / CSV）。 */
export async function apiGetText(path: string, params?: Record<string, QueryValue>): Promise<string> {
  const res = await fetch(buildUrl(path, params))
  const text = await res.text()
  if (!res.ok) throw new ApiError(res.status, errorMessage(text, res.status))
  return text
}
