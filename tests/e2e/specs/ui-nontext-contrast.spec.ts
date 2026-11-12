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
 *
 * **套件维度（T89）**：按 `GATE_KITS`（默认 `pf,carbon`）各跑一遍；控件选择器
 * （边框/Switch 轨道）两套件并集见 `kitProfiles.ts`。
 */
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { BRIDGE, COMBINED , appUrl } from './helpers'
import {
  BORDER_SELECTORS,
  GATE_KITS,
  SWITCH_TOGGLE_SELECTORS,
  expectKitApplied,
  profileOf,
} from './kitProfiles'

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
  return page.evaluate(
    ({ borderSelectors, switchSelectors }) => {
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
          '[disabled], [aria-disabled="true"], .pf-m-disabled, .cds--btn--disabled',
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
    /** 纯图标按钮（有 svg、无文字）：可识别性由图标承担，其边框/分隔线属装饰，不判对比度 */
    const isIconOnly = (el: Element): boolean => {
      if (el.tagName !== 'BUTTON' && el.tagName !== 'A') return false
      if ((el.textContent ?? '').replace(/\s+/g, '').trim()) return false
      return Boolean(el.querySelector('svg'))
    }
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
    for (const selector of borderSelectors) {
      for (const el of document.querySelectorAll(selector)) {
        if (!visible(el)) continue
        if (isDisabled(el)) continue
        // 纯图标按钮（只有 svg、无文字）：可识别性由图标承担（图标对比度由第 3 段单独判），
        // 边框只是分隔线，按 WCAG 1.4.11 不属于「识别控件所必需」——不判。
        // T89 实测：Carbon 分页前进按钮的分隔线 1.31:1（深色）会被误判为缺陷。
        if (isIconOnly(el)) continue
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
        // T99：PF6 把控件边框画在 ::before/::after（inset:0 伪元素）与
        // 零偏移/零模糊/正扩散 box-shadow 环上——元素自身无边框时补读
        // （T89 遗留：边框段此前对 PF 0 命中）。
        // 可感知性 = 与任一相邻侧 ≥3:1（WCAG 1.4.11）：内外两侧取较优者计数。
        if (!found) {
          const inside = effectiveBg(el)
          const addDerivedBorder = (c: Rgba, origin: string): void => {
            checked += 1
            const fgOut = blend(c, outside)
            const rOut = ratio(fgOut, outside)
            const rIn = inside ? ratio(blend(c, inside), inside) : rOut
            if (Math.max(rOut, rIn) >= 3) return
            if (rOut <= rIn) {
              add('border', el, fgOut, outside, `${selector}(${origin}·外侧)`)
            } else {
              add('border', el, blend(c, inside as Rgba), inside as Rgba,
                `${selector}(${origin}·内侧)`)
            }
          }
          for (const pseudo of ['::before', '::after'] as const) {
            const ps = getComputedStyle(el, pseudo)
            if (ps.display === 'none' || ps.content === 'none') continue
            for (const [, width, color] of [
              ['Top', ps.borderTopWidth, ps.borderTopColor],
              ['Right', ps.borderRightWidth, ps.borderRightColor],
              ['Bottom', ps.borderBottomWidth, ps.borderBottomColor],
              ['Left', ps.borderLeftWidth, ps.borderLeftColor],
            ] as const) {
              if (Number.parseFloat(width) <= 0) continue
              const c = parse(color)
              if (!c || c.a <= 0) continue
              addDerivedBorder(c, pseudo)
            }
          }
          // box-shadow 边框环：与 readFocus 同一筛选（偏移 0/模糊 0/扩散 >0），
          // 不把投影/焦点指示误判成静态边框。
          if (s.boxShadow && s.boxShadow !== 'none') {
            const ringRe = /(rgba?\([^)]*\))([^,]*)/g
            let m: RegExpExecArray | null
            while ((m = ringRe.exec(s.boxShadow)) !== null) {
              const c = parse(m[1])
              if (!c || c.a <= 0) continue
              const geo = (m[2].match(/-?[\d.]+px/g) ?? []).map((v) => Number.parseFloat(v))
              const [ox = 0, oy = 0, blur = 0, spread = 0] = geo
              if (ox !== 0 || oy !== 0 || blur !== 0 || spread <= 0) continue
              if (m[2].includes('inset')) continue  // 内嵌环属焦点指示，readFocus 已覆盖
              addDerivedBorder(c, 'box-shadow')
            }
          }
        }
        if (!found) skipped += 1
      }
    }

    // Switch 轨道（填充色就是可操作区域的视觉边界）
    for (const el of document.querySelectorAll(switchSelectors.join(','))) {
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
    },
    {
      borderSelectors: [...BORDER_SELECTORS],
      switchSelectors: [...SWITCH_TOGGLE_SELECTORS],
    },
  )
}

/**
 * 读取当前键盘焦点元素的焦点指示对比度（T89 重写：套件无关，按「指示器实际相邻的颜色」算）。
 *
 * 各套件的焦点画法不同，先前只读 `outline` 会把 PatternFly 之外的做法判错：
 *  - **PatternFly**：`outline: 2px solid`（offset 0）→ 相邻色是父容器背景；
 *  - **Carbon 按钮**：`outline-style: none` + `box-shadow: …1px inset, …2px inset`
 *    （内嵌环，相邻色是**按钮自身填充**——深色填充按钮会用浅色内环做分隔）；
 *  - **Carbon 链接/输入框**：`outline` + **负 offset**（画在元素内部）→ 相邻色是自身背景；
 *  - **Carbon 勾选/单选/开关**：焦点目标（input / 1×1 按钮）不可见，指示器画在
 *    label 的 `::before` 上 → 先解析「可见替身」，再读它自己与伪元素的环。
 *
 * 因此这里：① 解析可见替身；② 收集元素自身 + `::before`/`::after` 的
 * outline（判 offset 正负）、box-shadow（判 inset + 逐环颜色）、border；③ 取最高对比度。
 * 一个环都读不到才算 `focus-missing`（真的没有可见焦点指示）。
 */
async function readFocus(page: Page): Promise<{
  selector: string
  fg: string
  bg: string
  ratio: number
  kind: string
  /** 实际读到的 outline/box-shadow（诊断用，进失败信息） */
  indicator: string
} | null> {
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
    const area = (el: Element): number => {
      const r = el.getBoundingClientRect()
      return r.width * r.height
    }
    const selectorOf = (el: Element): string => {
      const cls = typeof el.className === 'string'
        ? el.className.split(/\s+/).filter(Boolean).slice(0, 2).join('.')
        : ''
      return `${el.tagName.toLowerCase()}${cls ? `.${cls}` : ''}`
    }

    const raw = document.activeElement
    if (!raw || raw === document.body || !(raw instanceof Element)) return null

    // ① 可见替身：勾选框/开关把焦点放在不可见的 input / 1×1 按钮上
    let target: Element = raw
    if (area(raw) < 16) {
      const wrappers: (Element | null)[] = [
        raw.closest('.cds--toggle__switch'),
        raw.closest('label'),
        raw.closest('.cds--checkbox-wrapper'),
        raw.closest('.cds--radio-button-wrapper'),
        raw.parentElement,
        raw.parentElement?.parentElement ?? null,
      ]
      const found = wrappers.find((c) => c && area(c) >= 16)
      if (found) target = found
    }
    // 焦点目标本身不可见/零尺寸（浏览器仍会 focus，如隐藏的 input）时**跳过**：
    // 看不见的元素谈不上「焦点指示是否可见」，报出来只是噪声。
    const targetStyle = getComputedStyle(target)
    if (
      area(target) < 16 ||
      targetStyle.visibility === 'hidden' ||
      Number(targetStyle.opacity) === 0
    ) {
      return null
    }

    const ownBg = effectiveBg(target)
    const parentBg = effectiveBg(target.parentElement) ?? ownBg
    if (!ownBg || !parentBg) return null
    /** 是否见到「浏览器默认焦点环」（见下方 collect 的说明） */
    let autoRing = false

    /** 从「元素自身 + 两个伪元素」收集所有可见环，返回对比度最高的一项 */
    const collect = (el: Element, pseudo: '' | '::before' | '::after'): {
      color: Rgba; adjacent: Rgba; kind: string
    }[] => {
      const out: { color: Rgba; adjacent: Rgba; kind: string }[] = []
      const s = getComputedStyle(el, pseudo || undefined)
      if (s.display === 'none' || s.content === 'none') return out
      const outer = pseudo ? (effectiveBg(el.parentElement) ?? parentBg) : parentBg
      const inner = pseudo ? (effectiveBg(el) ?? ownBg) : ownBg
      // outline：负 offset 画在内部（相邻色＝自身背景），否则在外部。
      // `outline-style: auto` 是浏览器默认焦点环（颜色由 UA 决定，计算值可能是近黑，
      // 按色值算必然误报）——标记出来单独上报，不参与对比度判定。
      const ow = Number.parseFloat(s.outlineWidth) || 0
      const oc = parse(s.outlineColor)
      if (ow > 0 && s.outlineStyle === 'auto') {
        autoRing = true
      } else if (s.outlineStyle !== 'none' && ow > 0 && oc && oc.a > 0) {
        const offset = Number.parseFloat(s.outlineOffset) || 0
        out.push({ color: oc, adjacent: offset < 0 ? inner : outer, kind: 'focus-outline' })
      }
      // box-shadow：只认**环**（偏移 0 / 模糊 0 / 有扩散），逐环判断 inset
      // （内嵌环相邻色＝自身背景）。带模糊的是投影（如 `0 2px 10px`），不是焦点指示。
      if (s.boxShadow && s.boxShadow !== 'none') {
        const ringRe = /(rgba?\([^)]*\))([^,]*)/g
        let m: RegExpExecArray | null
        while ((m = ringRe.exec(s.boxShadow)) !== null) {
          const c = parse(m[1])
          if (!c || c.a <= 0) continue
          const geo = (m[2].match(/-?[\d.]+px/g) ?? []).map((v) => Number.parseFloat(v))
          const [ox = 0, oy = 0, blur = 0, spread = 0] = geo
          if (ox !== 0 || oy !== 0 || blur !== 0 || spread <= 0) continue
          const inset = m[2].includes('inset')
          out.push({ color: c, adjacent: inset ? inner : outer, kind: 'focus-shadow' })
        }
      }
      // 注意：**不读边框**。静态边框（表格/按钮的常驻描边）不是焦点指示，读它会把
      // 任意带边框的元素误判成「焦点环对比度不足」。PF/Carbon 的焦点都用
      // outline 或 box-shadow（必要时画在 ::before 上），实测已覆盖。
      return out
    }

    // ② 焦点还常画在「容器里的可见子元素」上：PF Switch 的环在
    //    `.pf-v6-c-switch__toggle`、Carbon 开关在 `.cds--toggle__switch`、
    //    勾选框在 `.cds--checkbox-label::before`——都被包在 focus 目标的容器里。
    //    因此连同 target 的可见子元素（限量 8 个）一起收集，取对比度最高的一项。
    const scan: Element[] = [target]
    for (const child of Array.from(target.querySelectorAll('*')).slice(0, 8)) {
      if (area(child) >= 16) scan.push(child)
    }
    const candidates = scan.flatMap((el) => [
      ...collect(el, ''),
      ...collect(el, '::before'),
      ...collect(el, '::after'),
    ])
    // 诊断串：把实际读到的东西写进报告，失败时不必再复现才知道看的是哪个控件
    const tgtStyle = getComputedStyle(target)
    const indicator =
      `outline=${tgtStyle.outlineWidth}/${tgtStyle.outlineStyle}/${tgtStyle.outlineColor}` +
      ` shadow=${tgtStyle.boxShadow === 'none' ? '-' : tgtStyle.boxShadow}` +
      ` bg=${tgtStyle.backgroundColor}` +
      ` focusVisible=${raw.matches(':focus-visible')}` +
      ` id=${target.getAttribute('id') ?? ''}` +
      ` type=${target.getAttribute('type') ?? ''}` +
      ` ph=${(target.getAttribute('placeholder') ?? '').slice(0, 20)}`
    const ringMissing = {
      selector: selectorOf(target),
      fg: '-',
      bg: css(ownBg),
      ratio: 0,
      indicator,
    }
    if (candidates.length === 0) {
      // 浏览器默认焦点环：用户实际看到的是它，色值不可测 → 单独计数上报
      if (autoRing) return { ...ringMissing, kind: 'focus-auto', fg: 'ua-default' }
      // `:focus-visible` 不匹配 = 浏览器判定这不是键盘焦点（鼠标点击/程序化聚焦）：
      // WCAG 2.4.7 只要求**键盘**焦点可见，这里报「无焦点环」是噪声。
      if (!raw.matches(':focus-visible')) return { ...ringMissing, kind: 'focus-mouse' }
      return { ...ringMissing, kind: 'focus-missing' }
    }
    let best = candidates[0]
    let bestRatio = ratio(blend(best.color, best.adjacent), best.adjacent)
    for (const cand of candidates.slice(1)) {
      const r = ratio(blend(cand.color, cand.adjacent), cand.adjacent)
      if (r > bestRatio) {
        best = cand
        bestRatio = r
      }
    }
    return {
      selector: selectorOf(target),
      kind: best.kind,
      fg: css(blend(best.color, best.adjacent)),
      bg: css(best.adjacent),
      ratio: Math.round(bestRatio * 100) / 100,
      indicator,
    }
  })
}

for (const kit of GATE_KITS) {
  const profile = profileOf(kit)

  test(`非文本对比度 [${profile.label}]：控件边框 / Switch 轨道 / 纯图标按钮 / 键盘焦点（WCAG 1.4.11）`, async ({ page }) => {
    test.setTimeout(240_000)
    const issues: (Issue & { page: string; mode: string })[] = []
    let checked = 0
    let skipped = 0
    /** 依赖浏览器默认焦点环（`outline-style: auto`）的次数：色值不可测，单独上报 */
    let autoCount = 0
    /** 非键盘焦点（`:focus-visible` 不匹配）的次数：WCAG 2.4.7 不适用，单独上报 */
    let mouseCount = 0

    const pages = [
      { menu: /主站工作台/, key: 'master' },
      { menu: /子站工作台/, key: 'slave' },
      { menu: /多站/, key: 'multi' },
      { menu: /状态总览/, key: 'status' },
      { menu: /日志/, key: 'logs' },
      { menu: /历史/, key: 'history' },
      { menu: /报文抓包/, key: 'capture' },
      { menu: /自动化测试/, key: 'tests' },
      { menu: /对点传动/, key: 'commission' },
      { menu: /操作审计/, key: 'audit' },
    ]

    await page.goto(appUrl(COMBINED, '', kit), { waitUntil: 'domcontentloaded' })
    await expectKitApplied(page, kit)
    await expect(page.locator(profile.nav).filter({ hasText: /主站工作台/ })).toBeVisible({ timeout: 20_000 })
    await page.setViewportSize({ width: 1366, height: 768 })
    // 关掉过渡动画：InputNumber 等控件 outline 有 0.2s 过渡，Tab 后立刻读会读到 0px
    await page.addStyleTag({
      content: '*,*::before,*::after{transition:none !important;animation:none !important;}',
    })

    for (const mode of ['light', 'dark'] as const) {
      const current = await page.evaluate(() => document.documentElement.dataset.theme)
      if (current !== mode) {
        await page.getByTestId(profile.themeToggle).click()
        await expect
          .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
          .toBe(mode)
      }

      for (const meta of pages) {
        await page.locator(profile.nav).filter({ hasText: meta.menu }).first().click()
        await page.waitForTimeout(600)
        const report = await auditNonText(page)
        checked += report.checked
        skipped += report.skipped
        for (const issue of report.issues) {
          issues.push({ ...issue, page: `${kit}:${meta.key}`, mode })
        }

        // 键盘焦点：从当前菜单项开始 Tab 12 次，覆盖菜单/头部/页面控件
        const seen = new Set<string>()
        for (let i = 0; i < 12; i += 1) {
          await page.keyboard.press('Tab')
          // Carbon 的焦点描边有过渡（outline-color 0.1s）：立刻读会读到中间态
          // `rgba(0,0,0,0)`，把正常焦点误判成「没有焦点环」（实测证实）。
          await page.waitForTimeout(120)
          const focus = await readFocus(page)
          if (!focus) continue
          const key = `${focus.kind}|${focus.selector}`
          if (seen.has(key)) continue
          seen.add(key)
          checked += 1
          if (focus.kind === 'focus-auto') autoCount += 1
          if (focus.kind === 'focus-mouse') mouseCount += 1
          const skippedKind = focus.kind === 'focus-auto' || focus.kind === 'focus-mouse'
          if (focus.kind === 'focus-missing' || (!skippedKind && focus.ratio < 3)) {
            issues.push({
              kind: focus.kind,
              selector: focus.selector,
              fg: focus.fg,
              bg: focus.bg,
              ratio: focus.ratio,
              count: 1,
              page: `${kit}:${meta.key}`,
              mode,
              detail:
                focus.kind === 'focus-missing'
                  ? `无 focus-visible 轮廓/阴影（${focus.indicator}）`
                  : focus.indicator,
            })
          }
        }
      }

      // 桥接页（T98）：合并部署按角色过滤没有桥菜单，走 BRIDGE 8769 专项巡检
      await page.goto(appUrl(BRIDGE, '#/bridge', kit), { waitUntil: 'domcontentloaded' })
      await expectKitApplied(page, kit)
      await page.addStyleTag({
        content: '*,*::before,*::after{transition:none !important;animation:none !important;}',
      })
      await page.waitForTimeout(600)
      const bridgeReport = await auditNonText(page)
      checked += bridgeReport.checked
      skipped += bridgeReport.skipped
      for (const issue of bridgeReport.issues) {
        issues.push({ ...issue, page: `${kit}:bridge`, mode })
      }
      const seenBridge = new Set<string>()
      for (let i = 0; i < 12; i += 1) {
        await page.keyboard.press('Tab')
        await page.waitForTimeout(120)
        const focus = await readFocus(page)
        if (!focus) continue
        const key = `${focus.kind}|${focus.selector}`
        if (seenBridge.has(key)) continue
        seenBridge.add(key)
        checked += 1
        if (focus.kind === 'focus-auto') autoCount += 1
        if (focus.kind === 'focus-mouse') mouseCount += 1
        const skippedKind = focus.kind === 'focus-auto' || focus.kind === 'focus-mouse'
        if (focus.kind === 'focus-missing' || (!skippedKind && focus.ratio < 3)) {
          issues.push({
            kind: focus.kind,
            selector: focus.selector,
            fg: focus.fg,
            bg: focus.bg,
            ratio: focus.ratio,
            count: 1,
            page: `${kit}:bridge`,
            mode,
            detail:
              focus.kind === 'focus-missing'
                ? `无 focus-visible 轮廓/阴影（${focus.indicator}）`
                : focus.indicator,
          })
        }
      }
      // 回到合并部署：下一模式循环还要点主题按钮与菜单
      await page.goto(appUrl(COMBINED, '', kit), { waitUntil: 'domcontentloaded' })
      await expectKitApplied(page, kit)
      await expect(page.locator(profile.nav).filter({ hasText: /主站工作台/ })).toBeVisible({ timeout: 20_000 })
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
      `非文本对比巡检 [${profile.label}]：检查 ${checked} 处，跳过 ${skipped} 处（渐变/未知背景），` +
        `硬失败 ${hard.length} 组；浏览器默认焦点环 ${autoCount} 处（色值由 UA 决定）、` +
        `非键盘焦点 ${mouseCount} 处（WCAG 2.4.7 不适用）。`,
    )

    if (process.env.CONTRAST_REPORT === '1') {
      console.log(`\n报告模式：${hard.length} 组 <3:1（不阻断）。`)
    } else {
      expect(hard, `以下非文本对比度 <3:1：\n${fmt}`).toEqual([])
    }
  })
}
