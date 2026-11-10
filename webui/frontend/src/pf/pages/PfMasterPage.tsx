import { useEffect, useMemo, useState } from 'react'

import {
  ActionGroup,
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  Form,
  FormGroup,
  Grid,
  GridItem,
  Label,
  PageSection,
  Tab,
  Tabs,
  TextInput,
} from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useCommand, useCommandNoArgs, usePointsQuery, useStatusQuery } from '../../api/queries'
import type { DoctorRequest, DoctorResponse } from '../../api/types'
import type { Point } from '../../api/types'
import { useT, type MessageKey } from '../../i18n'
import { directCommandKind } from '../../lib/pointCommand'
import { pointKey } from '../../lib/pointValue'
import { trendBuffer } from '../../lib/trendBuffer'
import { useUiStore } from '../../store/uiStore'
import { PfCommandPanel } from '../components/PfCommandPanel'
import { PfDesignDiffCard } from '../components/PfDesignDiffCard'
import { PfFrameViewer } from '../components/PfFrameViewer'
import { PfPointCommandDialog } from '../components/PfPointCommandDialog'
import { PfPointsTable } from '../components/PfPointsTable'
import { PfTrendChart } from '../components/PfTrendChart'

const MAX_TREND = 8

export function PfMasterPage() {
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
  const [tab, setTab] = useState<string | number>('frames')

  const start = useCommand(api.master.start)
  const doctorCmd = useCommand<DoctorRequest, DoctorResponse>(api.master.doctor)
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
    <>
      <PageSection variant="secondary">
        <Card>
          <CardTitle>
            {t('status.connectionCard')}
            <Label isCompact style={{ marginInlineStart: 8 }} color={running ? 'green' : 'grey'}>
              {running ? t('conn.connected') : t('conn.disconnected')}
            </Label>
            {status?.state ? (
              <Label isCompact style={{ marginInlineStart: 4 }} color="blue">
                {status.state}
              </Label>
            ) : null}
          </CardTitle>
          <CardBody>
            {err ? (
              <Alert isInline variant="danger" title={t('common.cmdFailed')} style={{ marginBottom: 12 }}>
                {err instanceof Error ? err.message : String(err)}
              </Alert>
            ) : null}
            <Form onSubmit={(event) => event.preventDefault()}>
              <Grid hasGutter>
                <GridItem span={12} md={4}>
                  <FormGroup label={t('status.host')} fieldId="pf-host">
                    <TextInput id="pf-host" value={host} onChange={(_e, v) => setHost(v)} />
                  </FormGroup>
                </GridItem>
                <GridItem span={12} md={3}>
                  <FormGroup label={t('status.port')} fieldId="pf-port">
                    <TextInput id="pf-port" value={port} onChange={(_e, v) => setPort(v)} />
                  </FormGroup>
                </GridItem>
                <GridItem span={12} md={3}>
                  <FormGroup label={t('status.addr')} fieldId="pf-addr">
                    <TextInput id="pf-addr" value={addr} onChange={(_e, v) => setAddr(v)} />
                  </FormGroup>
                </GridItem>
              </Grid>
              <ActionGroup>
                <Button
                  variant="primary"
                  isDisabled={busy || started}
                  isLoading={start.isPending}
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
                <Button
                  variant="danger"
                  isDisabled={busy || !started}
                  isLoading={stop.isPending}
                  onClick={() => stop.mutate()}
                >
                  {t('conn.disconnect')}
                </Button>
                <Button
                  variant="secondary"
                  isDisabled={!running || gi.isPending}
                  isLoading={gi.isPending}
                  onClick={() => gi.mutate({})}
                >
                  {t('cmd.gi.label')}
                </Button>
                <Button
                  variant="secondary"
                  isDisabled={doctorCmd.isPending}
                  isLoading={doctorCmd.isPending}
                  onClick={() => {
                    doctorCmd.mutate({
                      host,
                      port: Number(port) || 2404,
                      addr: Number(addr) || 1,
                    })
                  }}
                >
                  {doctorCmd.isPending ? t('doctor.running') : t('doctor.button')}
                </Button>
              </ActionGroup>
              {doctorCmd.data ? (
                <Alert
                  variant={doctorCmd.data.report.ok ? 'success' : 'warning'}
                  title={t('doctor.conclusion')}
                  style={{ marginTop: 12 }}
                >
                  <p style={{ marginBottom: 8 }}>{doctorCmd.data.report.conclusion}</p>
                  {doctorCmd.data.report.steps.map((s) => (
                    <div key={s.key} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                      <Label isCompact color={s.ok ? 'green' : 'red'}>
                        {t(`doctor.step.${s.key}` as MessageKey)}
                      </Label>
                      <span style={{ fontSize: 12, color: 'var(--pf-t--global--text--color--subtle)' }}>
                        {s.detail}
                      </span>
                    </div>
                  ))}
                </Alert>
              ) : null}
            </Form>
          </CardBody>
        </Card>
      </PageSection>

      <PageSection>
        <Card>
          <CardTitle>
            <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
              <span>{t('pt2.title')}</span>
              <Button
                variant="secondary"
                size="sm"
                isDisabled={!selected || watchedKeys.includes(selected ? pointKey(selected) : '')}
                onClick={addTrend}
              >
                {t('pt2.addTrend')}
              </Button>
            </Flex>
          </CardTitle>
          <CardBody>
            <PfPointsTable
              selected={selected}
              onSelect={setSelected}
              height={520}
              onValueDoubleClick={(point) => {
                if (!directCommandKind(point)) return
                setSelected(point)
                setCommandPoint(point)
              }}
            />
          </CardBody>
        </Card>
      </PageSection>

      <PageSection>
        <PfCommandPanel point={selected} disabled={!status?.running} />
      </PageSection>

      <PageSection>
        <PfDesignDiffCard />
      </PageSection>

      <PageSection>
        <Tabs activeKey={tab} onSelect={(_event, key) => setTab(key)}>
          <Tab eventKey="frames" title={t('frameViewer.title')}>
            <div style={{ marginTop: 12 }}>
              <PfFrameViewer />
            </div>
          </Tab>
          <Tab eventKey="trend" title={t('trend.title')}>
            <div style={{ marginTop: 12 }}>
              <PfTrendChart
                watched={watched}
                onRemove={(key) => setWatched(watched.filter((p) => pointKey(p) !== key))}
                onClear={() => setWatched([])}
              />
            </div>
          </Tab>
        </Tabs>
      </PageSection>

      <PfPointCommandDialog
        point={commandPoint}
        disabled={!status?.running}
        onClose={() => setCommandPoint(null)}
      />
    </>
  )
}
