/**
 * UI 自动巡检（第一类：可自动发现）
 *
 * 扫描范围（合并模式 8767，单进程双角色）：
 *  - 8 个侧边菜单页 × 3 个桌面视口（1680 / 1366 / 1280）；
 *  - 主站/子站工作台的页签全部点开；
 *  - 中文 + 英文两套文案；
 *  - 控制台 error / 未捕获异常 / API 4xx·5xx / 契约校验失败；
 *  - Card 标题、按钮、页签、表单标签、分段控件、提示文案的裁切（scrollWidth > clientWidth）；
 *  - 页面级横向滚动，以及关键控件超出视口（表格内横向滚动区域豁免）；
 *  - 界面上直接漏出的 i18n key（如 `menu.status`）。
 *
 * 说明：这是「布局/契约/运行时」巡检，不判断业务语义（例如某开关“应该”能做什么）。
 * 截图落在 `tests/e2e/.playwright-artifacts/audit/`，便于人工复核有意省略的文本。
 */
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'

import { COMBINED, MASTER, SLAVE , appUrl } from './helpers'

test.describe.configure({ mode: 'serial' })

const PAGES = [
  { menu: /主站工作台/, marker: '连接与命令', key: 'master' },
  { menu: /子站工作台/, marker: '子站启动与状态', key: 'slave' },
  { menu: /多站/, marker: null, key: 'multi' },
  { menu: /状态总览/, marker: null, key: 'status' },
  { menu: /日志/, marker: null, key: 'logs' },
  { menu: /历史/, marker: null, key: 'history' },
  { menu: /报文抓包/, marker: null, key: 'capture' },
  { menu: /自动化测试/, marker: null, key: 'tests' },
] as const

const VIEWPORTS = [
  { width: 1680, height: 950 },
  { width: 1366, height: 768 },
  { width: 1280, height: 800 },
] as const

interface AuditIssue {
  kind: string
  page: string
  viewport: string
  lang: string
  detail: string
}

interface RuntimeIssue {
  label: string
  detail: string
}

interface AuditState {
  label: string
  viewport: string
  lang: string
  runtime: RuntimeIssue[]
  issues: AuditIssue[]
}

function attachWatchers(page: Page, state: AuditState): void {
  page.on('console', (msg) => {
    if (msg.type() !== 'error' && msg.type() !== 'warning') return
    const text = msg.text()
    const source = msg.location().url
    // API 的 4xx/5xx 由 response 监听统一记录；静态资源 404 必须保留，
    // 否则打包漏文件/哈希引用错会被静默放过。
    if (text.includes('Failed to load resource') && source.includes('/api/')) return
    const level = msg.type() === 'warning' ? 'console.warn' : 'console.error'
    state.runtime.push({ label: state.label, detail: `${level}: ${text} (${source})` })
  })
  page.on('pageerror', (err) => {
    state.runtime.push({ label: state.label, detail: `pageerror: ${err.message}` })
  })
  page.on('response', (res) => {
    const url = res.url()
    if (!url.includes('/api/') || res.status() < 400) return
    state.runtime.push({
      label: state.label,
      detail: `HTTP ${res.status()} ${res.request().method()} ${new URL(url).pathname}`,
    })
  })
  page.on('requestfailed', (req) => {
    const url = req.url()
    if (!url.includes('/api/')) return
    const reason = req.failure()?.errorText ?? ''
    if (reason.includes('ERR_ABORTED')) return // 切页取消在途请求属正常
    state.runtime.push({
      label: state.label,
      detail: `requestfailed ${new URL(url).pathname}: ${reason}`,
    })
  })
}

/** 在页面内执行的 DOM 巡检（返回可读问题列表） */
async function auditDom(page: Page): Promise<{
  clipped: string[]
  outside: string[]
  hscroll: string[]
  rawKeys: string[]
  errorAlerts: string[]
  emptyPanels: string[]
}> {
  return page.evaluate(() => {
    const clipped: string[] = []
    const outside: string[] = []
    const hscroll: string[] = []
    const rawKeys: string[] = []
    const errorAlerts: string[] = []
    const emptyPanels: string[] = []

    const clippedSelectors = [
      '.pf-v6-c-card__title-text',
      '.pf-v6-c-tabs__item-text',
      '.pf-v6-c-button__text',
      '.pf-v6-c-alert__title',
      '.pf-v6-c-alert__description',
      '.pf-v6-c-form__label-text',
      '[data-testid="points-hint"]',
      '.pf-v6-c-descriptions__label',
      '.pf-v6-c-descriptions__description',
    ]

    const visible = (el: Element): boolean => {
      const r = el.getBoundingClientRect()
      if (r.width <= 0 || r.height <= 0) return false
      const s = getComputedStyle(el)
      return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0
    }
    const textOf = (el: Element): string =>
      (el.textContent ?? '').replace(/\s+/g, ' ').trim()
    const describe = (el: Element): string => {
      const cls = typeof el.className === 'string'
        ? el.className.split(/\s+/).filter(Boolean).slice(0, 2).join('.')
        : ''
      const text = textOf(el).slice(0, 70)
      return `<${el.tagName.toLowerCase()}${cls ? `.${cls}` : ''}> "${text}"`
    }
    /** 是否位于「可横向滚动且确实在滚动」的祖先里（表格/代码块），这类溢出是设计内行为 */
    const inHScroll = (el: Element): boolean => {
      let p = el.parentElement
      while (p && p !== document.body) {
        const s = getComputedStyle(p)
        if (
          (s.overflowX === 'auto' || s.overflowX === 'scroll') &&
          p.scrollWidth > p.clientWidth + 1
        ) {
          return true
        }
        p = p.parentElement
      }
      return false
    }

    // 1) 页面级横向滚动
    const vw = document.documentElement.clientWidth
    if (document.documentElement.scrollWidth > vw + 1) {
      hscroll.push(`document.scrollWidth=${document.documentElement.scrollWidth} > viewport=${vw}`)
    }
    if (document.body.scrollWidth > vw + 1) {
      hscroll.push(`body.scrollWidth=${document.body.scrollWidth} > viewport=${vw}`)
    }

    // 2) 明确不应被裁的 UI 文案
    for (const selector of clippedSelectors) {
      for (const el of document.querySelectorAll(selector)) {
        if (!visible(el)) continue
        const text = textOf(el)
        if (!text) continue
        if (el.scrollWidth > el.clientWidth + 2) {
          clipped.push(`${selector} ${describe(el)} (scroll=${el.scrollWidth}, client=${el.clientWidth})`)
        }
        // 纵向裁切（固定高度 + overflow hidden）同样算显示不全
        const style = getComputedStyle(el)
        if (style.overflowY === 'hidden' && el.scrollHeight > el.clientHeight + 4) {
          clipped.push(
            `${selector} ${describe(el)} vertical (scroll=${el.scrollHeight}, client=${el.clientHeight})`,
          )
        }
      }
    }

    // 2b) Card 头部整体溢出：标题区 + extra（工具条）被 head 的 overflow 裁掉
    for (const head of document.querySelectorAll('.pf-v6-c-card__header-main')) {
      if (!visible(head)) continue
      const hr = head.getBoundingClientRect()
      if (head.scrollWidth > head.clientWidth + 2) {
        clipped.push(
          `.pf-v6-c-card__header-main ${describe(head)} (scroll=${head.scrollWidth}, client=${head.clientWidth})`,
        )
      }
      for (const el of head.querySelectorAll(
        '.pf-v6-c-card__title-text, .pf-v6-c-card__actions, button, input, .pf-v6-c-form-control',
      )) {
        if (!visible(el)) continue
        const r = el.getBoundingClientRect()
        if (r.right > hr.right + 1) {
          clipped.push(
            `card-head child ${describe(el)} (right=${Math.round(r.right)} > head=${Math.round(hr.right)})`,
          )
        }
      }
    }

    // 3) 按钮文案被压扁（antd 按钮 nowrap，挤压后会溢出或裁切）
    for (const el of document.querySelectorAll('button')) {
      if (!visible(el)) continue
      const text = textOf(el)
      if (!text) continue
      if (el.scrollWidth > el.clientWidth + 2) {
        clipped.push(`button ${describe(el)} (scroll=${el.scrollWidth}, client=${el.clientWidth})`)
      }
    }

    // 4) 关键控件超出视口横向边界（表格内部横向滚动豁免）
    const boxSelectors = [
      '.pf-v6-c-card',
      '.pf-v6-c-tabs',
      'button',
      'input',
      'select',
      '.pf-v6-c-form-control',
      '.pf-v6-c-table',
      '.pf-v6-c-pagination',
    ]
    for (const selector of boxSelectors) {
      for (const el of document.querySelectorAll(selector)) {
        if (!visible(el)) continue
        if (inHScroll(el)) continue
        const r = el.getBoundingClientRect()
        if (r.right > vw + 1 || r.left < -1) {
          outside.push(
            `${selector} ${describe(el)} (left=${Math.round(r.left)}, right=${Math.round(r.right)}, vw=${vw})`,
          )
        }
      }
    }

    // 5) 漏出的 i18n key（只查 UI 文案容器，避免日志/报文正文误报）
    const keyPattern = /\b(?:menu|pt|pt2|simPanel|slave|master|status|logs|history|cap|test|multi|scp|cmd|header|auth|common)\.[a-zA-Z][\w.]*/g
    const keySelectors = [
      '.pf-v6-c-card__title-text',
      '.pf-v6-c-tabs__item-text',
      '.pf-v6-c-nav__link',
      'button',
      '.pf-v6-c-form__label-text',
      '.pf-v6-c-alert__title',
      '.pf-v6-c-alert__description',
      '.pf-v6-c-descriptions__label',
      '.pf-v6-c-descriptions__description',
    ]
    for (const selector of keySelectors) {
      for (const el of document.querySelectorAll(selector)) {
        if (!visible(el)) continue
        const hits = textOf(el).match(keyPattern)
        if (hits) rawKeys.push(`${selector} ${describe(el)} -> ${hits.join(', ')}`)
      }
    }

    // 6) 页面内不应出现错误级 Alert（接口失败/契约不一致会落到这里）
    for (const el of document.querySelectorAll('.pf-v6-c-alert.pf-m-danger')) {
      if (visible(el)) errorAlerts.push(describe(el))
    }

    // 7) 激活的页签面板不应是空白（页签切换/懒加载失效会表现为空面板）
    for (const el of document.querySelectorAll('[role="tabpanel"]')) {
      if (!visible(el)) continue
      if (!textOf(el) && !el.querySelector('canvas, svg, img, video, .pf-v6-c-empty-state')) {
        emptyPanels.push(describe(el))
      }
    }

    return { clipped, outside, hscroll, rawKeys, errorAlerts, emptyPanels }
  })
}

/** 巡检当前页面并把问题记入 state（含逐页日志，超时也能看到已发现的项） */
async function recordIssues(page: Page, state: AuditState): Promise<void> {
  const dom = await auditDom(page)
  const found: AuditIssue[] = []
  for (const [kind, list] of [
    ['clipped', dom.clipped],
    ['outside', dom.outside],
    ['hscroll', dom.hscroll],
    ['raw-i18n-key', dom.rawKeys],
    ['error-alert', dom.errorAlerts],
    ['empty-panel', dom.emptyPanels],
  ] as const) {
    for (const detail of list) {
      found.push({
        kind,
        page: state.label,
        viewport: state.viewport,
        lang: state.lang,
        detail,
      })
    }
  }
  state.issues.push(...found)
  // 即使后面超时/失败，也能在日志里看到每个页面的巡检结果
  if (found.length > 0) {
    console.log(
      `\n[audit] ${state.viewport} ${state.lang} ${state.label}:\n` +
        found.map((i) => `  - [${i.kind}] ${i.detail}`).join('\n'),
    )
  }
  // 给异步 console.error / 失败响应一点时间落到收集器
  await page.waitForTimeout(250)
}

function assertClean(state: AuditState): void {
  const all = [
    ...state.issues.map(
      (i) => `[${i.kind}] ${i.viewport} ${i.lang} ${i.page}: ${i.detail}`,
    ),
    ...state.runtime.map((i) => `[runtime] ${i.label}: ${i.detail}`),
  ]
  if (all.length > 0) {
    console.log(`\nUI 巡检发现 ${all.length} 条：\n${all.join('\n')}\n`)
  } else {
    console.log(
      '\nUI 巡检通过：未发现裁切/溢出/控制台 error·warn/失败请求/错误 Alert/空白页签/漏出 i18n key。\n',
    )
  }
  expect(all, `UI 巡检发现问题：\n${all.join('\n')}`).toEqual([])
}

test('UI 自动巡检：布局裁切 / 横向溢出 / 控制台错误 / 失败请求 / i18n key', async ({ page, request }) => {
  test.setTimeout(300_000) // 24 个页面快照 + 英文复扫，远超默认 60s
  mkdirSync('tests/e2e/audit-shots', { recursive: true })

  // 前置：子站监听 2415，主站连上去——让两端的“已连接/可操作”状态都被巡检到
  // （先停一次，保证重复运行/失败重跑时状态干净）
  await request.post(`${COMBINED}/api/master/stop`, { data: {} })
  await request.post(`${COMBINED}/slave/api/slave/stop`, { data: {} })
  const slaveStart = await request.post(`${COMBINED}/slave/api/slave/start`, {
    data: { host: '127.0.0.1', port: 2415, addr: 1 },
  })
  expect((await slaveStart.json()).ok).toBeTruthy()
  const masterStart = await request.post(`${COMBINED}/api/master/start`, {
    data: { host: '127.0.0.1', port: 2415, addr: 1 },
  })
  expect((await masterStart.json()).ok).toBeTruthy()

  const state: AuditState = {
    label: 'init',
    viewport: '1680x950',
    lang: 'zh',
    runtime: [],
    issues: [],
  }
  attachWatchers(page, state)

  const record = async (): Promise<void> => recordIssues(page, state)

  const shot = async (): Promise<void> => {
    await page.screenshot({
      path: `tests/e2e/audit-shots/${state.viewport}-${state.lang}-${state.label}.png`,
      fullPage: true,
    })
  }

  await page.goto(appUrl(COMBINED), { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: /主站工作台/ })).toBeVisible({ timeout: 20_000 })

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    state.viewport = `${viewport.width}x${viewport.height}`

    for (const meta of PAGES) {
      state.label = meta.key
      const menuItem = page.locator('.pf-v6-c-nav__link').filter({ hasText: meta.menu }).first()
      await menuItem.click()
      // 菜单必须真的切到对应页面：PF 会给当前项加 pf-m-current
      await expect(menuItem).toHaveClass(/pf-m-current/)
      if (meta.marker) {
        await expect(page.getByText(meta.marker, { exact: false })).toBeVisible({ timeout: 20_000 })
      }
      // 等懒加载 chunk + 首屏请求落地
      await page.waitForTimeout(700)
      await record()
      await shot()

      // 主站命令面板的折叠区默认只展开「遥控」：全部展开后再巡检一次，
      // 否则设点/参数/文件等表单的裁切问题会被折叠隐藏。
      if (meta.key === 'master') {
        state.label = 'master-expanded'
        for (let n = 0; n < 20; n += 1) {
          const collapsed = page
            .locator('.pf-v6-c-expandable-section__toggle[aria-expanded="false"]')
            .first()
          if ((await collapsed.count()) === 0) break
          await collapsed.click()
        }
        await page.waitForTimeout(400)
        await record()
        await shot()
      }
    }

    // 工作台页签：主站 2 个 / 子站 4 个
    for (const tab of ['报文查看器', '趋势图']) {
      state.label = `master-tab-${tab}`
      await page.locator('.pf-v6-c-nav__link').filter({ hasText: /主站工作台/ }).click()
      const tabEl = page.getByRole('tab', { name: tab })
      await tabEl.click()
      await expect(tabEl).toHaveAttribute('aria-selected', 'true')
      await page.waitForTimeout(500)
      await record()
      await shot()
    }
    for (const tab of ['手动置数', '应答行为', '模拟控制', '测试注入']) {
      state.label = `slave-tab-${tab}`
      await page.locator('.pf-v6-c-nav__link').filter({ hasText: /子站工作台/ }).click()
      const tabEl = page.getByRole('tab', { name: tab })
      await tabEl.click()
      await expect(tabEl).toHaveAttribute('aria-selected', 'true')
      await page.waitForTimeout(500)
      await record()
      await shot()
    }
  }

  // 英文文案通常更长：单独跑一轮，专抓英文下的裁切/溢出
  state.lang = 'en'
  await page.getByRole('button', { name: 'EN', exact: true }).click()
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: /Master workbench/i })).toBeVisible()
  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    state.viewport = `${viewport.width}x${viewport.height}`
    for (const meta of [
      { menu: /Master workbench/i, marker: 'Connection & commands', key: 'master' },
      { menu: /Slave workbench/i, marker: 'Slave start & status', key: 'slave' },
      { menu: /Status/, marker: null, key: 'status' },
      { menu: /Logs/, marker: null, key: 'logs' },
      { menu: /History/, marker: null, key: 'history' },
    ]) {
      state.label = meta.key
      const menuItem = page.locator('.pf-v6-c-nav__link').filter({ hasText: meta.menu }).first()
      await menuItem.click()
      await expect(menuItem).toHaveClass(/pf-m-current/)
      if (meta.marker) {
        await expect(page.getByText(meta.marker, { exact: false })).toBeVisible({ timeout: 20_000 })
      }
      await page.waitForTimeout(700)
      await record()
      await shot()
    }
  }

  // 深色主题：布局/溢出同样要过一遍（颜色对比不在自动判定范围）
  await page.setViewportSize({ width: 1366, height: 768 })
  state.viewport = '1366x768'
  await page.getByTestId('theme-toggle').click()
  for (const meta of [
    { menu: /Master workbench/i, marker: 'Connection & commands', key: 'dark-master' },
    { menu: /Slave workbench/i, marker: 'Slave start & status', key: 'dark-slave' },
    { menu: /Status/, marker: null, key: 'dark-status' },
  ]) {
    state.label = meta.key
    await page.locator('.pf-v6-c-nav__link').filter({ hasText: meta.menu }).first().click()
    if (meta.marker) {
      await expect(page.getByText(meta.marker, { exact: false })).toBeVisible({ timeout: 20_000 })
    }
    await page.waitForTimeout(700)
    await record()
    await shot()
  }

  await request.post(`${COMBINED}/api/master/stop`, { data: {} })
  await request.post(`${COMBINED}/slave/api/slave/stop`, { data: {} })

  assertClean(state)
})

test('单角色部署巡检：主站 8765 / 子站 8766 的可见菜单与页面', async ({ page }) => {
  test.setTimeout(180_000)
  const state: AuditState = {
    label: 'init',
    viewport: '1366x768',
    lang: 'zh',
    runtime: [],
    issues: [],
  }
  attachWatchers(page, state)
  await page.setViewportSize({ width: 1366, height: 768 })

  const deployments = [
    {
      base: MASTER,
      menus: [/主站工作台/, /多站/, /状态总览/, /日志/, /历史/, /报文抓包/, /自动化测试/],
    },
    {
      base: SLAVE,
      menus: [/子站工作台/, /多站/, /状态总览/, /日志/, /历史/, /报文抓包/, /自动化测试/],
    },
  ]
  for (const deployment of deployments) {
    await page.goto(appUrl(deployment.base), { waitUntil: 'domcontentloaded' })
    await expect(page.locator('.pf-v6-c-nav__link').first()).toBeVisible({ timeout: 20_000 })
    // 单角色部署只应出现本角色工作台菜单（角色隔离）
    const labels = await page.locator('.pf-v6-c-nav__link').allTextContents()
    const expectedOther = deployment.base === MASTER ? '子站工作台' : '主站工作台'
    expect(labels.some((l) => l.includes(expectedOther))).toBe(false)

    for (const menu of deployment.menus) {
      state.label = `${deployment.base === MASTER ? 'master-only' : 'slave-only'}-${menu.source}`
      const menuItem = page.locator('.pf-v6-c-nav__link').filter({ hasText: menu }).first()
      await menuItem.click()
      await expect(menuItem).toHaveClass(/pf-m-current/)
      await page.waitForTimeout(700)
      await recordIssues(page, state)
    }
  }

  assertClean(state)
})

test('下载/导出链接探活：直开链接返回 2xx 且带附件头', async ({ request }) => {
  const checks: { base: string; path: string }[] = [
    { base: COMBINED, path: '/api/points/yaml' },
    { base: COMBINED, path: '/api/export/points.csv' },
    { base: COMBINED, path: '/api/export/session.json' },
    { base: COMBINED, path: '/api/logs/export' },
    { base: COMBINED, path: '/api/diagnostics/export' },
    { base: MASTER, path: '/api/history/export?type=data' },
    { base: MASTER, path: '/api/history/export?type=frames' },
  ]
  for (const check of checks) {
    const res = await request.get(`${check.base}${check.path}`)
    expect(res.status(), `${check.path} status`).toBe(200)
    const disposition = res.headers()['content-disposition'] ?? ''
    // 导出物都应作为附件下载（浏览器直开不会显示乱码页）
    expect(disposition, `${check.path} Content-Disposition`).toContain('attachment')
  }

  // 不存在的抓包文件/测试报告：应是明确的 404，而不是 500 或挂起
  for (const path of ['/api/capture/download/__nope__.i104', '/api/tests/reports/nope/nope.json']) {
    const res = await request.get(`${COMBINED}${path}`)
    expect(res.status(), `${path} status`).toBe(404)
  }
})
