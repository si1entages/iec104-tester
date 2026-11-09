/**
 * 套件档案（T89）：页级门禁要在**产品默认套件 Carbon** 与 PatternFly 上都跑。
 *
 * 背景：功能用例（master/slave/…）的 DOM 断言按 PF 编写，因此固定跑 `?kit=pf`；
 * 但页级门禁（ui-audit / ui-contrast / ui-nontext-contrast）检查的是**界面本身**
 * ——裁切、横向溢出、对比度、焦点环——必须覆盖用户默认看到的 Carbon，否则默认套件
 * 的界面缺陷不会被任何自动门禁发现（T89 之前就是如此）。
 *
 * 两套件的 DOM 差异集中在这里：
 *  - **导航**：PF `.pf-v6-c-nav__link` + `pf-m-current`；Carbon `.cds--side-nav__link`
 *    + `cds--side-nav__link--current`；
 *  - **折叠区**：PF ExpandableSection / Carbon AccordionItem；
 *  - **巡检用选择器**：一律取两套件的**并集**（不存在的选择器匹配 0 个元素，无副作用），
 *    这样同一份巡检逻辑对两套件都成立，不必维护两套扫描体。
 *
 * 跑法：`E2E_KITS=pf,carbon`（默认两套）；只跑一套时 `E2E_KITS=pf`。
 */
import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

export type KitName = 'pf' | 'carbon'

export const ALL_KITS: KitName[] = ['pf', 'carbon']

function parseKits(raw: string | undefined): KitName[] {
  const list = (raw ?? ALL_KITS.join(','))
    .split(',')
    .map((s) => s.trim())
    .filter((s): s is KitName => s === 'pf' || s === 'carbon')
  return list.length > 0 ? list : ALL_KITS
}

/** 页级门禁跑哪些套件（默认两套；CI 无需额外配置） */
export const GATE_KITS: KitName[] = parseKits(process.env.E2E_KITS)

export interface KitProfile {
  kit: KitName
  label: string
  /** 侧栏导航项 */
  nav: string
  /** 当前页标记的类名 */
  navCurrent: RegExp
  /** 命令面板折叠区「已收起」的开关按钮 */
  collapsedToggle: string
  /** 主题切换按钮 testid（三套件统一） */
  themeToggle: string
}

export const KIT_PROFILES: Record<KitName, KitProfile> = {
  pf: {
    kit: 'pf',
    label: 'PatternFly',
    nav: '.pf-v6-c-nav__link',
    navCurrent: /pf-m-current/,
    collapsedToggle: '.pf-v6-c-expandable-section__toggle[aria-expanded="false"]',
    themeToggle: 'theme-toggle',
  },
  carbon: {
    kit: 'carbon',
    label: 'Carbon',
    nav: '.cds--side-nav__link',
    navCurrent: /cds--side-nav__link--current/,
    collapsedToggle: 'button.cds--accordion__heading[aria-expanded="false"]',
    themeToggle: 'theme-toggle',
  },
}

export function profileOf(kit: KitName): KitProfile {
  return KIT_PROFILES[kit]
}

/**
 * 断言 URL 上的 `?kit=` 真的生效。
 *
 * 门禁最怕「静默跑错界面」：`?kit=carbon` 若未被识别（回退默认或解析失败），
 * 门禁会在另一套件上全绿却没有覆盖目标套件。`dataset.kit` 由套件宿主在样式就绪后写入，
 * 是可靠的完成信号（见 `docs/ui_kits.md`）。
 */
export async function expectKitApplied(page: Page, kit: KitName): Promise<void> {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.kit), { timeout: 20_000 })
    .toBe(kit)
}

// ── 巡检用选择器（两套件并集） ─────────────────────────────────────────────

/** 明确不应被裁的文案容器（Card/Tile 标题、页签、按钮、表单标签、键值项…） */
export const CLIPPED_TEXT_SELECTORS = [
  // PF
  '.pf-v6-c-card__title-text',
  '.pf-v6-c-tabs__item-text',
  '.pf-v6-c-button__text',
  '.pf-v6-c-alert__title',
  '.pf-v6-c-alert__description',
  '.pf-v6-c-form__label-text',
  '.pf-v6-c-descriptions__label',
  '.pf-v6-c-descriptions__description',
  // Carbon
  '.app-panel-title',
  '.cds--label',
  '.cds--tabs__nav-item-label',
  '.cds--inline-notification__title',
  '.cds--accordion__title',
  '.cds--tag__label',
  '.app-kv-term',
  '.app-kv-value',
  // 共享（工程自有 testid）
  '[data-testid="points-hint"]',
] as const

/** 关键控件：不得超出视口横向边界（表格内横向滚动区豁免） */
export const BOX_SELECTORS = [
  // PF
  '.pf-v6-c-card',
  '.pf-v6-c-tabs',
  '.pf-v6-c-form-control',
  '.pf-v6-c-table',
  '.pf-v6-c-pagination',
  // Carbon
  '.cds--tile',
  '.cds--tabs',
  '.cds--text-input',
  '.cds--data-table',
  '.cds--pagination',
  // 通用
  'button',
  'input',
  'select',
] as const

/** 错误级提示（接口失败 / 契约不一致会落到这里） */
export const ERROR_ALERT_SELECTORS = [
  '.pf-v6-c-alert.pf-m-danger',
  '.cds--inline-notification--error',
] as const

/** 可能漏出 i18n key 的文案容器 */
export const RAW_KEY_SELECTORS = [
  // PF
  '.pf-v6-c-card__title-text',
  '.pf-v6-c-tabs__item-text',
  '.pf-v6-c-nav__link',
  '.pf-v6-c-form__label-text',
  '.pf-v6-c-alert__title',
  '.pf-v6-c-alert__description',
  '.pf-v6-c-descriptions__label',
  '.pf-v6-c-descriptions__description',
  // Carbon
  '.app-panel-title',
  '.cds--side-nav__link-text',
  '.cds--label',
  '.cds--tabs__nav-item-label',
  '.cds--inline-notification__title',
  '.cds--accordion__title',
  '.app-kv-term',
  // 通用
  'button',
] as const

/** 空面板判定时要排除的「有内容」标志（图标/图表/空状态占位） */
export const EMPTY_PANEL_CONTENT_SELECTOR =
  'canvas, svg, img, video, .pf-v6-c-empty-state, .cds--empty-state'

/** 非文本对比：控件边框选择器 */
export const BORDER_SELECTORS = [
  // PF
  '.pf-v6-c-form-control',
  '.pf-v6-c-button.pf-m-secondary',
  '.pf-v6-c-check__input',
  '.pf-v6-c-radio__input',
  '.pf-v6-c-pagination__nav button',
  // Carbon
  '.cds--text-input',
  '.cds--select-input',
  '.cds--btn--secondary',
  '.cds--checkbox',
  '.cds--radio-button__appearance',
  '.cds--pagination__button',
] as const

/** 非文本对比：Switch/Toggle 轨道选择器 */
export const SWITCH_TOGGLE_SELECTORS = [
  '.pf-v6-c-switch__toggle',
  '.cds--toggle__switch',
] as const
