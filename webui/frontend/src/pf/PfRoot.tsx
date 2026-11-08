import { PfApp } from './PfApp'

/**
 * PatternFly 套件根：只负责挂载外壳。
 *
 * 数据运行时（QueryClientProvider / WS 桥 / 契约协商）与样式表由 `src/main.tsx`
 * 统一管理，套件之间切换时不断连、不重复建连。
 */
export default function PfRoot() {
  return <PfApp />
}
