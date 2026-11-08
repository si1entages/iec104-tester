import { useEffect, useMemo, useState } from 'react'

import { Button, Tab, TabList, TabPanel, TabPanels, Tabs, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, usePointsQuery, useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { useT } from '../../i18n'
import { directCommandKind } from '../../lib/pointCommand'
import { pointKey } from '../../lib/pointValue'
import { trendBuffer } from '../../lib/trendBuffer'
import { useUiStore } from '../../store/uiStore'
import { CarbonCommandPanel } from '../components/CarbonCommandPanel'
import { CarbonFrameViewer } from '../components/CarbonFrameViewer'
import { CarbonPointCommandDialog } from '../components/CarbonPointCommandDialog'
import { CarbonPointsTable } from '../components/CarbonPointsTable'
import { CarbonTrendChart } from '../components/CarbonTrendChart'
import { Note, Panel, TextField } from '../components/ui'

const MAX_TREND = 8

export function CarbonMasterPage() {
  const t = useT()
  const { data: status } = useStatusQuery()
  const { data: points = [] } = usePointsQuery()
  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState('2404')
  const [addr, setAddr] = useState('1')
  // 选中行与趋势 watch 放共享 store：切菜单/切套件回来不丢。
  // store 里的 Point 只是选中瞬间的快照（标识字段），这里按 key 从点表缓存**现取**，
  // 让命令面板的「当前值」跟随 WS 更新，而不是停在选中瞬间（与经典版同一 bug 修复）
  const selectedStored = useUiStore((s) => s.selectedPoint)
  const setSelected = useUiStore((s) => s.setSelectedPoint)
  const watched = useUiStore((s) => s.trendWatched)
  const setWatched = useUiStore((s) => s.setTrendWatched)
  const selected = useMemo(
    () =>
      selectedStored
        ? points.find((p) => pointKey(p) === pointKey(selectedStored)) ?? null
        : null,
    [points, selectedStored],
  )
  const [commandPoint, setCommandPoint] = useState<Point | null>(null)
  const [tab, setTab] = useState(0)

  const start = useCommand(api.master.start)
  const stop = useCommandNoArgs(api.master.stop)
  const gi = useCommand(api.master.gi)

  const running = Boolean(status?.running)
  const started = Boolean(status?.started)
  const busy = start.isPending || stop.isPending
  const err = start.error ?? stop.error ?? gi.error

  // 趋势采样在工作台层注册：切到趋势页签之前的变化也要被记录下来
  const watchedKeys = watched.map(pointKey)
  useEffect(() => {
    trendBuffer.setWatched(watchedKeys)
  }, [watchedKeys])

  const addTrend = (): void => {
    if (!selected) return
    const key = pointKey(selected)
    if (watched.some((p) => pointKey(p) === key)) return
    const next = [...watched, selected].slice(-MAX_TREND)
    setWatched(next)
    // 立即注册并以当前值作为首个采样：连接空闲（无新值推送）时曲线也有起点，
    // 不用等到下一次值变化才出现第一个点（页面 effect 会用同一组 key 再注册一次，幂等）
    trendBuffer.setWatched(next.map(pointKey))
    trendBuffer.record(key, Date.now() / 1000, selected.value)
  }

  return (
    <div className="app-gap">
      <Panel
        title={
          <span className="app-row">
            {t('status.connectionCard')}
            <Tag size="sm" type={running ? 'green' : 'gray'}>
              {running ? t('conn.connected') : t('conn.disconnected')}
            </Tag>
            {status?.state ? (
              <Tag size="sm" type="blue">
                {status.state}
              </Tag>
            ) : null}
          </span>
        }
      >
        {err ? <Note kind="error" title={t('common.cmdFailed')} style={{ marginBottom: 12 }}>{err instanceof Error ? err.message : String(err)}</Note> : null}
        <form onSubmit={(event) => event.preventDefault()}>
          <div className="app-row" style={{ alignItems: 'flex-end' }}>
            <TextField id="cb-host" label={t('status.host')} value={host} onChange={setHost} width={220} />
            <TextField id="cb-port" label={t('status.port')} value={port} onChange={setPort} width={140} />
            <TextField id="cb-addr" label={t('status.addr')} value={addr} onChange={setAddr} width={140} />
          </div>
          <div className="app-row" style={{ marginTop: 12 }}>
            <Button
              kind="primary"
              disabled={busy || started}
              onClick={() => {
                start.mutate({
                  host,
                  port: Number(port) || 2404,
                  addr: Number(addr) || 1,
                })
              }}
            >
              {t('conn.connect')}
            </Button>
            <Button kind="danger" disabled={busy || !started} onClick={() => stop.mutate()}>
              {t('conn.disconnect')}
            </Button>
            <Button
              kind="secondary"
              disabled={!running || gi.isPending}
              onClick={() => gi.mutate({})}
            >
              {t('cmd.gi.label')}
            </Button>
          </div>
        </form>
      </Panel>

      <Panel
        title={
          <span className="app-row">
            {t('pt2.title')}
            <Button
              kind="secondary"
              size="sm"
              disabled={!selected || watchedKeys.includes(selected ? pointKey(selected) : '')}
              onClick={addTrend}
            >
              {t('pt2.addTrend')}
            </Button>
          </span>
        }
      >
        <CarbonPointsTable
          selected={selected}
          onSelect={setSelected}
          height={520}
          onValueDoubleClick={(point) => {
            if (!directCommandKind(point)) return
            setSelected(point)
            setCommandPoint(point)
          }}
        />
      </Panel>

      <CarbonCommandPanel point={selected} disabled={!status?.running} />

      <Tabs selectedIndex={tab} onChange={({ selectedIndex }) => setTab(selectedIndex)}>
        <TabList aria-label={t('frameViewer.title')}>
          <Tab>{t('frameViewer.title')}</Tab>
          <Tab>{t('trend.title')}</Tab>
        </TabList>
        <TabPanels>
          <TabPanel>
            <div style={{ marginTop: 12 }}>
              <CarbonFrameViewer />
            </div>
          </TabPanel>
          <TabPanel>
            <div style={{ marginTop: 12 }}>
              <CarbonTrendChart
                watched={watched}
                onRemove={(key) => setWatched(watched.filter((p) => pointKey(p) !== key))}
                onClear={() => setWatched([])}
              />
            </div>
          </TabPanel>
        </TabPanels>
      </Tabs>

      <CarbonPointCommandDialog
        point={commandPoint}
        disabled={!status?.running}
        onClose={() => setCommandPoint(null)}
      />
    </div>
  )
}
