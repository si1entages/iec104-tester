import { useEffect, useRef, useState } from 'react'

import { useT } from '../i18n'
import { useUiStore } from '../store/uiStore'
import { AVAILABLE_KITS, KIT_IDS, useKitStore } from './store'
import type { KitId } from './store'

const LABEL_KEY: Record<KitId, 'kit.pf' | 'kit.classic' | 'kit.carbon'> = {
  pf: 'kit.pf',
  classic: 'kit.classic',
  carbon: 'kit.carbon',
}

/**
 * 界面套件切换器（同地址、页内即时切换）。
 *
 * 独立于各套件渲染：三套 UI 的组件库/主题体系互不相同，切换器本身用原生
 * 元素 + 内联样式，避免把某一套件的按钮样式带进另一套件。
 *
 * 默认收起为右下角 32px 圆钮，避免遮挡数据表/命令面板；点开后才展开选项，
 * 点击外部或按 Esc 收起。
 */
export function KitSwitcher() {
  const t = useT()
  const theme = useUiStore((s) => s.theme)
  const kit = useKitStore((s) => s.kit)
  const setKit = useKitStore((s) => s.setKit)
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement | null>(null)
  const dark = theme === 'dark'

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent): void => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const palette = dark
    ? { bg: '#1b2129', border: '#333c48', fg: '#d9d9d9', idle: 'transparent', activeFg: '#04282a' }
    : { bg: '#ffffff', border: '#d0d5dd', fg: '#1f1f1f', idle: 'transparent', activeFg: '#04282a' }

  return (
    <div
      ref={boxRef}
      style={{
        position: 'fixed',
        right: 16,
        bottom: 16,
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: 6,
      }}
    >
      {open ? (
        <div
          data-testid="kit-switcher"
          role="group"
          aria-label={t('kit.label')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            padding: 3,
            borderRadius: 999,
            background: palette.bg,
            border: `1px solid ${palette.border}`,
            boxShadow: '0 2px 10px rgba(0, 0, 0, 0.18)',
            fontSize: 12,
            lineHeight: 1,
          }}
        >
          <span style={{ paddingInline: 8, color: palette.fg, opacity: 0.7 }}>{t('kit.label')}</span>
          {KIT_IDS.map((id) => {
            const available = AVAILABLE_KITS.includes(id)
            const active = kit === id
            const name = t(LABEL_KEY[id])
            return (
              <button
                key={id}
                type="button"
                data-kit={id}
                disabled={!available}
                aria-pressed={active}
                title={available ? t('kit.switchTo', { name }) : `${name} · ${t('kit.soon')}`}
                onClick={() => {
                  if (!available) return
                  setKit(id)
                  setOpen(false)
                }}
                style={{
                  border: 0,
                  borderRadius: 999,
                  padding: '5px 10px',
                  font: 'inherit',
                  cursor: available ? 'pointer' : 'not-allowed',
                  opacity: available ? 1 : 0.45,
                  background: active ? '#13c2c2' : palette.idle,
                  color: active ? palette.activeFg : palette.fg,
                  fontWeight: active ? 600 : 400,
                }}
              >
                {name}
                {available ? null : (
                  <span style={{ marginInlineStart: 4, opacity: 0.8 }}>({t('kit.soon')})</span>
                )}
              </button>
            )
          })}
        </div>
      ) : null}
      {/* 圆钮外层带同色背景：焦点环画在外侧，相邻色取父容器背景（对比度门禁同口径） */}
      <span style={{ display: 'inline-flex', borderRadius: '50%', background: palette.bg, lineHeight: 0 }}>
        <button
          type="button"
          data-testid="kit-switcher-toggle"
          aria-label={t('kit.label')}
          aria-expanded={open}
          title={t('kit.label')}
          onClick={() => setOpen((v) => !v)}
          style={{
            width: 34,
            height: 34,
            borderRadius: '50%',
            border: `1px solid ${palette.border}`,
            background: palette.bg,
            color: palette.fg,
            boxShadow: '0 2px 10px rgba(0, 0, 0, 0.18)',
            font: '600 10px/1 system-ui, sans-serif',
            letterSpacing: 0.4,
            cursor: 'pointer',
          }}
        >
          UI
        </button>
      </span>
    </div>
  )
}
