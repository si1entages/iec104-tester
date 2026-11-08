/**
 * T15 e2e 共享工具：后端编排（HTTP 设置）、点表注入、UI 导航与请求捕获。
 *
 * 端点分配与 `qa_*.py` 惯例一致：主站 UI 8765 / 子站 UI 8766 / IEC 2404。
 * 本机已有运行中的实例占用默认端口时，可用 `E2E_PORT_OFFSET=10` 整体平移
 * （见 playwright.config.ts 的 webServer 命令，两端必须使用同一个值）。
 */
import type { APIRequestContext, Page } from '@playwright/test'
import { expect } from '@playwright/test'

export const PORT_OFFSET = Number(process.env.E2E_PORT_OFFSET ?? 0)

export const MASTER = `http://127.0.0.1:${8765 + PORT_OFFSET}`
export const SLAVE = `http://127.0.0.1:${8766 + PORT_OFFSET}`
/** 合并模式：一个进程、一个端口，同时提供主站 + /slave 子站 */
export const COMBINED = `http://127.0.0.1:${8767 + PORT_OFFSET}`
/** 视觉基线专用：单角色主站、无引擎/无帧/无历史，内容可复现 */
export const VISUAL = `http://127.0.0.1:${8768 + PORT_OFFSET}`
export const IEC_PORT = 2404

/**
 * 功能用例统一跑在 **PatternFly 套件**上（这些用例的 DOM 断言按 PF 编写）。
 * Carbon 是产品默认套件，其外壳/切换/主题覆盖见 ui-kit.spec；
 * 两者共享同一数据层与业务逻辑，PF 用例即可覆盖核心流程。
 */
export const SPECS_KIT = 'pf'

/** `/app/?kit=<SPECS_KIT>#<hash>`：功能用例的统一入口 URL */
export function appUrl(base: string, hash = ''): string {
  return `${base}/app/?kit=${SPECS_KIT}${hash ? `#${hash}` : ''}`
}

export interface CapturedRequest {
  path: string
  body: Record<string, unknown> | null
}

/** 捕获页面发出的 /api/* POST（含请求体），供「请求体正确性」断言使用 */
export function capturePosts(page: Page): CapturedRequest[] {
  const posts: CapturedRequest[] = []
  page.on('request', (req) => {
    if (req.method() !== 'POST' || !req.url().includes('/api/')) return
    let body: Record<string, unknown> | null = null
    try {
      body = req.postDataJSON() as Record<string, unknown>
    } catch {
      body = null
    }
    posts.push({ path: new URL(req.url()).pathname, body })
  })
  return posts
}

/**
 * 生成 e2e 点表 YAML：
 *  - 2000 个批量 YX（IOA 10000+）：虚拟滚动断言「DOM 行数远小于总行数」；
 *  - 低 IOA 的 YX/YC/YK/YM/STEP：命令面板与置数面板的确定性目标。
 */
export function buildPointsYaml(): string {
  const lines: string[] = ['station_name: E2E Playwright', 'common_addr: 1', 'yx:']
  lines.push(
    '- ioa: 1',
    '  name: YX_SINGLE_1',
    '  group: 1',
    '  enabled: true',
    '  type: single',
    '  initial_value: false',
    '  inverted: false',
  )
  for (let i = 0; i < 2000; i += 1) {
    lines.push(
      `- ioa: ${10000 + i}`,
      `  name: YX_BULK_${String(i).padStart(4, '0')}`,
      '  group: 9',
      '  enabled: true',
      '  type: single',
      '  initial_value: false',
      '  inverted: false',
    )
  }
  lines.push(
    'yc:',
    '- ioa: 101',
    '  name: YC_101',
    '  group: 1',
    '  enabled: true',
    '  type: short_float',
    '  initial_value: 0.0',
    '  min_value: -99999.0',
    '  max_value: 99999.0',
    '  dead_band: 0.0',
    "  unit: ''",
    '  scale: 1.0',
    '  offset: 0.0',
    '  decimal_places: 2',
    'yk:',
    '- ioa: 201',
    '  name: YK_SBO_TRUE',
    '  group: 1',
    '  enabled: true',
    '  type: single',
    '  sbo: true',
    '  timeout_ms: 10000',
    '- ioa: 202',
    '  name: YK_SBO_FALSE',
    '  group: 1',
    '  enabled: true',
    '  type: single',
    '  sbo: false',
    '  timeout_ms: 10000',
    'ym:',
    '- ioa: 301',
    '  name: YM_301',
    '  group: 1',
    '  enabled: true',
    '  initial_value: 0',
    'step:',
    '- ioa: 401',
    '  name: STEP_401',
    '  group: 1',
    '  enabled: true',
    '  initial_value: 0',
    '  min_value: -64',
    '  max_value: 63',
    '  step_size: 1',
    '  transient: false',
  )
  return lines.join('\n')
}

/** 向某端注入点表 */
export async function injectPoints(request: APIRequestContext, base: string): Promise<void> {
  const res = await request.post(`${base}/api/points/yaml`, {
    headers: { 'Content-Type': 'text/yaml' },
    data: buildPointsYaml(),
  })
  expect(res.ok(), `注入点表失败: ${base}`).toBeTruthy()
}

/** 停掉两端引擎（幂等，容错：服务可能本来就没起） */
export async function stopEngines(request: APIRequestContext): Promise<void> {
  for (const base of [MASTER, SLAVE]) {
    await request.post(`${base}/api/master/stop`).catch(() => {})
    await request.post(`${base}/api/slave/stop`).catch(() => {})
  }
}

/** 打开某端 UI 并切换到指定页（点侧边菜单，顺带覆盖导航入口） */
export async function gotoApp(page: Page, base: string, menu: string): Promise<Page> {
  await page.goto(appUrl(base), { waitUntil: 'domcontentloaded' })
  // PatternFly 侧栏：NavItem 渲染为 <a class="pf-v6-c-nav__link">，用文本过滤
  const item = page.locator('.pf-v6-c-nav__link').filter({ hasText: menu }).first()
  await item.waitFor()
  await item.click()
  return page
}

/** 轮询某端 /api/status 直到断言成立 */
export async function waitForStatus(
  request: APIRequestContext,
  base: string,
  predicate: (status: Record<string, unknown>) => boolean,
  timeoutMs = 15_000,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + timeoutMs
  let last: Record<string, unknown> = {}
  while (Date.now() < deadline) {
    try {
      const res = await request.get(`${base}/api/status`)
      last = (await res.json()) as Record<string, unknown>
      if (predicate(last)) return last
    } catch {
      // 服务暂不可达，继续轮询
    }
    await new Promise((r) => setTimeout(r, 250))
  }
  throw new Error(`waitForStatus 超时: ${base} 最后状态=${JSON.stringify(last)}`)
}
