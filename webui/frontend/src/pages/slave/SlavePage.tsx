import { Suspense, lazy, useState } from 'react'

import { Alert, Col, Row, Spin, Tabs } from 'antd'

import { useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { PointsTable } from '../../components/PointsTable'
import { useT } from '../../i18n'
import { ManualSetPanel } from './ManualSetPanel'
import { ResponsePanel } from './ResponsePanel'
import { SimulationPanel } from './SimulationPanel'
import { SlaveConnectionPanel } from './SlaveConnectionPanel'
import { TestInjectionPanel } from './TestInjectionPanel'

// 报文查看器与主站页**复用同一个组件**（components/FrameViewer），
// 这里只做懒加载，保持与主站页一致的拆包收益。
const FrameViewer = lazy(() =>
  import('../../components/FrameViewer').then((m) => ({ default: m.FrameViewer })),
)

function TabFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 24 }}>
      <Spin />
    </div>
  )
}

/**
 * 子站工作台（T13）。
 *
 * 布局：启动与状态区（含客户端列表）→ [点表 | 手动置数 / 应答行为 / 模拟控制] →
 * 报文查看器（与主站页共享组件）。
 *
 * 点表与主站页共用 `components/PointsTable`：十万行虚拟滚动、WS 就地更新、
 * 过滤能力完全一致，仅选中提示文案不同。
 */
export default function SlavePage() {
  const t = useT()
  const { data: status } = useStatusQuery()
  const [selected, setSelected] = useState<Point | null>(null)

  if (status?.role === 'master') {
    return (
      <Alert
        type="info"
        showIcon
        title={t('slave.masterRole')}
        description={t('slave.masterRoleDesc')}
      />
    )
  }

  const running = Boolean(status?.running)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <SlaveConnectionPanel />

      <Row gutter={12}>
        <Col flex="auto" style={{ minWidth: 0 }}>
          <PointsTable
            selected={selected}
            onSelect={setSelected}
            selectHint={t('slave.selectHint')}
          />
        </Col>
        <Col flex="420px">
          <Tabs
            size="small"
            defaultActiveKey="manual"
            items={[
              {
                key: 'manual',
                label: t('slave.tab.manual'),
                children: <ManualSetPanel point={selected} disabled={!running} />,
              },
              {
                key: 'response',
                label: t('slave.tab.response'),
                children: <ResponsePanel disabled={!running} />,
              },
              {
                key: 'sim',
                label: t('slave.tab.sim'),
                children: <SimulationPanel disabled={!running} selected={selected} />,
              },
              {
                key: 'inject',
                label: t('slave.tab.inject'),
                children: <TestInjectionPanel disabled={!running} />,
              },
            ]}
          />
        </Col>
      </Row>

      <Suspense fallback={<TabFallback />}>
        <FrameViewer />
      </Suspense>
    </div>
  )
}
