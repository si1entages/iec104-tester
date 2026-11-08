import { useT } from '../i18n'

/**
 * 套件样式加载期间的过渡屏。
 *
 * 只用内联样式：此时选中套件的样式表还没加载，不能依赖任何套件 token，
 * 否则会出现「白底白字」或整页跳版。
 */
export function KitSplash() {
  const t = useT()
  return (
    <div
      data-testid="kit-splash"
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
      }}
    >
      <span
        style={{
          width: 34,
          height: 34,
          borderRadius: 8,
          background: '#13c2c2',
          display: 'inline-block',
        }}
      />
      <span style={{ fontSize: 13, opacity: 0.7 }}>IEC104 Tester · {t('common.loading')}</span>
    </div>
  )
}
