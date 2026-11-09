/**
 * 配色对比度自动巡检（WCAG 2.1 近似实现，零依赖）。
 *
 * 目的：把「看得清吗」里**可量化**的部分自动化——文字前景色 vs 有效背景色的
 * 对比度。审美（留白、层级、配色是否好看）不在这里判定；这里只回答
 * 「这段文字/占位符在它实际渲染的背景上，对比度够不够」。
 *
 * 算法：
 *  - 只取**直接包含文本节点**的可见元素（父容器不重复计数）；
 *  - 背景色沿祖先链做 alpha 合成，直到遇到不透明背景；
 *  - 前景色 alpha × 祖先 opacity 后再与背景合成；
 *  - 大字（≥24px，或 ≥18.66px 且 bold）阈值 3:1，其余 4.5:1（WCAG AA）；
 *  - `disabled` / `aria-disabled` 的控件按 WCAG 豁免，单列 info 不计失败；
 *  - 渐变/背景图/Canvas 上的文字无法可靠取样，标记为 unknown 跳过（不误报）。
 *
 * 门禁策略：普通文本 < 3:1 直接失败（明显不可读）；3:1~4.5:1 作为
 * 「AA 建议项」打印在报告里，不阻断（预置的成功/错误色属于设计选择）。
 * 需要只看报告不阻断时设 `CONTRAST_REPORT=1`。
 *
 * **套件维度（T89）**：按 `GATE_KITS`（默认 `pf,carbon`）各跑一遍——产品默认套件
 * Carbon 必须有同样的对比度门禁，选择器差异见 `kitProfiles.ts`。
 */
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { COMBINED , appUrl } from './helpers'
import { GATE_KITS, expectKitApplied, profileOf } from './kitProfiles'

test.describe.configure({ mode: 'serial' })

interface ContrastIssue {
  kind: string
  text: string
  selector: string
  fg: string
  bg: string
  ratio: number
  required: number
  fontSize: string
  count: number
}

interface ContrastReport {
  issues: ContrastIssue[]
  unknown: number
  checked: number
}

async function auditContrast(page: Page): Promise<ContrastReport> {
  return page.evaluate(() => {
    interface Rgba { r: number; g: number; b: number; a: number }
    const parse = (value: string): Rgba | null => {
      const m = value.match(/rgba?\(([^)]+)\)/)
      if (!m) return null
      const p = m[1].split(/[,/\s]+/).filter(Boolean).map(Number)
      if (p.length < 3 || p.some((n) => Number.isNaN(n))) return null
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }
    }
    const blend = (fg: Rgba, bg: Rgba): Rgba => ({
      r: fg.r * fg.a + bg.r * (1 - fg.a),
      g: fg.g * fg.a + bg.g * (1 - fg.a),
      b: fg.b * fg.a + bg.b * (1 - fg.a),
      a: 1,
    })
    const luminance = (c: Rgba): number => {
      const f = (v: number): number => {
        const x = v / 255
        return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
      }
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b)
    }
    const ratio = (a: Rgba, b: Rgba): number => {
      const la = luminance(a)
      const lb = luminance(b)
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
    }
    const css = (c: Rgba): string =>
      `rgb(${Math.round(c.r)}, ${Math.round(c.g)}, ${Math.round(c.b)})`

    const visible = (el: Element): boolean => {
      const r = el.getBoundingClientRect()
      if (r.width <= 0 || r.height <= 0) return false
      const s = getComputedStyle(el)
      if (s.display === 'none' || s.visibility === 'hidden') return false
      // 祖先 opacity=0 / overflow 裁到完全不可见（如 Switch 隐藏的另一侧文字）
      let node: Element | null = el
      while (node && node !== document.body) {
        const ns = getComputedStyle(node)
        if (Number(ns.opacity) === 0) return false
        if (
          (ns.overflow === 'hidden' || ns.overflowX === 'hidden' || ns.overflowY === 'hidden')
        ) {
          const nr = node.getBoundingClientRect()
          if (
            r.right <= nr.left + 0.5 || r.left >= nr.right - 0.5 ||
            r.bottom <= nr.top + 0.5 || r.top >= nr.bottom - 0.5
          ) {
            return false
          }
        }
        node = node.parentElement
      }
      return true
    }

    /** 元素的有效背景（沿祖先做 alpha 合成）；无法可靠判断时返回 null */
    const effectiveBg = (el: Element): Rgba | null => {
      const layers: Rgba[] = []
      let node: Element | null = el
      while (node) {
        const s = getComputedStyle(node)
        if (s.backgroundImage !== 'none') return null // 渐变/图片：不做猜测
        let c = parse(s.backgroundColor)
        // PF 常见：Label/Tag 的底色画在 ::before 伪元素上（z-index:-1）
        if (!c || c.a === 0) {
          const bs = getComputedStyle(node, '::before')
          const fullInset =
            bs.top === '0px' && bs.right === '0px' && bs.bottom === '0px' && bs.left === '0px'
          // 只把「铺满元素」的伪元素当作背景；左侧指示条之类的局部装饰不算
          if (bs.content !== 'none' && bs.backgroundImage === 'none' && fullInset) {
            c = parse(bs.backgroundColor)
          }
        }
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

    const cumulativeOpacity = (el: Element): number => {
      let op = 1
      let node: Element | null = el
      while (node) {
        op *= Number(getComputedStyle(node).opacity) || 1
        node = node.parentElement
      }
      return op
    }

    const isDisabled = (el: Element): boolean =>
      Boolean(
        el.closest(
          '[disabled], [aria-disabled="true"], .pf-m-disabled, .cds--btn--disabled',
        ),
      )

    const selectorOf = (el: Element): string => {
      const cls = typeof el.className === 'string'
        ? el.className.split(/\s+/).filter(Boolean).slice(0, 2).join('.')
        : ''
      return `${el.tagName.toLowerCase()}${cls ? `.${cls}` : ''}`
    }

    const groups = new Map<string, ContrastIssue>()
    let unknown = 0
    let checked = 0

    const add = (
      kind: string, text: string, el: Element, fg: Rgba, bg: Rgba,
      need: number, size: string,
    ): void => {
      const r = ratio(fg, bg)
      // 低于 3:1 才算硬失败；3~4.5 计入建议项
      if (r >= 4.5) return
      const fgCss = css(fg)
      const bgCss = css(bg)
      const key = `${kind}|${fgCss}|${bgCss}|${need}`
      const existing = groups.get(key)
      if (existing) {
        existing.count += 1
      } else {
        groups.set(key, {
          kind, text: text.slice(0, 50), selector: selectorOf(el),
          fg: fgCss, bg: bgCss, ratio: Math.round(r * 100) / 100,
          required: need, fontSize: size, count: 1,
        })
      }
    }

    const check = (el: Element, text: string, kind: string): void => {
      if (!text.trim() || !visible(el)) return
      const s = getComputedStyle(el)
      const fgRaw = parse(s.color)
      const bg = effectiveBg(el)
      if (!fgRaw || !bg) {
        unknown += 1
        return
      }
      checked += 1
      const op = cumulativeOpacity(el)
      const fg = blend({ ...fgRaw, a: fgRaw.a * op }, bg)
      const px = Number.parseFloat(s.fontSize)
      const weight = Number.parseInt(s.fontWeight, 10) || 400
      const large = px >= 24 || (px >= 18.66 && weight >= 700)
      add(kind, text, el, fg, bg, large ? 3 : 4.5, s.fontSize)
    }

    for (const el of document.querySelectorAll('*')) {
      if (['SCRIPT', 'STYLE', 'SVG', 'CANVAS'].includes(el.tagName)) continue
      if (el.getAttribute('aria-hidden') === 'true') continue
      const direct = Array.from(el.childNodes)
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => n.textContent ?? '')
        .join(' ')
        .replace(/\s+/g, ' ')
        .trim()
      if (direct) check(el, direct, isDisabled(el) ? 'disabled-text' : 'text')
    }

    // 占位符（输入框里的提示文字同样要能看清）
    for (const el of document.querySelectorAll('input[placeholder], textarea[placeholder]')) {
      if (!visible(el)) continue
      const placeholder = el.getAttribute('placeholder') ?? ''
      if (!placeholder.trim()) continue
      const s = getComputedStyle(el)
      const pseudo = getComputedStyle(el, '::placeholder')
      const fgRaw = parse(pseudo.color)
      const bg = effectiveBg(el)
      if (!fgRaw || !bg) {
        unknown += 1
        continue
      }
      checked += 1
      add('placeholder', placeholder, el, blend(fgRaw, bg), bg, 4.5, s.fontSize)
    }

    return { issues: [...groups.values()], unknown, checked }
  })
}

for (const kit of GATE_KITS) {
  const profile = profileOf(kit)

  test(`配色对比度巡检 [${profile.label}]：浅色/深色 × 8 个页面（WCAG AA 近似）`, async ({ page }) => {
    test.setTimeout(240_000)
    const issues: (ContrastIssue & { page: string; mode: string })[] = []
    let checked = 0
    let unknown = 0

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

    await page.goto(appUrl(COMBINED, '', kit), { waitUntil: 'domcontentloaded' })
    await expectKitApplied(page, kit)
    await expect(page.locator(profile.nav).filter({ hasText: /主站工作台/ })).toBeVisible({ timeout: 20_000 })
    await page.setViewportSize({ width: 1366, height: 768 })

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
        await page.waitForTimeout(700)
        const report = await auditContrast(page)
        checked += report.checked
        unknown += report.unknown
        for (const issue of report.issues) {
          issues.push({ ...issue, page: `${kit}:${meta.key}`, mode })
        }

        // 选中一行：选中标签、命令/置数面板、禁用→可用等状态下的文字也要查
        if (meta.key === 'master' || meta.key === 'slave') {
          const row = page.locator('[data-testid="point-row"]').first()
          if ((await row.count()) > 0) {
            await row.click()
            await page.waitForTimeout(300)
            const selected = await auditContrast(page)
            checked += selected.checked
            unknown += selected.unknown
            for (const issue of selected.issues) {
              issues.push({ ...issue, page: `${kit}:${meta.key}-selected`, mode })
            }
          }
        }
      }
    }

    const hard = issues.filter((i) => i.kind !== 'disabled-text' && i.ratio < 3)
    const advice = issues.filter((i) => i.kind !== 'disabled-text' && i.ratio >= 3)
    const disabled = issues.filter((i) => i.kind === 'disabled-text')

    const fmt = (rows: typeof issues): string =>
      rows
        .sort((a, b) => a.ratio - b.ratio)
        .map(
          (i) =>
            `  [${i.mode}/${i.page}] ${i.ratio}:1 (需 ${i.required}:1) ${i.kind} ` +
            `${i.selector} ${i.fontSize} fg=${i.fg} bg=${i.bg} ×${i.count} 「${i.text}」`,
        )
        .join('\n')

    if (advice.length > 0) {
      console.log(`\n对比度建议项（3:1~4.5:1，WCAG AA 小字未达标，不阻断）：\n${fmt(advice)}\n`)
    }
    if (disabled.length > 0) {
      console.log(`\n禁用态低对比（WCAG 豁免，仅记录）：\n${fmt(disabled)}\n`)
    }
    if (hard.length > 0) {
      console.log(`\n对比度硬失败（<3:1）：\n${fmt(hard)}\n`)
    }
    console.log(
      `对比度巡检 [${profile.label}]：检查 ${checked} 处文本，跳过 ${unknown} 处（渐变/图片/未知背景）。`,
    )

    if (process.env.CONTRAST_REPORT === '1') {
      console.log(
        hard.length > 0
          ? `\n报告模式：${hard.length} 组文本 <3:1（不阻断）。`
          : '\n报告模式：无 <3:1 文本。',
      )
    } else {
      expect(
        hard,
        `以下文本对比度 <3:1（明显不可读）：\n${fmt(hard)}`,
      ).toEqual([])
    }
  })
}
