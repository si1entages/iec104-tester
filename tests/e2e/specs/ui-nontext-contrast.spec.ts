/**
 * 非文本对比度巡检（WCAG 1.4.11 / 2.4.7，零依赖）。
 *
 * 文本对比度由 `ui-contrast.spec.ts` 覆盖；这里查“图形对象/控件边界”：
 *  - 输入框、下拉框、数字框、日期选择、默认按钮、勾选框、单选框、分页项的边框
 *    与相邻背景 ≥3:1（边框是识别控件的唯一视觉边界）；
 *  - Switch 轨道与背景 ≥3:1；
 *  - 纯图标按钮（无可见文字）的图标颜色与背景 ≥3:1；
 *  - 键盘焦点：Tab 遍历，焦点轮廓颜色与背景 ≥3:1，且必须有可见焦点指示。
 *
 * 跑法同其他 Playwright 用例；默认门禁 <3:1 失败，`CONTRAST_REPORT=1` 只报告。
 */
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { COMBINED , appUrl } from './helpers'

test.describe.configure({ mode: 'serial' })

interface Issue {
  kind: string
  selector: string
  fg: string
  bg: string
  ratio: number
  count: number
  detail?: string
}

async function auditNonText(page: Page): Promise<{
  issues: Issue[]
  checked: number
  skipped: number
}> {
  return page.evaluate(() => {
    interface Rgba { r: number; g: number; b: number; a: number }
    const parse = (value: string): Rgba | null => {
      if (!value || value === 'transparent') return { r: 0, g: 0, b: 0, a: 0 }
      const m = value.match(/rgba?\(([^)]+)\)/)
      if (!m) return null
      const p = m[1].split(/[,/\s]+/).filter(Boolean).map(Number)
      if (p.length < 3 || p.some(Number.isNaN)) return null
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }
    }
    const blend = (fg: Rgba, bg: Rgba): Rgba => ({
      r: fg.r * fg.a + bg.r * (1 - fg.a),
      g: fg.g * fg.a + bg.g * (1 - fg.a),
      b: fg.b * fg.a + bg.b * (1 - fg.a),
      a: 1,
    })
    const lum = (c: Rgba): number => {
      const f = (v: number): number => {
        const x = v / 255
        return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
      }
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b)
    }
    const ratio = (a: Rgba, b: Rgba): number => {
      const la = lum(a)
      const lb = lum(b)
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
    }
    const css = (c: Rgba): string =>
      `rgb(${Math.round(c.r)}, ${Math.round(c.g)}, ${Math.round(c.b)})`
    const visible = (el: Element): boolean => {
      const r = el.getBoundingClientRect()
      if (r.width <= 0 || r.height <= 0) return false
      const s = getComputedStyle(el)
      return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0
    }
    /** 禁用控件按 WCAG 豁免（不参与非文本对比判定） */
    const isDisabled = (el: Element): boolean =>
      Boolean(
        el.closest(
          '[disabled], [aria-disabled="true"], .pf-m-disabled',
        ),
      )
    const effectiveBg = (el: Element | null): Rgba | null => {
      if (!el) return null
      const layers: Rgba[] = []
      let node: Element | null = el
      while (node) {
        const s = getComputedStyle(node)
        if (s.backgroundImage !== 'none') return null
        const c = parse(s.backgroundColor)
        if (c && c.a > 0) {
          layers.push(c)
          if (c.a >= 1) break
        }
        node = node.parentElement
      }
      let bg: Rgba = { r: 255, g: 255, b: 255, a: 1 }
      for (let i = layers.length - 1; i >= 0; i -= 1) bg = blend(layers[i], bg)
      return bg
    }
    const selectorOf = (el: Element): string => {
      const cls = typeof el.className === 'string'
        ? el.className.split(/\s+/).filter(Boolean).slice(0, 2).join('.')
        : ''
      return `${el.tagName.toLowerCase()}${cls ? `.${cls}` : ''}`
    }

    const groups = new Map<string, Issue>()
    let checked = 0
    let skipped = 0
    const add = (kind: string, el: Element, fg: Rgba, bg: Rgba, detail?: string): void => {
      const r = ratio(fg, bg)
      if (r >= 3) return
      const fgCss = css(fg)
      const bgCss = css(bg)
      const key = `${kind}|${selectorOf(el)}|${fgCss}|${bgCss}|${detail ?? ''}`
      const existing = groups.get(key)
      if (existing) existing.count += 1
      else {
        groups.set(key, {
          kind, selector: selectorOf(el), fg: fgCss, bg: bgCss,
          ratio: Math.round(r * 100) / 100, count: 1, detail,
        })
      }
    }

    // ── 1. 控件边框与背景 ───────────────────────────────────────
    const borderSelectors = [
      '.pf-v6-c-form-control',
      '.pf-v6-c-button.pf-m-secondary',
      '.pf-v6-c-check__input',
      '.pf-v6-c-radio__input',
      '.pf-v6-c-pagination__nav button',
    ]
    for (const selector of borderSelectors) {
      for (const el of document.querySelectorAll(selector)) {
        if (!visible(el)) continue
        if (isDisabled(el)) continue
        const s = getComputedStyle(el)
        const outside = effectiveBg(el.parentElement)
        if (!outside) {
          skipped += 1
          continue
        }
        const sides = [
          ['Top', s.borderTopWidth, s.borderTopColor],
          ['Right', s.borderRightWidth, s.borderRightColor],
          ['Bottom', s.borderBottomWidth, s.borderBottomColor],
          ['Left', s.borderLeftWidth, s.borderLeftColor],
        ] as const
        let found = false
        for (const [, width, color] of sides) {
          if (Number.parseFloat(width) <= 0) continue
          const c = parse(color)
          if (!c || c.a <= 0) continue
          found = true
          checked += 1
          add('border', el, blend(c, outside), outside, selector)
        }
        if (!found) skipped += 1
      }
    }

    // Switch 轨道（填充色就是可操作区域的视觉边界）
    for (const el of document.querySelectorAll('.pf-v6-c-switch__toggle')) {
      if (!visible(el)) continue
      if (isDisabled(el)) continue
      const s = getComputedStyle(el)
      const outside = effectiveBg(el.parentElement)
      const track = parse(s.backgroundColor)
      if (!outside || !track || track.a <= 0) {
        skipped += 1
        continue
      }
      // 未选中态：PF 轨道与页面同色，真正的状态指示是滑块（::before），按滑块断言
      let painted = blend(track, outside)
      if (ratio(painted, outside) < 3) {
        const thumb = parse(getComputedStyle(el, '::before').backgroundColor)
        if (thumb && thumb.a > 0) painted = blend(thumb, blend(track, outside))
      }
      checked += 1
      add('switch-track', el, painted, outside)
    }

    // ── 2. 纯图标按钮 ───────────────────────────────────────────
    for (const el of document.querySelectorAll('button, a[href]')) {
      if (!visible(el)) continue
      if (isDisabled(el)) continue
      const text = (el.textContent ?? '').replace(/\s+/g, '').trim()
      if (text) continue // 有可见文字：文字对比度已由文本巡检覆盖
      const icon = el.querySelector('svg')
      if (!icon) continue
      const s = getComputedStyle(el)
      const fg = parse(s.color)
      const bg = effectiveBg(el)
      if (!fg || !bg) {
        skipped += 1
        continue
      }
      checked += 1
      add('icon-only', el, blend(fg, bg), bg)
    }

    return { issues: [...groups.values()], checked, skipped }
  })
}

/** 读取当前键盘焦点元素的焦点指示对比度 */
async function readFocus(page: Page): Promise<{
  selector: string
  fg: string
  bg: string
  ratio: number
  kind: string
} | null> {
  return page.evaluate(() => {
    interface Rgba { r: number; g: number; b: number; a: number }
    const parse = (value: string): Rgba | null => {
      if (!value || value === 'transparent') return { r: 0, g: 0, b: 0, a: 0 }
      const m = value.match(/rgba?\(([^)]+)\)/)
      if (!m) return null
      const p = m[1].split(/[,/\s]+/).filter(Boolean).map(Number)
      if (p.length < 3) return null
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }
    }
    const blend = (fg: Rgba, bg: Rgba): Rgba => ({
      r: fg.r * fg.a + bg.r * (1 - fg.a),
      g: fg.g * fg.a + bg.g * (1 - fg.a),
      b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1,
    })
    const lum = (c: Rgba): number => {
      const f = (v: number): number => {
        const x = v / 255
        return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
      }
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b)
    }
    const ratio = (a: Rgba, b: Rgba): number => {
      const la = lum(a)
      const lb = lum(b)
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
    }
    const css = (c: Rgba): string => `rgb(${Math.round(c.r)}, ${Math.round(c.g)}, ${Math.round(c.b)})`
    const effectiveBg = (el: Element | null): Rgba | null => {
      if (!el) return null
      const layers: Rgba[] = []
      let node: Element | null = el
      while (node) {
        const s = getComputedStyle(node)
        if (s.backgroundImage !== 'none') return null
        const c = parse(s.backgroundColor)
        if (c && c.a > 0) {
          layers.push(c)
          if (c.a >= 1) break
        }
        node = node.parentElement
      }
      let bg: Rgba = { r: 255, g: 255, b: 255, a: 1 }
      for (let i = layers.length - 1; i >= 0; i -= 1) bg = blend(layers[i], bg)
      return bg
    }

    const el = document.activeElement
    if (!el || el === document.body || !(el instanceof Element)) return null
    const r = el.getBoundingClientRect()
    if (r.width <= 0 || r.height <= 0) return null
    const s = getComputedStyle(el)
    // 焦点轮廓画在元素外侧（outline-offset），相邻色是父容器背景；
    // 用元素自身背景会把「深青轮廓 + 深青主按钮」误判成 1:1。
    const bg = effectiveBg(el.parentElement) ?? effectiveBg(el)
    if (!bg) return null
    const cls = typeof el.className === 'string'
      ? el.className.split(/\s+/).filter(Boolean).slice(0, 2).join('.')
      : ''
    const selector = `${el.tagName.toLowerCase()}${cls ? `.${cls}` : ''}`

    // 优先 outline；否则看 box-shadow 里的颜色
    const outlineWidth = Number.parseFloat(s.outlineWidth) || 0
    const outline = parse(s.outlineColor)
    if (outlineWidth > 0 && outline && outline.a > 0) {
      return {
        selector, kind: 'focus-outline', fg: css(blend(outline, bg)), bg: css(bg),
        ratio: Math.round(ratio(blend(outline, bg), bg) * 100) / 100,
      }
    }
    const shadow = s.boxShadow
    if (shadow && shadow !== 'none') {
      const c = parse(shadow)
      if (c && c.a > 0) {
        return {
          selector, kind: 'focus-shadow', fg: css(blend(c, bg)), bg: css(bg),
          ratio: Math.round(ratio(blend(c, bg), bg) * 100) / 100,
        }
      }
    }
    return { selector, kind: 'focus-missing', fg: '-', bg: css(bg), ratio: 0 }
  })
}

test('非文本对比度：控件边框 / Switch 轨道 / 纯图标按钮 / 键盘焦点（WCAG 1.4.11）', async ({ page }) => {
  test.setTimeout(240_000)
  const issues: (Issue & { page: string; mode: string })[] = []
  let checked = 0
  let skipped = 0

  const pages = [
    { menu: /主站工作台/, key: 'master' },
    { menu: /子站工作台/, key: 'slave' },
    { menu: /多站/, key: 'multi' },
    { menu: /状态总览/, key: 'status' },
    { menu: /日志/, key: 'logs' },
    { menu: /历史/, key: 'history' },
    { menu: /报文抓包/, key: 'capture' },
    { menu: /自动化测试/, key: 'tests' },
  ]

  await page.goto(appUrl(COMBINED), { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.pf-v6-c-nav__link').filter({ hasText: /主站工作台/ })).toBeVisible({ timeout: 20_000 })
  await page.setViewportSize({ width: 1366, height: 768 })
  // 关掉过渡动画：InputNumber 等控件 outline 有 0.2s 过渡，Tab 后立刻读会读到 0px
  await page.addStyleTag({
    content: '*,*::before,*::after{transition:none !important;animation:none !important;}',
  })

  for (const mode of ['light', 'dark'] as const) {
    const current = await page.evaluate(() => document.documentElement.dataset.theme)
    if (current !== mode) {
      await page.getByTestId('theme-toggle').click()
      await expect
        .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
        .toBe(mode)
    }

    for (const meta of pages) {
      await page.locator('.pf-v6-c-nav__link').filter({ hasText: meta.menu }).first().click()
      await page.waitForTimeout(600)
      const report = await auditNonText(page)
      checked += report.checked
      skipped += report.skipped
      for (const issue of report.issues) {
        issues.push({ ...issue, page: meta.key, mode })
      }

      // 键盘焦点：从当前菜单项开始 Tab 12 次，覆盖菜单/头部/页面控件
      const seen = new Set<string>()
      for (let i = 0; i < 12; i += 1) {
        await page.keyboard.press('Tab')
        const focus = await readFocus(page)
        if (!focus) continue
        const key = `${focus.kind}|${focus.selector}`
        if (seen.has(key)) continue
        seen.add(key)
        checked += 1
        if (focus.kind === 'focus-missing' || focus.ratio < 3) {
          issues.push({
            kind: focus.kind,
            selector: focus.selector,
            fg: focus.fg,
            bg: focus.bg,
            ratio: focus.ratio,
            count: 1,
            page: meta.key,
            mode,
            detail: focus.kind === 'focus-missing' ? '无 focus-visible 轮廓/阴影' : undefined,
          })
        }
      }
    }
  }

  const hard = issues.filter((i) => i.ratio < 3 || i.kind === 'focus-missing')
  const fmt = hard
    .sort((a, b) => a.ratio - b.ratio)
    .map(
      (i) =>
        `  [${i.mode}/${i.page}] ${i.kind} ${i.selector} ${i.ratio}:1 ` +
        `fg=${i.fg} bg=${i.bg} ×${i.count}${i.detail ? ` (${i.detail})` : ''}`,
    )
    .join('\n')

  if (hard.length > 0) console.log(`\n非文本对比硬失败（<3:1）：\n${fmt}\n`)
  console.log(
    `非文本对比巡检：检查 ${checked} 处，跳过 ${skipped} 处（渐变/未知背景），` +
      `硬失败 ${hard.length} 组。`,
  )

  if (process.env.CONTRAST_REPORT === '1') {
    console.log(`\n报告模式：${hard.length} 组 <3:1（不阻断）。`)
  } else {
    expect(hard, `以下非文本对比度 <3:1：\n${fmt}`).toEqual([])
  }
})
