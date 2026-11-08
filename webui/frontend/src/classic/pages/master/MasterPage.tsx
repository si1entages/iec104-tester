import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'

import { Alert, Col, Row, Spin, Tabs } from 'antd'

import { usePointsQuery, useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { PointsTable } from '../../components/PointsTable'
import { useT } from '../../i18n'
import { directCommandKind } from '../../lib/pointCommand'
import { pointKey } from '../../lib/pointValue'
import { trendBuffer } from '../../lib/trendBuffer'
import { useUiStore } from '../../store/uiStore'
import { CommandPanel } from './CommandPanel'
import { ConnectionPanel } from './ConnectionPanel'
import { PointCommandDialog } from './PointCommandDialog'

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
 *
 * 交互：单击选中行后由右侧面板下发命令；命令点（YK/YC/STEP）的值单元格
 * 还支持**双击直接下发**——先弹确认框核对点位/方向/目标值，确认后才发请求。
 * SBO 点位不在这里手写两段式，统一交给主站引擎按点表配置「选择→等确认→执行」，
 * 选择失败时不会发送执行帧。
 */
export default function MasterPage() {
  const t = useT()
  const { data: status } = useStatusQuery()
  const { data: points = [] } = usePointsQuery()
  // 选中行与趋势 watch 放共享 store：切菜单/切套件回来不丢。
  // store 里只存选中瞬间的快照（标识字段）；实时 Point 按 key 从点表缓存**现取**——
  // WS 增量补丁只更新缓存，直接用快照会让「当前值」永远停在选中瞬间（bug 修复）
  const selectedStored = useUiStore((s) => s.selectedPoint)
  const setSelected = useUiStore((s) => s.setSelectedPoint)
  const watched = useUiStore((s) => s.trendWatched)
  const setWatched = useUiStore((s) => s.setTrendWatched)
  // 双击命令弹窗只记键：弹窗开着时 WS 快照刷新，弹窗里的「当前值」也跟着更新
  const [commandKey, setCommandKey] = useState<string | null>(null)

  const selected = useMemo(
    () =>
      selectedStored
        ? points.find((p) => pointKey(p) === pointKey(selectedStored)) ?? null
        : null,
    [points, selectedStored],
  )
  const commandPoint = useMemo(
    () => (commandKey ? points.find((p) => pointKey(p) === commandKey) ?? null : null),
    [points, commandKey],
  )
  const onSelect = useCallback(
    (point: Point | null) => {
      setSelected(point)
    },
    [setSelected],
  )
  const onValueDoubleClick = useCallback(
    (point: Point) => {
      // 双击监视点（YX/YM）只保持选中，不产生命令
      if (!directCommandKind(point)) return
      setSelected(point)
      setCommandKey(pointKey(point))
    },
    [setSelected],
  )

  const watchedKeys = useMemo(() => watched.map(pointKey), [watched])

  // 采样注册放在工作台层（而非趋势图组件挂载后）——否则只有打开趋势图页签才开始
  // 采样，此前发生的值变化全部丢失，切过去只看到空图（bug 修复）
  useEffect(() => {
    trendBuffer.setWatched(watchedKeys)
  }, [watchedKeys])

  const addTrend = useCallback(
    (point: Point) => {
      const key = pointKey(point)
      if (watched.some((p) => pointKey(p) === key)) return
      const next = [...watched, point].slice(-MAX_TREND)
      setWatched(next)
      // 立即注册并以当前值作为首个采样：连接空闲（无新值推送）时曲线也有起点，
      // 不用等到下一次值变化才出现第一个点（页面 effect 会用同一组 key 再注册一次，幂等）
      trendBuffer.setWatched(next.map(pointKey))
      trendBuffer.record(key, Date.now() / 1000, point.value)
    },
    [watched, setWatched],
  )

  const removeTrend = useCallback(
    (key: string) => {
      setWatched(watched.filter((p) => pointKey(p) !== key))
    },
    [watched, setWatched],
  )

  if (status?.role === 'slave') {
    return (
      <Alert
        type="info"
        showIcon
        title={t('master.slaveRole')}
        description={t('master.slaveRoleDesc')}
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
            onSelect={onSelect}
            onValueDoubleClick={onValueDoubleClick}
            watchedKeys={watchedKeys}
            onAddTrend={addTrend}
          />
        </Col>
        <Col flex="400px">
          <CommandPanel point={selected} disabled={!status?.running} />
        </Col>
      </Row>

      <PointCommandDialog
        key={commandKey ?? 'closed'}
        point={commandPoint}
        disabled={!status?.running}
        onClose={() => setCommandKey(null)}
      />

      <Tabs
        defaultActiveKey="frames"
        items={[
          {
            key: 'frames',
            label: t('frameViewer.title'),
            children: (
              <Suspense fallback={<TabFallback />}>
                <FrameViewer />
              </Suspense>
            ),
          },
          {
            key: 'trend',
            label: t('trend.title'),
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
