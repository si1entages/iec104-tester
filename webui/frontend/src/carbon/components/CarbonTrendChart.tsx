import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Button, DismissibleTag } from '@carbon/react'
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
import { Panel } from './ui'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

interface Props {
  watched: Point[]
  onRemove: (key: string) => void
  onClear: () => void
}

/** 趋势图（Carbon 版）：ECharts 与 UI 库无关，配色取自 --cds-* token。 */
export function CarbonTrendChart({ watched, onRemove, onClear }: Props) {
  const t = useT()
  const observerRef = useRef<ResizeObserver | null>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const [version, setVersion] = useState(0)
  const theme = useUiStore((s) => s.theme)

  // 配色全部取自 Carbon token（canvas 不认 CSS 变量，先解析成具体颜色）
  const colors = useMemo(
    () => ({
      text: cssVar('--cds-text-primary'),
      textSecondary: cssVar('--cds-text-secondary'),
      axisLine: cssVar('--cds-border-strong'),
      splitLine: cssVar('--cds-border-subtle'),
    }),
    // theme 变化会切换 html 上的 g10/g100 类，需要重新解析变量
    [theme],
  )

  useEffect(() => trendBuffer.subscribe(() => setVersion((v) => v + 1)), [])

  // 最新一次 setOption：图例可能在容器可见之前才创建（Carbon Tabs 的隐藏面板
  // 保持了 DOM 但尺寸为 0，此时 init 会得到 0×0 canvas 且画不出图），
  // 因此把「应用数据」抽成 ref：只有容器有实际尺寸才 init，创建后立即补一次。
  const applyRef = useRef<() => void>(() => undefined)
  applyRef.current = () => {
    const chart = chartRef.current
    if (!chart) return
    const option = {
      backgroundColor: 'transparent',
      // 关动画（真机联调反馈）：高频点值流下 2Hz 重绘若带默认动画，整条曲线
      // 每次更新都滑动一遍，观感是「跑马灯」。工业趋势图按 ISA-101 应瞬时重绘。
      animation: false,
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
  // 用回调 ref——容器每次出现都重新挂观察器并重试；隐藏面板（如 Carbon Tabs
  // 的隐藏 TabPanel）尺寸为 0 时先跳过，等 ResizeObserver 报告可见再创建，
  // 避免 0×0 画布。
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
    <Panel
      title={
        <span className="app-row">
          {t('trend.title')}
          {watched.length === 0 ? (
            <span style={{ color: 'var(--cds-text-secondary)', fontSize: 12 }}>{t('trend.emptyHint')}</span>
          ) : (
            watched.map((point) => {
              const key = pointKey(point)
              return (
                <DismissibleTag
                  key={key}
                  size="sm"
                  type="blue"
                  text={`${point.type}-${point.ioa}`}
                  dismissTooltipLabel={t('trend.remove')}
                  onClose={() => onRemove(key)}
                />
              )
            })
          )}
          {watched.length > 0 ? (
            <Button kind="ghost" size="sm" onClick={onClear}>
              {t('trend.clear')}
            </Button>
          ) : null}
        </span>
      }
    >
      {watched.length === 0 ? (
        <div style={{ padding: 32, textAlign: 'center', color: 'var(--cds-text-secondary)' }}>{t('trend.sampling')}</div>
      ) : (
        <>
          <div ref={attachContainer} style={{ width: '100%', height: 320 }} />
          {/* 单采样态自解释（真机联调反馈「看不到曲线」的最常见原因：连接未建立/点值
              未变化时只有加入瞬间的一个数据点标记，肉眼几乎不可见——明确告知在等数据） */}
          {watched.every((p) => trendBuffer.get(pointKey(p)).length < 2) ? (
            <div style={{ color: 'var(--cds-text-secondary)', fontSize: 12, marginTop: 4 }}>
              {t('trend.waiting')}
            </div>
          ) : null}
          <div style={{ color: 'var(--cds-text-secondary)', fontSize: 12, marginTop: 4 }}>{t('trend.footer')}</div>
        </>
      )}
    </Panel>
  )
}
