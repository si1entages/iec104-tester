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
        report(false, '没有启用的站，无法启动')
        return false
      }
      try {
        const r = await start.mutateAsync({ stations: payload })
        if (!r.ok) {
          report(false, `启动失败：${r.error ?? '未知错误'}`)
          return false
        }
        report(true, `已启动 ${r.stations ?? payload.length} 个站`)
        return true
      } catch (e) {
        report(false, `启动失败：${(e as Error).message}`)
        return false
      }
    },
    [start, report],
  )

  const runStop = useCallback(async (): Promise<boolean> => {
    try {
      const r = await stop.mutateAsync()
      if (!r.ok) {
        report(false, `停止失败：${r.error ?? '未知错误'}`)
        return false
      }
      report(true, '已停止全部站')
      return true
    } catch (e) {
      report(false, `停止失败：${(e as Error).message}`)
      return false
    }
  }, [stop, report])

  /** 以目标草稿「重建」管理器：先停全部，再按启用站启动 */
  const rebuild = useCallback(
    async (next: DraftStation[]): Promise<void> => {
      const stopped = await runStop()
      if (!stopped) return
      if (toStationConfigs(next).length === 0) {
        setDraft(next)
        setLast({ ok: true, text: '已停止全部站（当前没有启用的站）' })
        return
      }
      const ok = await runStart(next)
      if (ok) setDraft(next)
    },
    [runStop, runStart],
  )

  const onStartAll = (): void => {
    if (issues.length > 0) {
      report(false, `参数校验未通过：${issues[0]}${issues.length > 1 ? ` 等 ${issues.length} 项` : ''}`)
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
        message="多站管理器与当前会话角色无关"
        description="它挂在 Web 会话上，用途是「子站侧压力测试」：一次拉起多个子站去压被测主站。后端只支持整体启停，因此单站启停会被实现为「停止全部 → 以剩余站重新启动」。"
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
            <span>站配置（草稿）</span>
            <Tag color="blue">{draft.length}</Tag>
            <Tag color="green">启用 {enabledIds.size}</Tag>
            {running ? <Tag color="orange">运行中：字段已冻结，仅「参与本次启动」可切</Tag> : null}
            {pendingRebuild ? <Tag color="warning">有未生效的站变更</Tag> : null}
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
              添加站
            </Button>
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              loading={start.isPending}
              disabled={running || busy}
              onClick={onStartAll}
            >
              启动全部启用站
            </Button>
            <Button
              danger
              size="small"
              icon={<StopOutlined />}
              loading={stop.isPending}
              disabled={!running || busy}
              onClick={() => void runStop()}
            >
              停止全部
            </Button>
          </Space>
        }
      >
        {issues.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={`参数校验：${issues.length} 项待修正`}
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
            message="站集合与当前运行中的站不一致"
            description={
              <Space>
                <Typography.Text style={{ fontSize: 12 }}>
                  当前运行 {runningIds.size} 个站，草稿启用 {enabledIds.size} 个。
                </Typography.Text>
                <Button
                  size="small"
                  type="primary"
                  loading={busy}
                  onClick={() => void rebuild(draft)}
                >
                  重建管理器以应用
                </Button>
              </Space>
            }
          />
        ) : null}

        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {draft.length === 0 ? (
            <Typography.Text type="secondary">还没有站，点右上角「添加站」。</Typography.Text>
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
