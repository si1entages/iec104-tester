// i18n-ignore-file — 本文件只有契约校验的诊断错误文案（console/ErrorBoundary），无 UI 文案
/**
 * 极简运行时契约校验（零依赖）。
 *
 * 为什么不用 zod（沿用 `validate.ts` 的取舍）：本工程刻意压缩依赖面，
 * 契约校验只需要「形状判定 + 精确报错」，一个 200 行的组合子足够。
 *
 * 设计目标：
 *  - **类型可推断**：`Infer<typeof schema>` 直接得到响应类型，前端不存在
 *    “接口定义”和“运行时校验”两份真相；
 *  - **失败可定位**：抛出 `ApiContractError`，带 JSON 路径（`/segments[0].title`），
 *    比静默读 `undefined` 后显示“翻译失败”可诊断；
 *  - **宽进严出**：未知字段忽略（后端纯新增不破坏前端），必填字段缺失/类型不符
 *    直接失败；可选字段只在出现时校验。
 */

/** 响应与契约不符；`path` 是 JSON 路径，`received` 便于控制台/测试定位。 */
export class ApiContractError extends Error {
  readonly path: string
  readonly received: unknown

  constructor(path: string, detail: string, received: unknown) {
    super(`接口响应不符合契约 ${path}：${detail}`)
    this.name = 'ApiContractError'
    this.path = path
    this.received = received
  }
}

/** 一个可执行 schema；`_type` 仅参与类型推断，运行时不读。 */
export interface Schema<T> {
  readonly _type?: T
  parse(value: unknown, path: string): T
}

/** 可选字段包装（保留 `_optional` 标记，供对象推断 `?` 与运行时跳过）。 */
export interface OptionalSchema<T> extends Schema<T | undefined> {
  readonly _optional: true
}

export type Infer<S> = S extends Schema<infer T> ? T : never
export type InferObject<S extends Shape> = {
  [K in RequiredKeys<S>]: Infer<S[K]>
} & {
  [K in OptionalKeys<S>]?: Infer<S[K]>
}

type Shape = Record<string, Schema<unknown>>
type RequiredKeys<S extends Shape> = {
  [K in keyof S]-?: S[K] extends OptionalSchema<unknown> ? never : K
}[keyof S]
type OptionalKeys<S extends Shape> = {
  [K in keyof S]-?: S[K] extends OptionalSchema<unknown> ? K : never
}[keyof S]

function make<T>(fn: (value: unknown, path: string) => T): Schema<T> {
  return { parse: fn }
}

function typeName(value: unknown): string {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  return typeof value
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isOptional(schema: Schema<unknown>): schema is OptionalSchema<unknown> {
  return (schema as OptionalSchema<unknown>)._optional === true
}

// ── 基础类型 ───────────────────────────────────────────────────────────

export const str = (): Schema<string> =>
  make((value, path) => {
    if (typeof value !== 'string') throw new ApiContractError(path, `期望 string，实际 ${typeName(value)}`, value)
    return value
  })

export const num = (): Schema<number> =>
  make((value, path) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      throw new ApiContractError(path, `期望有限 number，实际 ${typeName(value)}`, value)
    }
    return value
  })

export const bool = (): Schema<boolean> =>
  make((value, path) => {
    if (typeof value !== 'boolean') throw new ApiContractError(path, `期望 boolean，实际 ${typeName(value)}`, value)
    return value
  })

export const unknown = (): Schema<unknown> => make((value) => value)

export const literal = <T extends string | number | boolean>(expected: T): Schema<T> =>
  make((value, path) => {
    if (value !== expected) throw new ApiContractError(path, `期望字面量 ${JSON.stringify(expected)}`, value)
    return expected
  })

export const enumOf = <T extends string>(...values: readonly T[]): Schema<T> =>
  make((value, path) => {
    if (typeof value === 'string' && (values as readonly string[]).includes(value)) return value as T
    throw new ApiContractError(path, `期望枚举 ${values.join(' | ')}，实际 ${JSON.stringify(value)}`, value)
  })

export const optional = <T>(inner: Schema<T>): OptionalSchema<T> => {
  const schema: OptionalSchema<T> = {
    _optional: true,
    parse: (value, path) => (value === undefined ? undefined : inner.parse(value, path)),
  }
  return schema
}

export const nullable = <T>(inner: Schema<T>): Schema<T | null> =>
  make((value, path) => (value === null ? null : inner.parse(value, path)))

/** 对象：必填键缺失直接失败；可选键缺失/undefined 跳过；未知键忽略。 */
export const obj = <S extends Shape>(shape: S): Schema<InferObject<S>> =>
  make((value, path) => {
    if (!isRecord(value)) throw new ApiContractError(path, `期望 object，实际 ${typeName(value)}`, value)
    for (const key of Object.keys(shape)) {
      const schema = shape[key]
      const present = Object.prototype.hasOwnProperty.call(value, key) && value[key] !== undefined
      if (!present) {
        if (isOptional(schema)) continue
        throw new ApiContractError(`${path}.${key}`, '必填字段缺失', undefined)
      }
      schema.parse(value[key], `${path}.${key}`)
    }
    // 返回原对象而非副本：高频端点（10 万点快照）每 5s 一次，
    // 复制会造成不必要的分配与 GC 抖动；校验只读、不改变语义。
    return value as InferObject<S>
  })

/** 对象 + 保留未知键（用于 `{ok, ...}` 这类开放响应）。 */
export const looseObj = <S extends Shape>(shape: S): Schema<InferObject<S> & Record<string, unknown>> => {
  const strict = obj(shape)
  return make((value, path) => {
    if (!isRecord(value)) throw new ApiContractError(path, `期望 object，实际 ${typeName(value)}`, value)
    strict.parse(value, path)
    return value as InferObject<S> & Record<string, unknown>
  })
}

export const arr = <T>(inner: Schema<T>): Schema<T[]> =>
  make((value, path) => {
    if (!Array.isArray(value)) throw new ApiContractError(path, `期望 array，实际 ${typeName(value)}`, value)
    for (let i = 0; i < value.length; i += 1) inner.parse(value[i], `${path}[${i}]`)
    return value as T[]
  })

export const dict = <T>(inner: Schema<T>): Schema<Record<string, T>> =>
  make((value, path) => {
    if (!isRecord(value)) throw new ApiContractError(path, `期望 object，实际 ${typeName(value)}`, value)
    for (const [key, item] of Object.entries(value)) inner.parse(item, `${path}.${key}`)
    return value as Record<string, T>
  })

/** 任一分支匹配即可（返回首个成功分支）。 */
export const unionOf = <S extends Schema<unknown>[]>(...schemas: S): Schema<Infer<S[number]>> =>
  make((value, path) => {
    const errors: string[] = []
    for (const schema of schemas) {
      try {
        return schema.parse(value, path) as Infer<S[number]>
      } catch (e) {
        errors.push(e instanceof Error ? e.message : String(e))
      }
    }
    throw new ApiContractError(path, `不匹配任何分支：${errors.join('；')}`, value)
  })

/** 在基础 schema 上追加业务约束（例如 ok=true 时必须带某字段）。 */
export const refined = <T>(inner: Schema<T>, check: (value: T, path: string) => void): Schema<T> =>
  make((value, path) => {
    const parsed = inner.parse(value, path)
    check(parsed, path)
    return parsed
  })
