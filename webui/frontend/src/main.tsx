import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import ReactDOM from 'react-dom/client'

import App from './App'
import { ErrorBoundary } from './layout/ErrorBoundary'
import { applyThemeToDom, resolveInitialTheme } from './lib/themePreference'
import { darkTheme, lightTheme } from './theme'
import { useUiStore } from './store/uiStore'

import 'antd/dist/reset.css'
import './styles/global.css'

// 在 React 渲染前同步解析主题并落到 DOM（body 配色走 CSS data-theme 变量），
// 避免「先浅后深」闪屏；ConfigProvider 的算法随 store.theme 首帧即正确。
const initialTheme = resolveInitialTheme()
applyThemeToDom(initialTheme)

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 2000,
    },
  },
})

const rootEl = document.getElementById('root')
if (!rootEl) throw new Error('#root 节点缺失')

function Root() {
  const theme = useUiStore((s) => s.theme)
  return (
    <ConfigProvider locale={zhCN} theme={theme === 'light' ? lightTheme : darkTheme}>
      <QueryClientProvider client={queryClient}>
        {/* AntdApp 提供 message/notification 的上下文，避免静态方法丢主题 */}
        <AntdApp>
          <ErrorBoundary>
            <App />
          </ErrorBoundary>
        </AntdApp>
      </QueryClientProvider>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
