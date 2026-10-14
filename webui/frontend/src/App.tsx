import { AppLayout } from './layout/AppLayout'
import { LogsPage } from './pages/LogsPage'
import { StatusPage } from './pages/StatusPage'
import { useUiStore } from './store/uiStore'
import { useSchemaHandshake } from './hooks/useSchemaHandshake'
import { useWsBridge } from './ws/useWsBridge'

export default function App() {
  // 契约版本协商（GET /api/schema）+ 全局 WS（snapshot 先行 / 背压感知）
  useSchemaHandshake()
  useWsBridge()
  const page = useUiStore((s) => s.page)

  return <AppLayout>{page === 'logs' ? <LogsPage /> : <StatusPage />}</AppLayout>
}
