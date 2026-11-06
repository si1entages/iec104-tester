import { useEffect, useMemo, useState } from 'react'

import { ClearOutlined, PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Card, Input, InputNumber, Select, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'

import { api } from '../api/endpoints'
import { clearFrames, replaceFrames, useLiveFrames } from '../api/queries'
import type { Frame } from '../api/types'
import { formatClock, groupHex } from '../lib/format'
import {
  DIRECTION_COLOR,
  FORMAT_COLOR,
  directionLabel,
  parseFrame,
} from '../lib/frame'
import type { ParsedFrame } from '../lib/frame'
import { normalizeFrames } from '../lib/records'
import { useResizableColumns } from '../hooks/useResizableColumns'
import { useT } from '../i18n'
import type { MessageKey } from '../i18n'
import { FrameTranslatePopover } from './FrameTranslatePopover'

interface Row {
  key: string
  frame: Frame
  parsed: ParsedFrame | null
}

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

function useColumns(t: TFn): TableColumnsType<Row> {
  return useMemo(
    () => [
      {
        key: 'time',
        title: t('frameViewer.col.time'),
        width: 130,
        render: (_v, row) => <span className="mono">{formatClock(row.frame.ts ?? 0)}</span>,
      },
      {
        key: 'direction',
        title: t('frameViewer.col.direction'),
        width: 80,
        render: (_v, row) => (
          <Tag color={DIRECTION_COLOR[row.frame.direction] ?? 'default'}>
            {directionLabel(row.frame.direction)}
          </Tag>
        ),
      },
      { key: 'len', title: t('frameViewer.col.len'), width: 70, render: (_v, row) => row.frame.len },
      {
        key: 'format',
        title: t('frameViewer.col.format'),
        width: 70,
        render: (_v, row) =>
          row.parsed ? <Tag color={FORMAT_COLOR[row.parsed.format]}>{row.parsed.format}</Tag> : '-',
      },
      {
        key: 'type',
        title: t('frameViewer.col.type'),
        width: 240,
        ellipsis: true,
        render: (_v, row) =>
          row.parsed?.uFunc ?? row.parsed?.typeName ?? '-',
      },
      {
        key: 'cot',
        title: t('frameViewer.col.cot'),
        width: 130,
        ellipsis: true,
        render: (_v, row) => row.parsed?.cotName ?? '-',
      },
      {
        key: 'hex',
        title: t('frameViewer.col.hex'),
        width: 420,
        // 第二批改造④：报文列移到序号列前面；行高自适应直接显示全部报文
        // （hex 串按字节分组换行，不再截断）；悬停 300ms 拉起逐段翻译
        render: (_v, row) => (
          <FrameTranslatePopover hex={row.frame.hex}>
            <span className="mono hex-wrap">{groupHex(row.frame.hex)}</span>
          </FrameTranslatePopover>
        ),
      },
      {
        key: 'seq',
        title: t('frameViewer.col.seq'),
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
        title: t('frameViewer.col.firstIoa'),
        width: 90,
        className: 'mono',
        render: (_v, row) => row.parsed?.firstIoa ?? '-',
      },
      {
        key: 'count',
        title: t('frameViewer.col.count'),
        width: 70,
        render: (_v, row) => row.parsed?.count ?? '-',
      },
    ],
    [t],
  )
}

/**
 * 报文查看器（T12）：HEX + 协议解析 + 收发配色 + 过滤 + 暂停/清空。
 * 报文缓冲存在 React Query 缓存里，切页/重挂载不丢。
 *
 * **共享组件**：主站工作台与子站工作台复用同一个实例（不是复制粘贴），
 * 两侧都只是换页签内容，报文来源同为全局 WS 桥的 `frames/live` 缓冲。
 */
export function FrameViewer() {
  const t = useT()
  const queryClient = useQueryClient()
  const frames = useLiveFrames()
  const baseColumns = useColumns(t)
  // 列宽拖拽（第二批改造③）：会话内记忆
  const { columns, headerComponents, totalWidth } = useResizableColumns(baseColumns)
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
          <span>{t('frameViewer.title')}</span>
          <Tag color="blue">{rows.length}</Tag>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('frameViewer.buffer', { n: frames.length })}
          </Typography.Text>
          {paused ? <Tag color="orange">{t('frameViewer.paused')}</Tag> : null}
        </Space>
      }
      extra={
        <Space wrap>
          <Select
            size="small"
            style={{ width: 100 }}
            allowClear
            placeholder={t('frameViewer.direction')}
            value={direction}
            onChange={setDirection}
            options={[
              { value: 'tx', label: t('frameViewer.send') },
              { value: 'rx', label: t('frameViewer.receive') },
            ]}
          />
          <Select
            size="small"
            style={{ width: 100 }}
            allowClear
            placeholder={t('frameViewer.format')}
            value={format}
            onChange={setFormat}
            options={[
              { value: 'I', label: t('frameViewer.iFrame') },
              { value: 'S', label: t('frameViewer.sFrame') },
              { value: 'U', label: t('frameViewer.uFrame') },
            ]}
          />
          <InputNumber
            size="small"
            min={0}
            placeholder={t('frameViewer.minLen')}
            style={{ width: 120 }}
            value={minLen}
            onChange={(v) => setMinLen(v === null ? undefined : Number(v))}
          />
          <Input.Search
            size="small"
            style={{ width: 190 }}
            allowClear
            placeholder={t('frameViewer.search')}
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
            {paused ? t('frameViewer.resume') : t('frameViewer.pause')}
          </Button>
          <Button
            size="small"
            icon={<ClearOutlined />}
            onClick={() => {
              clearFrames(queryClient)
              setFrozen([])
            }}
          >
            {t('frameViewer.clear')}
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
