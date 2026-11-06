import { useEffect, useMemo, useRef, useState } from 'react'

import { ClearOutlined, CloseOutlined } from '@ant-design/icons'
import { Button, Card, Empty, Space, Tag, Typography, theme as antdTheme } from 'antd'
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

interface Props {
  /** 被订阅的点位（只有这些点位会被采样，避免十万点全量入内存） */
  watched: Point[]
  onRemove: (key: string) => void
  onClear: () => void
}

/** 趋势图（T12）：从点表挑选点位看实时曲线（ECharts，按需引入）。 */
export function TrendChart({ watched, onRemove, onClear }: Props) {
  const t = useT()
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const [version, setVersion] = useState(0)
  // 图表配色全部来自主题 token；theme 变化时 token 随之变化 → chartColors 重算 → option 重建
  const theme = useUiStore((s) => s.theme)
  const { token } = antdTheme.useToken()
  const chartColors = useMemo(
    () => ({
      text: token.colorText,
      textSecondary: token.colorTextSecondary,
      axisLine: token.colorBorderSecondary,
      splitLine: token.colorSplit,
    }),
    [token.colorText, token.colorTextSecondary, token.colorBorderSecondary, token.colorSplit],
  )

  // 采样注册（setWatched）由 MasterPage 持有：工作台挂载即采样，与本组件是否
  // 挂载无关；这里只负责订阅缓冲节流通知并重绘
  useEffect(() => trendBuffer.subscribe(() => setVersion((v) => v + 1)), [])

  useEffect(() => {
    if (!containerRef.current) return
    const chart = init(containerRef.current, undefined, { renderer: 'canvas' })
    chartRef.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(containerRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const emptyOption = {
      backgroundColor: 'transparent',
      grid: { left: 48, right: 16, top: 28, bottom: 28 },
      tooltip: { trigger: 'axis' as const, confine: true },
      legend: { textStyle: { color: chartColors.text }, top: 0 },
      xAxis: {
        type: 'category' as const,
        axisLabel: { color: chartColors.textSecondary },
        axisLine: { lineStyle: { color: chartColors.axisLine } },
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { color: chartColors.textSecondary },
        splitLine: { lineStyle: { color: chartColors.splitLine } },
      },
      series: [] as unknown[],
    }
    const series = watched.map((point) => {
      const key = pointKey(point)
      const samples = trendBuffer.get(key)
      return {
        name: `${point.type}-${point.ioa} ${point.name}`,
        type: 'line' as const,
        // 稀疏数据（总召唤后往往只有 1~2 个采样点）开符号可见，否则单点画不出线
        showSymbol: samples.length <= 2,
        symbolSize: 6,
        smooth: true,
        sampling: 'lttb' as const,
        data: samples.map((s) => [formatClock(s.ts), s.value]),
      }
    })
    chart.setOption({ ...emptyOption, series }, { replaceMerge: ['series'] })
    // theme 显式入 deps：切换主题时整体重设 option（配色随主题重建）
  }, [version, watched, chartColors, theme])

  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <span>{t('trend.title')}</span>
          {watched.length === 0 ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('trend.emptyHint')}
            </Typography.Text>
          ) : (
            watched.map((point) => {
              const key = pointKey(point)
              return (
                <Tag
                  key={key}
                  closable
                  color="cyan"
                  onClose={(e) => {
                    e.preventDefault()
                    onRemove(key)
                  }}
                >
                  {point.type}-{point.ioa}
                </Tag>
              )
            })
          )}
          {watched.length > 0 ? (
            <Button size="small" icon={<ClearOutlined />} onClick={onClear}>
              {t('trend.clear')}
            </Button>
          ) : null}
        </Space>
      }
    >
      {watched.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span style={{ color: token.colorTextTertiary }}>
              {t('trend.sampling')}
            </span>
          }
        />
      ) : (
        <div ref={containerRef} style={{ width: '100%', height: 320 }} />
      )}
      {watched.length > 0 ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          <CloseOutlined /> {t('trend.footer')}
        </Typography.Text>
      ) : null}
    </Card>
  )
}
