import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import ReactDOM from 'react-dom/client'

import App from './App'
import { ErrorBoundary } from './layout/ErrorBoundary'
import { appTheme } from './theme'

import 'antd/dist/reset.css'
import './styles/global.css'

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

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        {/* AntdApp 提供 message/notification 的上下文，避免静态方法丢主题 */}
        <AntdApp>
          <ErrorBoundary>
            <App />
          </ErrorBoundary>
        </AntdApp>
      </QueryClientProvider>
    </ConfigProvider>
  </React.StrictMode>,
)
