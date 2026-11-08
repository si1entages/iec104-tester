import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Button, DismissibleTag, Select, SelectItem, TextInput } from '@carbon/react'
import { useQueries } from '@tanstack/react-query'
// 按需注册：只引入折线 + 必要组件（与实时趋势图同策略）
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use } from 'echarts/core'
import type { EChartsType } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

import { api } from '../../api/endpoints'
import type { HistoryDataRecord } from '../../api/types'
import { toNumericValue } from '../../lib/trendBuffer'
import { useUiStore } from '../../store/uiStore'
import { useT } from '../../i18n'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const MAX_SERIES = 8
const SERIES_LIMIT = 5000

interface CurveSeries {
  point_type: 'yx' | 'yc' | 'ym'
  ioa: number
}

interface Props {
  /** 起止时间（epoch 秒；undefined = 不限），随历史页「查询」按钮生效 */
  start?: number
  end?: number
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/**
 * 历史曲线（T77）：从 data_history 点位时间序列画回放曲线.
 *
 * 序列由用户添加（1~8 个，类型 + IOA），时间范围随历史页查询生效；
 * 每条序列一次 `GET /api/history/data`（useQueries 并行）。
 * 图表与实时趋势图同一套 0×0 防护：回调 ref + ResizeObserver，容器有尺寸才 init。
 */
export function CarbonHistoryCurve({ start, end }: Props) {
  const t = useT()
  const theme = useUiStore((s) => s.theme)
  const setChartSnapshots = useUiStore((s) => s.setChartSnapshots)
  const chartSnapshots = useUiStore((s) => s.chartSnapshots)
  const observerRef = useRef<ResizeObserver | null>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const [series, setSeries] = useState<CurveSeries[]>([])
  const [type, setType] = useState<'yx' | 'yc' | 'ym'>('yc')
  const [ioa, setIoa] = useState('')

  const queries = useQueries({
    queries: series.map((s) => ({
      queryKey: ['historyCurve', s.point_type, s.ioa, start ?? null, end ?? null],
      queryFn: () => api.history.data({ point_type: s.point_type, ioa: s.ioa, start, end, limit: SERIES_LIMIT }),
    })),
  })

  const colors = useMemo(
    () => ({
      text: cssVar('--cds-text-primary'),
      textSecondary: cssVar('--cds-text-secondary'),
      axisLine: cssVar('--cds-border-strong'),
      splitLine: cssVar('--cds-border-subtle'),
    }),
    [theme],
  )

  const applyRef = useRef<() => void>(() => undefined)
  applyRef.current = () => {
    const chart = chartRef.current
    if (!chart) return
    chart.setOption(
      {
        backgroundColor: 'transparent',
        grid: { left: 56, right: 16, top: 32, bottom: 28 },
        tooltip: { trigger: 'axis' as const, confine: true },
        legend: { textStyle: { color: colors.text }, top: 0 },
        xAxis: {
          type: 'time' as const,
          axisLabel: { color: colors.textSecondary },
          axisLine: { lineStyle: { color: colors.axisLine } },
        },
        yAxis: { type: 'value' as const, axisLabel: { color: colors.textSecondary },
                 splitLine: { lineStyle: { color: colors.splitLine } } },
        series: series.map((s, i) => {
          const rows: HistoryDataRecord[] = queries[i]?.data?.rows ?? []
          const isStep = s.point_type !== 'yc'
          return {
            name: `${s.point_type.toUpperCase()}-${s.ioa}`,
            type: 'line' as const,
            showSymbol: rows.length <= 2,
            step: isStep ? ('end' as const) : undefined,
            data: rows
              .map((r) => [r.ts * 1000, toNumericValue(r.value)])
              .filter((p): p is [number, number] => p[1] !== null),
          }
        }),
      },
      { replaceMerge: ['series'] },
    )
  }

  // 容器是条件渲染（无序列时提示）：回调 ref——每次出现重挂观察器并重试 init
  const attachContainer = useCallback(
    (el: HTMLDivElement | null) => {
      observerRef.current?.disconnect()
      observerRef.current = null
      chartRef.current?.dispose()
      chartRef.current = null
      if (!el) return
      const ensure = (): void => {
        if (chartRef.current || el.clientWidth === 0) return
        chartRef.current = init(el, undefined, { renderer: 'canvas' })
        applyRef.current()
      }
      const observer = new ResizeObserver(() => {
        ensure()
        chartRef.current?.resize()
      })
      observer.observe(el)
      observerRef.current = observer
      ensure()
    },
    // theme 变化切 g10/g100 类，token 颜色需重解析
    [theme],
  )

  useEffect(() => {
    applyRef.current()
    // 曲线渲染后采集快照（T87）：供报告导出嵌入（最多 4 张，
    // 仅采集有数据的序列，避免空图占位）
    const chart = chartRef.current
    if (chart && queries.some((q) => (q.data?.rows?.length ?? 0) > 0)) {
      try {
        // 打印报告需要不透明底色；从主题 token 解析实际色值（canvas 不认 CSS 变量）
        const bg = cssVar('--cds-background') || cssVar('--pf-t--global--background--color--primary--default')
        const url = chart.getDataURL({ type: 'png', pixelRatio: 1.5,
          backgroundColor: bg }) as string
        setChartSnapshots([url, ...chartSnapshots.filter((x) => x !== url)].slice(0, 4))
      } catch { /* ECharts 未就绪时跳过 */ }
    }
  })

  const addSeries = (): void => {
    const n = Number(ioa)
    if (!Number.isInteger(n) || n <= 0) return
    const key = `${type}-${n}`
    if (series.some((s) => `${s.point_type}-${s.ioa}` === key)) return
    setSeries((prev) => [...prev, { point_type: type, ioa: n }].slice(-MAX_SERIES))
    setIoa('')
  }

  const loading = queries.some((q) => q.isFetching)
  const anyRows = queries.some((q) => (q.data?.rows?.length ?? 0) > 0)

  return (
    <div>
      <div className="app-row" style={{ alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ width: 130, minWidth: 130 }}>
          <Select
            id="cb-hc-type"
            labelText={t('histcurve.type')}
            hideLabel
            value={type}
            onChange={(event) => setType((event.target as HTMLSelectElement).value as 'yx' | 'yc' | 'ym')}
          >
            <SelectItem value="yx" text={t('history.type.yx')} />
            <SelectItem value="yc" text={t('history.type.yc')} />
            <SelectItem value="ym" text={t('history.type.ym')} />
          </Select>
        </div>
        <div style={{ width: 130, minWidth: 130 }}>
          <TextInput
            id="cb-hc-ioa"
            type="number"
            labelText={t('histcurve.ioa')}
            hideLabel
            min={1}
            placeholder={t('histcurve.ioa')}
            value={ioa}
            onChange={(event) => setIoa(event.target.value)}
          />
        </div>
        <Button kind="secondary" size="sm" onClick={addSeries} disabled={series.length >= MAX_SERIES}>
          {t('histcurve.add')}
        </Button>
        {series.map((s) => (
          <DismissibleTag
            key={`${s.point_type}-${s.ioa}`}
            size="sm"
            type="blue"
            text={`${s.point_type.toUpperCase()}-${s.ioa}`}
            dismissTooltipLabel={t('histcurve.remove')}
            onClose={() => setSeries((prev) => prev.filter((x) => !(x.point_type === s.point_type && x.ioa === s.ioa)))}
          />
        ))}
        {loading ? <span style={{ fontSize: 12, opacity: 0.7 }}>{t('common.loading')}</span> : null}
      </div>
      <div style={{ marginTop: 8 }}>
        {series.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', opacity: 0.7 }}>{t('histcurve.empty')}</div>
        ) : !anyRows && !loading ? (
          <div style={{ padding: 32, textAlign: 'center', opacity: 0.7 }}>{t('histcurve.noData')}</div>
        ) : (
          <div ref={attachContainer} style={{ width: '100%', height: 360 }} />
        )}
      </div>
    </div>
  )
}
