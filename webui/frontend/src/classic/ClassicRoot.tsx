import { App as AntdApp, ConfigProvider } from 'antd'
import enUS from 'antd/locale/en_US'
import zhCN from 'antd/locale/zh_CN'

import App from './App'
import { ErrorBoundary } from './layout/ErrorBoundary'
import { useUiStore } from './store/uiStore'
import { darkTheme, lightTheme } from './theme'

/**
 * 经典版（antd 6）套件根：v1.3.1 界面，挂到共享数据运行时上。
 *
 * - 数据运行时（QueryClient / WS 桥 / 契约协商）由 `src/main.tsx` 常驻；
 * - 全局样式（antd reset + global.css）由 `useKitCss` 按套件加载/移除；
 * - 主题与语言沿用共享 `uiStore`，与 PatternFly 版保持一致。
 */
export default function ClassicRoot() {
  const theme = useUiStore((s) => s.theme)
  const locale = useUiStore((s) => s.locale)

  return (
    <ConfigProvider
      locale={locale === 'en' ? enUS : zhCN}
      theme={theme === 'light' ? lightTheme : darkTheme}
    >
      {/* AntdApp 提供 message/notification 的上下文，避免静态方法丢主题 */}
      <AntdApp>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </AntdApp>
    </ConfigProvider>
  )
}
