import { AppLayout } from './layout/AppLayout'
import { LogsPage } from './pages/LogsPage'
import { StatusPage } from './pages/StatusPage'
import { useUiStore } from './store/uiStore'
import { useWsBridge } from './ws/useWsBridge'

export default function App() {
  // 全局 WS：把 snapshot/log 灌进 React Query 缓存与 Zustand
  useWsBridge()
  const page = useUiStore((s) => s.page)

  return <AppLayout>{page === 'logs' ? <LogsPage /> : <StatusPage />}</AppLayout>
}
