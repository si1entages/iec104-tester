import { useEffect, useMemo, useState } from 'react'

import { ClearOutlined, PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Card, Input, InputNumber, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import type { TableColumnsType } from 'antd'

import { api } from '../api/endpoints'
import { clearFrames, replaceFrames, useLiveFrames } from '../api/queries'
import type { Frame } from '../api/types'
import { formatClock, groupHex } from '../lib/format'
import {
  DIRECTION_COLOR,
  DIRECTION_LABEL,
  FORMAT_COLOR,
  parseFrame,
} from '../lib/frame'
import type { ParsedFrame } from '../lib/frame'
import { normalizeFrames } from '../lib/records'
import { useResizableColumns } from '../hooks/useResizableColumns'

interface Row {
  key: string
  frame: Frame
  parsed: ParsedFrame | null
}

const COLUMNS: TableColumnsType<Row> = [
  {
    key: 'time',
    title: '时间',
    width: 130,
    render: (_v, row) => <span className="mono">{formatClock(row.frame.ts ?? 0)}</span>,
  },
  {
    key: 'direction',
    title: '方向',
    width: 80,
    render: (_v, row) => (
      <Tag color={DIRECTION_COLOR[row.frame.direction] ?? 'default'}>
        {DIRECTION_LABEL[row.frame.direction] ?? row.frame.direction}
      </Tag>
    ),
  },
  { key: 'len', title: '长度', width: 70, render: (_v, row) => row.frame.len },
  {
    key: 'format',
    title: '格式',
    width: 70,
    render: (_v, row) =>
      row.parsed ? <Tag color={FORMAT_COLOR[row.parsed.format]}>{row.parsed.format}</Tag> : '-',
  },
  {
    key: 'type',
    title: '类型 / U 功能',
    width: 240,
    ellipsis: true,
    render: (_v, row) =>
      row.parsed?.uFunc ?? row.parsed?.typeName ?? '-',
  },
  {
    key: 'cot',
    title: 'COT',
    width: 130,
    ellipsis: true,
    render: (_v, row) => row.parsed?.cotName ?? '-',
  },
  {
    key: 'seq',
    title: '序号',
    width: 110,
    className: 'mono',
    render: (_v, row) => {
      const p = row.parsed
      if (!p) return '-'
      if (p.format === 'I') return `S=${p.ns} R=${p.nr}`
      if (p.format === 'S') return `R=${p.nr}`
      return '-'
    },
  },
  {
    key: 'firstIoa',
    title: '首 IOA',
    width: 90,
    className: 'mono',
    render: (_v, row) => row.parsed?.firstIoa ?? '-',
  },
  {
    key: 'count',
    title: '个数',
    width: 70,
    render: (_v, row) => row.parsed?.count ?? '-',
  },
  {
    key: 'hex',
    title: '报文 (HEX)',
    width: 420,
    // 行高自适应直接显示全部报文（第二批改造④）：hex 串按字节分组换行，不再截断
    render: (_v, row) => (
      <Tooltip title={<span className="mono">{groupHex(row.frame.hex)}</span>}>
        <span className="mono hex-wrap">{groupHex(row.frame.hex)}</span>
      </Tooltip>
    ),
  },
]

/**
 * 报文查看器（T12）：HEX + 协议解析 + 收发配色 + 过滤 + 暂停/清空。
 * 报文缓冲存在 React Query 缓存里，切页/重挂载不丢。
 *
 * **共享组件**：主站工作台与子站工作台复用同一个实例（不是复制粘贴），
 * 两侧都只是换页签内容，报文来源同为全局 WS 桥的 `frames/live` 缓冲。
 */
export function FrameViewer() {
  const queryClient = useQueryClient()
  const frames = useLiveFrames()
  // 列宽拖拽（第二批改造③）：会话内记忆
  const { columns, headerComponents, totalWidth } = useResizableColumns(COLUMNS)
  const [paused, setPaused] = useState(false)
  const [frozen, setFrozen] = useState<Frame[]>([])
  const [direction, setDirection] = useState<string | undefined>(undefined)
  const [format, setFormat] = useState<string | undefined>(undefined)
  const [minLen, setMinLen] = useState<number | undefined>(undefined)
  const [keyword, setKeyword] = useState('')

  // 首屏用 /api/recent 预热（WS 只推增量，不重放历史）
  useEffect(() => {
    if (frames.length > 0) return
    let cancelled = false
    void api
      .recent()
      .then((r) => {
        if (!cancelled) replaceFrames(queryClient, normalizeFrames(r.frames))
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
    // 只在挂载时预热一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const source = paused ? frozen : frames

  const rows = useMemo<Row[]>(() => {
    const kw = keyword.trim().toLowerCase()
    const out: Row[] = []
    for (let i = 0; i < source.length; i += 1) {
      const frame = source[i]
      const parsed = parseFrame(frame.hex)
      if (direction && frame.direction !== direction) continue
      if (format && parsed?.format !== format) continue
      if (minLen !== undefined && frame.len < minLen) continue
      if (kw) {
        const hay = `${frame.hex} ${parsed?.typeName ?? ''} ${parsed?.cotName ?? ''}`.toLowerCase()
        if (!hay.includes(kw)) continue
      }
      out.push({ key: `${frame.ts ?? 0}-${i}`, frame, parsed })
    }
    // 最新在上
    out.reverse()
    return out
  }, [source, direction, format, minLen, keyword])

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>报文查看器</span>
          <Tag color="blue">{rows.length}</Tag>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            / 缓冲 {frames.length}
          </Typography.Text>
          {paused ? <Tag color="orange">已暂停（冻结视图）</Tag> : null}
        </Space>
      }
      extra={
        <Space wrap>
          <Select
            size="small"
            style={{ width: 100 }}
            allowClear
            placeholder="方向"
            value={direction}
            onChange={setDirection}
            options={[
              { value: 'tx', label: '发送' },
              { value: 'rx', label: '接收' },
            ]}
          />
          <Select
            size="small"
            style={{ width: 100 }}
            allowClear
            placeholder="格式"
            value={format}
            onChange={setFormat}
            options={[
              { value: 'I', label: 'I 帧' },
              { value: 'S', label: 'S 帧' },
              { value: 'U', label: 'U 帧' },
            ]}
          />
          <InputNumber
            size="small"
            min={0}
            placeholder="最小长度"
            style={{ width: 120 }}
            value={minLen}
            onChange={(v) => setMinLen(v === null ? undefined : Number(v))}
          />
          <Input.Search
            size="small"
            style={{ width: 190 }}
            allowClear
            placeholder="HEX / 类型 / COT"
            onChange={(e) => setKeyword(e.target.value)}
          />
          <Button
            size="small"
            icon={paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
            onClick={() => {
              if (paused) {
                setPaused(false)
              } else {
                setFrozen(frames)
                setPaused(true)
              }
            }}
          >
            {paused ? '继续' : '暂停'}
          </Button>
          <Button
            size="small"
            icon={<ClearOutlined />}
            onClick={() => {
              clearFrames(queryClient)
              setFrozen([])
            }}
          >
            清空
          </Button>
        </Space>
      }
    >
      <Table<Row>
        virtual
        rowKey="key"
        size="small"
        columns={columns}
        components={headerComponents}
        dataSource={rows}
        pagination={false}
        scroll={{ y: 380, x: totalWidth }}
      />
    </Card>
  )
}
