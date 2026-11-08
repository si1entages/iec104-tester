import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FlexItem,
  FormSelect,
  FormSelectOption,
  TextInput,
} from '@patternfly/react-core'
import { useQueries } from '@tanstack/react-query'
// 按需注册：只引入折线 + 必要组件（与实时趋势图同策略）
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use } from 'echarts/core'
import type { EChartsType } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

import { api } from '../../api/endpoints'
import type { HistoryDataRecord } from '../../api/types'
import { useT } from '../../i18n'
import { toNumericValue } from '../../lib/trendBuffer'
import { useUiStore } from '../../store/uiStore'

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
 * 历史曲线（T77，PF）：与 CarbonHistoryCurve 同构——data_history 点位时间
 * 序列回放曲线，序列 1~8 个，图表 0×0 防护同实时趋势图。
 */
export function PfHistoryCurve({ start, end }: Props) {
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
      text: cssVar('--pf-t--global--text--color--regular'),
      textSecondary: cssVar('--pf-t--global--text--color--subtle'),
      axisLine: cssVar('--pf-t--global--border--color--default'),
      splitLine: cssVar('--pf-t--global--border--color--default'),
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
    [theme],
  )

  useEffect(() => {
    applyRef.current()
    // 曲线渲染后采集快照（T87）：供报告导出嵌入（最多 4 张）
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
    <Card>
      <CardTitle>{t('history.tab.curve')}</CardTitle>
      <CardBody>
        <Flex gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          <FlexItem>
            <FormSelect
              id="pf-hc-type"
              aria-label={t('histcurve.type')}
              value={type}
              onChange={(_e, v) => setType(v as 'yx' | 'yc' | 'ym')}
            >
              <FormSelectOption value="yx" label={t('history.type.yx')} />
              <FormSelectOption value="yc" label={t('history.type.yc')} />
              <FormSelectOption value="ym" label={t('history.type.ym')} />
            </FormSelect>
          </FlexItem>
          <FlexItem>
            <TextInput
              id="pf-hc-ioa"
              type="number"
              aria-label={t('histcurve.ioa')}
              min={1}
              placeholder={t('histcurve.ioa')}
              value={ioa}
              onChange={(_e, v) => setIoa(v)}
            />
          </FlexItem>
          <FlexItem>
            <Button variant="secondary" onClick={addSeries} isDisabled={series.length >= MAX_SERIES}>
              {t('histcurve.add')}
            </Button>
          </FlexItem>
          {series.map((s) => (
            <FlexItem key={`${s.point_type}-${s.ioa}`}>
              <Button variant="link" isInline
                      onClick={() => setSeries((prev) => prev.filter((x) => !(x.point_type === s.point_type && x.ioa === s.ioa)))}>
                {`${s.point_type.toUpperCase()}-${s.ioa}`} ✕
              </Button>
            </FlexItem>
          ))}
          {loading ? <FlexItem><span style={{ fontSize: 12, opacity: 0.7 }}>{t('common.loading')}</span></FlexItem> : null}
        </Flex>
        <div style={{ marginTop: 8 }}>
          {series.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', opacity: 0.7 }}>{t('histcurve.empty')}</div>
          ) : !anyRows && !loading ? (
            <div style={{ padding: 32, textAlign: 'center', opacity: 0.7 }}>{t('histcurve.noData')}</div>
          ) : (
            <div ref={attachContainer} style={{ width: '100%', height: 360 }} />
          )}
        </div>
      </CardBody>
    </Card>
  )
}
