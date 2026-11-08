import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Button, Card, CardBody, CardTitle, Flex, Label } from '@patternfly/react-core'
// 按需注册：只引入折线 + 必要组件，避免把整个 echarts 打进首屏 bundle
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use } from 'echarts/core'
import type { EChartsType } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

import type { Point } from '../../api/types'
import { useT } from '../../i18n'
import { formatClock } from '../../lib/format'
import { pointKey } from '../../lib/pointValue'
import { trendBuffer } from '../../lib/trendBuffer'
import { useUiStore } from '../../store/uiStore'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

interface Props {
  watched: Point[]
  onRemove: (key: string) => void
  onClear: () => void
}

/** 趋势图（PF 版）：ECharts 与 UI 库无关，容器与工具条换成 PatternFly。 */
export function PfTrendChart({ watched, onRemove, onClear }: Props) {
  const t = useT()
  const observerRef = useRef<ResizeObserver | null>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const [version, setVersion] = useState(0)
  const theme = useUiStore((s) => s.theme)

  // 配色全部取自 PF token（canvas 不认 CSS 变量，先解析成具体颜色）
  const colors = useMemo(
    () => ({
      text: cssVar('--pf-t--global--text--color--regular'),
      textSecondary: cssVar('--pf-t--global--text--color--subtle'),
      axisLine: cssVar('--pf-t--global--border--color--default'),
      splitLine: cssVar('--pf-t--global--border--color--default'),
    }),
    // theme 变化会切换 html 上的 pf 类，需要重新解析变量
    [theme],
  )

  useEffect(() => trendBuffer.subscribe(() => setVersion((v) => v + 1)), [])

  const applyRef = useRef<() => void>(() => undefined)
  applyRef.current = () => {
    const chart = chartRef.current
    if (!chart) return
    const option = {
      backgroundColor: 'transparent',
      grid: { left: 48, right: 16, top: 32, bottom: 28 },
      tooltip: { trigger: 'axis' as const, confine: true },
      legend: { textStyle: { color: colors.text }, top: 0 },
      xAxis: {
        type: 'time' as const,
        axisLabel: {
          color: colors.textSecondary,
          formatter: (value: number) => formatClock(value / 1000),
        },
        axisLine: { lineStyle: { color: colors.axisLine } },
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { color: colors.textSecondary },
        splitLine: { lineStyle: { color: colors.splitLine } },
      },
      series: watched.map((point) => {
        const samples = trendBuffer.get(pointKey(point))
        return {
          name: `${point.type}-${point.ioa} ${point.name}`,
          type: 'line' as const,
          showSymbol: samples.length <= 2,
          symbolSize: 6,
          smooth: true,
          sampling: 'lttb' as const,
          data: samples.map((s) => [s.ts * 1000, s.value]),
        }
      }),
    }
    chart.setOption(option, { replaceMerge: ['series'] })
  }

  // 容器是条件渲染（无 watch 时显示占位提示）：挂载时容器可能还不存在，
  // 不能用一次性 effect 读 ref（会永久 bail，之后加入趋势也不 init）。
  // 用回调 ref——容器每次出现都重新挂观察器并重试；隐藏面板尺寸为 0 时先跳过，
  // 等 ResizeObserver 报告可见再创建（避免 0×0 画布）。
  const attachContainer = useCallback((el: HTMLDivElement | null) => {
    observerRef.current?.disconnect()
    observerRef.current = null
    chartRef.current?.dispose()
    chartRef.current = null
    if (!el) return
    const ensure = (): void => {
      if (chartRef.current || el.clientWidth === 0) return
      const chart = init(el, undefined, { renderer: 'canvas' })
      chartRef.current = chart
      applyRef.current()
    }
    const observer = new ResizeObserver(() => {
      ensure()
      chartRef.current?.resize()
    })
    observer.observe(el)
    observerRef.current = observer
    ensure()
  }, [])

  useEffect(() => {
    applyRef.current()
  }, [version, watched, colors, theme])

  return (
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          <span>{t('trend.title')}</span>
          {watched.length === 0 ? (
            <span style={{ opacity: 0.7, fontSize: 12 }}>{t('trend.emptyHint')}</span>
          ) : (
            watched.map((point) => {
              const key = pointKey(point)
              return (
                <Label key={key} color="blue" isCompact onClose={() => onRemove(key)}>
                  {point.type}-{point.ioa}
                </Label>
              )
            })
          )}
          {watched.length > 0 ? (
            <Button variant="link" size="sm" onClick={onClear}>
              {t('trend.clear')}
            </Button>
          ) : null}
        </Flex>
      </CardTitle>
      <CardBody>
        {watched.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', opacity: 0.7 }}>{t('trend.sampling')}</div>
        ) : (
          <>
            <div ref={attachContainer} style={{ width: '100%', height: 320 }} />
            <div style={{ opacity: 0.65, fontSize: 12, marginTop: 4 }}>{t('trend.footer')}</div>
          </>
        )}
      </CardBody>
    </Card>
  )
}
