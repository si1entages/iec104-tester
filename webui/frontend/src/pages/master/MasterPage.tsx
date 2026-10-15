import { Suspense, lazy, useCallback, useMemo, useState } from 'react'

import { Alert, Col, Row, Spin, Tabs } from 'antd'

import { useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { PointsTable } from '../../components/PointsTable'
import { pointKey } from '../../lib/pointValue'
import { CommandPanel } from './CommandPanel'
import { ConnectionPanel } from './ConnectionPanel'

// 报文查看器与趋势图（含 ECharts）懒加载：不进主站首屏 chunk，
// 只有切到对应 Tab 才下载。报文查看器是跨页共享组件（见 components/）。
const FrameViewer = lazy(() =>
  import('../../components/FrameViewer').then((m) => ({ default: m.FrameViewer })),
)
const TrendChart = lazy(() => import('./TrendChart').then((m) => ({ default: m.TrendChart })))

function TabFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 24 }}>
      <Spin />
    </div>
  )
}

/** 趋势最多同时观察的点位数（超出会让图例与采样都失控） */
const MAX_TREND = 8

/**
 * 主站工作台（T12）。
 *
 * 布局：连接与状态区 → [点表（十万行虚拟滚动） | 命令面板] → [报文查看器 / 趋势图]。
 * 交互变更：**单击选中行 + 右侧面板下发命令**，不再有「双击值直接发命令」路径。
 */
export default function MasterPage() {
  const { data: status } = useStatusQuery()
  const [selected, setSelected] = useState<Point | null>(null)
  const [watched, setWatched] = useState<Point[]>([])

  const watchedKeys = useMemo(() => watched.map(pointKey), [watched])

  const addTrend = useCallback((point: Point) => {
    setWatched((prev) => {
      const key = pointKey(point)
      if (prev.some((p) => pointKey(p) === key)) return prev
      return [...prev, point].slice(-MAX_TREND)
    })
  }, [])

  const removeTrend = useCallback((key: string) => {
    setWatched((prev) => prev.filter((p) => pointKey(p) !== key))
  }, [])

  if (status?.role === 'slave') {
    return (
      <Alert
        type="info"
        showIcon
        message="当前部署为子站角色"
        description="主站工作台仅在主站（--mode master）下可用；子站工作台见左侧「子站工作台」页。"
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <ConnectionPanel />

      <Row gutter={12}>
        <Col flex="auto" style={{ minWidth: 0 }}>
          <PointsTable
            selected={selected}
            onSelect={setSelected}
            watchedKeys={watchedKeys}
            onAddTrend={addTrend}
          />
        </Col>
        <Col flex="400px">
          <CommandPanel point={selected} disabled={!status?.running} />
        </Col>
      </Row>

      <Tabs
        defaultActiveKey="frames"
        items={[
          {
            key: 'frames',
            label: '报文查看器',
            children: (
              <Suspense fallback={<TabFallback />}>
                <FrameViewer />
              </Suspense>
            ),
          },
          {
            key: 'trend',
            label: '趋势图',
            children: (
              <Suspense fallback={<TabFallback />}>
                <TrendChart
                  watched={watched}
                  onRemove={removeTrend}
                  onClear={() => setWatched([])}
                />
              </Suspense>
            ),
          },
        ]}
      />
    </div>
  )
}
