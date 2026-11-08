import antdResetCss from 'antd/dist/reset.css?url'
import carbonStylesCss from '@carbon/styles/css/styles.css?url'
import patternflyCss from '@patternfly/patternfly/patternfly.css?url'

import carbonAppCss from '../carbon/carbon.css?url'
import classicCss from '../classic/styles/global.css?url'
import pfCss from '../pf/pf.css?url'

import type { KitId } from './store'

/**
 * 各套件的样式表（`?url` 只产出资源 URL，不自动注入）。
 *
 * 为什么不让 Vite 自动注入：三套 UI 共用同一个文档，PF 的 base 层有全局
 * `:where(body|ul|table|td|th|a)` 规则，antd 的 reset 也作用于全局元素，
 * Carbon 的 styles.css 同样带全局 reset（`*` 盒模型、body 边距、Plex 字体）；
 * 同一时刻只允许当前套件的样式表在 `<head>` 里，切走即移除，避免互相污染。
 *
 * antd 6 的组件样式是 CSS-in-JS 运行时注入（`.ant-*` 命名空间），切走后
 * 残留也无副作用；这里管理的是它的全局 reset。
 */
const KIT_CSS: Record<KitId, string[]> = {
  pf: [patternflyCss, pfCss],
  classic: [antdResetCss, classicCss],
  carbon: [carbonStylesCss, carbonAppCss],
}

const ATTR = 'data-kit-css'

function linksFor(href: string): HTMLLinkElement[] {
  return Array.from(document.querySelectorAll<HTMLLinkElement>(`link[${ATTR}]`)).filter(
    (el) => el.getAttribute('href') === href,
  )
}

function loadCss(href: string): Promise<void> {
  const existing = linksFor(href)[0]
  if (existing) return Promise.resolve()
  return new Promise((resolve) => {
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = href
    link.setAttribute(ATTR, '')
    // 样式加载失败不阻塞界面（保持可交互，缺失样式比白屏可诊断）
    link.onload = () => resolve()
    link.onerror = () => resolve()
    document.head.appendChild(link)
  })
}

/**
 * 切到指定套件：先加载新样式，再移除旧套件样式。
 * 顺序保证切换过程中不会出现「无样式」闪烁。
 */
export async function applyKitCss(kit: KitId): Promise<void> {
  const wanted = new Set(KIT_CSS[kit])
  await Promise.all([...wanted].map(loadCss))
  document.querySelectorAll<HTMLLinkElement>(`link[${ATTR}]`).forEach((el) => {
    if (!wanted.has(el.getAttribute('href') ?? '')) el.remove()
  })
}

/** 卸载时清理（正常情况下根节点不会卸载，仅用于测试/热更新）。 */
export function clearKitCss(): void {
  document.querySelectorAll(`link[${ATTR}]`).forEach((el) => el.remove())
}
