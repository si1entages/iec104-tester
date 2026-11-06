import { useCallback, useMemo, useState } from 'react'

import { CloudServerOutlined, PlusOutlined, PlayCircleOutlined, StopOutlined } from '@ant-design/icons'
import { Alert, App as AntdApp, Button, Card, Space, Tag, Typography } from 'antd'

import { api } from '../../api/endpoints'
import {
  useCommand,
  useCommandNoArgs,
  useMultiStatusQuery,
  useMultiSummaryQuery,
} from '../../api/queries'
import { useT } from '../../i18n'
import { MultiStatusView } from './MultiStatusView'
import { StationCard } from './StationCard'
import type { DraftStation } from './stationDraft'
import { newStation, toStationConfigs, validateDraft } from './stationDraft'

function sameSet(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false
  for (const v of a) if (!b.has(v)) return false
  return true
}

/**
 * 多站工作台（T16）——在 Web 端增删 / 启停多个子站，并看聚合状态。
 *
 * ## 为什么这里把「单站启停」做成「重建」
 * 后端只暴露整体启停：`POST /api/multi/start` 用一次请求里的 `stations[]`
 * 创建**整个** `MultiStationManager`，没有「向运行中的管理器增删一个站」的端点。
 * 因此单站启停只能表达为：**停止全部 → 以目标站集合重新启动**。
 * 这一点在界面上是**显式标注**的（草稿开关 + 重建提示 + 表格里的二次确认），
 * 不做成看起来像单项操作、其实会连带影响其他站的样子。
 *
 * ## 角色可见性
 * 多站管理器挂在 Web 会话上，**与 `--mode master/slave` 无关**
 * （`webui/session.py`：多站管理器与主/子站会话独立；其用途是**子站侧压力测试**——
 * 一次性拉起多个子站去压被测主站）。所以「多站」入口在主站、子站两种角色下**都可见**，
 * 不按角色隐藏；页面顶部给出一条说明避免误认为它是当前会话的子功能。
 */
export default function MultiPage() {
  const t = useT()
  const { message } = AntdApp.useApp()

  const statusQuery = useMultiStatusQuery()
  const summaryQuery = useMultiSummaryQuery()
  const running = Boolean(summaryQuery.data?.running ?? statusQuery.data?.running)

  const [draft, setDraft] = useState<DraftStation[]>(() => [newStation(1), newStation(2)])
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const start = useCommand(api.multi.start)
  const stop = useCommandNoArgs(api.multi.stop)
  const busy = start.isPending || stop.isPending

  const issues = useMemo(() => validateDraft(draft), [draft])

  const runningIds = useMemo(
    () => new Set((statusQuery.data?.stations ?? []).map((s) => s.station_id)),
    [statusQuery.data],
  )
  const enabledIds = useMemo(
    () => new Set(draft.filter((s) => s.enabled).map((s) => s.station_id)),
    [draft],
  )
  const pendingRebuild = running && !sameSet(runningIds, enabledIds)

  const patch = useCallback((index: number, next: Partial<DraftStation>) => {
    setDraft((prev) => prev.map((s, i) => (i === index ? { ...s, ...next } : s)))
  }, [])

  const report = useCallback(
    (ok: boolean, text: string): void => {
      setLast({ ok, text })
      if (ok) message.success(text)
      else message.error(text)
    },
    [message],
  )

  /** 统一把「网络/400/业务失败」都收敛成一条可见错误，绝不静默 */
  const runStart = useCallback(
    async (stations: DraftStation[]): Promise<boolean> => {
      const payload = toStationConfigs(stations)
      if (payload.length === 0) {
        report(false, t('multi.noEnabled'))
        return false
      }
      try {
        const r = await start.mutateAsync({ stations: payload })
        if (!r.ok) {
          report(false, t('multi.startFailed', { error: r.error ?? t('cmd.unknown') }))
          return false
        }
        report(true, t('multi.started', { n: r.stations ?? payload.length }))
        return true
      } catch (e) {
        report(false, t('multi.startFailed', { error: (e as Error).message }))
        return false
      }
    },
    [start, report, t],
  )

  const runStop = useCallback(async (): Promise<boolean> => {
    try {
      const r = await stop.mutateAsync()
      if (!r.ok) {
        report(false, t('multi.stopFailed', { error: r.error ?? t('cmd.unknown') }))
        return false
      }
      report(true, t('multi.stoppedAll'))
      return true
    } catch (e) {
      report(false, t('multi.stopFailed', { error: (e as Error).message }))
      return false
    }
  }, [stop, report, t])

  /** 以目标草稿「重建」管理器：先停全部，再按启用站启动 */
  const rebuild = useCallback(
    async (next: DraftStation[]): Promise<void> => {
      const stopped = await runStop()
      if (!stopped) return
      if (toStationConfigs(next).length === 0) {
        setDraft(next)
        setLast({ ok: true, text: t('multi.stoppedNoEnabled') })
        return
      }
      const ok = await runStart(next)
      if (ok) setDraft(next)
    },
    [runStop, runStart, t],
  )

  const onStartAll = (): void => {
    if (issues.length > 0) {
      report(
        false,
        t('multi.validationFailed', {
          first: issues[0],
          more: issues.length > 1 ? t('multi.validationMore', { n: issues.length }) : '',
        }),
      )
      return
    }
    void runStart(draft)
  }

  const onDisableStation = (stationId: string): void => {
    void rebuild(draft.map((s) => (s.station_id === stationId ? { ...s, enabled: false } : s)))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Alert
        type="info"
        showIcon
        closable
        message={t('multi.roleNote')}
        description={t('multi.roleNoteDesc')}
      />

      {last ? (
        <Alert
          type={last.ok ? 'success' : 'error'}
          showIcon
          message={last.text}
          closable
          onClose={() => setLast(null)}
        />
      ) : null}

      <Card
        size="small"
        title={
          <Space wrap>
            <CloudServerOutlined />
            <span>{t('multi.draftTitle')}</span>
            <Tag color="blue">{draft.length}</Tag>
            <Tag color="green">{t('multi.enabledCount', { n: enabledIds.size })}</Tag>
            {running ? <Tag color="orange">{t('multi.runningFrozen')}</Tag> : null}
            {pendingRebuild ? <Tag color="warning">{t('multi.pendingChanges')}</Tag> : null}
          </Space>
        }
        extra={
          <Space wrap>
            <Button
              size="small"
              icon={<PlusOutlined />}
              disabled={running}
              onClick={() => setDraft((prev) => [...prev, newStation(prev.length + 1)])}
            >
              {t('multi.addStation')}
            </Button>
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              loading={start.isPending}
              disabled={running || busy}
              onClick={onStartAll}
            >
              {t('multi.startAll')}
            </Button>
            <Button
              danger
              size="small"
              icon={<StopOutlined />}
              loading={stop.isPending}
              disabled={!running || busy}
              onClick={() => void runStop()}
            >
              {t('multi.stopAll')}
            </Button>          </Space>
        }
      >
        {issues.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('multi.validationIssues', { n: issues.length })}
            description={
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {issues.map((it) => (
                  <li key={it}>{it}</li>
                ))}
              </ul>
            }
          />
        ) : null}

        {pendingRebuild ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('multi.stationMismatch')}
            description={
              <Space>
                <Typography.Text style={{ fontSize: 12 }}>
                  {t('multi.runningCount', { running: runningIds.size, enabled: enabledIds.size })}
                </Typography.Text>
                <Button
                  size="small"
                  type="primary"
                  loading={busy}
                  onClick={() => void rebuild(draft)}
                >
                  {t('multi.rebuild')}
                </Button>
              </Space>
            }
          />
        ) : null}

        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {draft.length === 0 ? (
            <Typography.Text type="secondary">{t('multi.empty')}</Typography.Text>
          ) : (
            draft.map((station, i) => (
              <StationCard
                key={`${station.station_id}-${i}`}
                station={station}
                index={i}
                frozen={running}
                onChange={(p) => patch(i, p)}
                onRemove={() => setDraft((prev) => prev.filter((_, idx) => idx !== i))}
              />
            ))
          )}
        </Space>
      </Card>

      <MultiStatusView
        summary={summaryQuery.data}
        status={statusQuery.data}
        loading={statusQuery.isLoading || summaryQuery.isLoading}
        isError={statusQuery.isError || summaryQuery.isError}
        error={statusQuery.error ?? summaryQuery.error}
        onDisableStation={running ? onDisableStation : undefined}
        busy={busy}
      />
    </div>
  )
}
