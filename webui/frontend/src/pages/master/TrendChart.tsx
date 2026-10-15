import { useEffect, useRef, useState } from 'react'

import { ClearOutlined, CloseOutlined } from '@ant-design/icons'
import { Button, Card, Empty, Space, Tag, Typography } from 'antd'
// 按需注册：只引入折线 + 必要组件，避免把整个 echarts 打进首屏 bundle
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use } from 'echarts/core'
import type { EChartsType } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

import type { Point } from '../../api/types'
import { formatClock } from '../../lib/format'
import { pointKey } from '../../lib/pointValue'
import { trendBuffer } from '../../lib/trendBuffer'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

interface Props {
  /** 被订阅的点位（只有这些点位会被采样，避免十万点全量入内存） */
  watched: Point[]
  onRemove: (key: string) => void
  onClear: () => void
}

const EMPTY_OPTION = {
  backgroundColor: 'transparent',
  grid: { left: 48, right: 16, top: 28, bottom: 28 },
  tooltip: { trigger: 'axis' as const, confine: true },
  legend: { textStyle: { color: '#d9d9d9' }, top: 0 },
  xAxis: {
    type: 'category' as const,
    axisLabel: { color: '#8c8c8c' },
    axisLine: { lineStyle: { color: '#3a3a3a' } },
  },
  yAxis: {
    type: 'value' as const,
    axisLabel: { color: '#8c8c8c' },
    splitLine: { lineStyle: { color: '#262626' } },
  },
  series: [] as unknown[],
}

/** 趋势图（T12）：从点表挑选点位看实时曲线（ECharts，按需引入）。 */
export function TrendChart({ watched, onRemove, onClear }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const [version, setVersion] = useState(0)

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
    chart.setOption({ ...EMPTY_OPTION, series }, { replaceMerge: ['series'] })
  }, [version, watched])

  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <span>趋势图</span>
          {watched.length === 0 ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              在点表中选中一行后点「加入趋势」
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
              清空曲线
            </Button>
          ) : null}
        </Space>
      }
    >
      {watched.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span style={{ color: '#8c8c8c' }}>
              选择点位后开始采样（仅采样被选点位，十万点表也不会吃满内存）
            </span>
          }
        />
      ) : (
        <div ref={containerRef} style={{ width: '100%', height: 320 }} />
      )}
      {watched.length > 0 ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          <CloseOutlined /> 最多保留最近 600 个采样点；采样由 WS 点值更新驱动。
        </Typography.Text>
      ) : null}
    </Card>
  )
}
