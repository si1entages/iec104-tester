import { useMemo, useRef, useState } from 'react'

import { Button, Search, Tag } from '@carbon/react'
import { useVirtualizer, type VirtualItem } from '@tanstack/react-virtual'

import { usePointsQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { useT } from '../../i18n'
import { formatMeasurement } from '../../lib/format'
import { isStalePoint } from '../../lib/pointValue'
import { directCommandHint } from '../../lib/pointCommand'
import { pointKey } from '../../lib/pointValue'
import { CarbonQualityTags } from './CarbonQualityTags'

/**
 * Carbon 点表：TanStack Virtual 承载 10 万行。
 *
 * 与 PF 版同方案：固定列宽 + 逐行独立 `<table class="cds--data-table">` + 绝对定位；
 * 行高用 `measureElement` 实测（Carbon 默认密度 ≈48px，主题/字号变化也不漂移）。
 */
const DEFAULT_HEIGHT = 560

const COLUMNS: { key: string; label: string; width: string; align?: 'right' }[] = [
  { key: 'ioa', label: 'IOA', width: '9%' },
  { key: 'type', label: 'type', width: '8%' },
  { key: 'name', label: 'name', width: '32%' },
  { key: 'group', label: 'group', width: '7%' },
  { key: 'enabled', label: 'enabled', width: '10%' },
  { key: 'value', label: 'value', width: '17%', align: 'right' },
  { key: 'quality', label: 'quality', width: '17%' },
]

const TYPE_TABS = ['all', 'YX', 'YC', 'YK', 'YM', 'STEP'] as const

interface Props {
  selected?: Point | null
  onSelect?: (point: Point | null) => void
  height?: number
  showToolbar?: boolean
  /** 双击命令点的值单元格（主站传入；不传则纯浏览） */
  onValueDoubleClick?: (point: Point) => void
  selectHint?: string
}

export function CarbonPointsTable({
  selected,
  onSelect,
  height = DEFAULT_HEIGHT,
  showToolbar = true,
  onValueDoubleClick,
  selectHint,
}: Props) {
  const t = useT()
  const staleTip = t('alarms.staleTip')
  const { data: points = [], isLoading, isError, error } = usePointsQuery()
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [keyword, setKeyword] = useState('')
  const [type, setType] = useState<(typeof TYPE_TABS)[number]>('all')

  const rows = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return points.filter((p) => {
      if (type !== 'all' && p.type !== type) return false
      if (!kw) return true
      return String(p.ioa).includes(kw) || p.name.toLowerCase().includes(kw)
    })
  }, [points, keyword, type])

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 48,
    overscan: 8,
  })

  const items = virtualizer.getVirtualItems()
  const totalHeight = virtualizer.getTotalSize()
  const selectedKey = selected ? pointKey(selected) : null

  const headLabels: Record<string, string> = {
    ioa: t('status.col.ioa'),
    type: t('status.col.type'),
    name: t('status.col.name'),
    group: t('status.col.group'),
    enabled: t('status.col.enabled'),
    value: t('status.col.value'),
    quality: t('status.col.quality'),
  }

  const hint = selectHint ?? (onValueDoubleClick ? t('pt2.hint.command') : t('pt2.hint.select'))

  const renderRow = (vi: VirtualItem) => {
    const p = rows[vi.index]
    const key = pointKey(p)
    const isSelected = selectedKey === key
    const hintForValue = onValueDoubleClick ? directCommandHint(p) : undefined
    return (
      <table
        key={key}
        ref={virtualizer.measureElement}
        data-index={vi.index}
        className={`cds--data-table cds--data-table--md${isSelected ? ' cds--data-table--selected' : ''}`}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          margin: 0,
          transform: `translateY(${vi.start}px)`,
        }}
      >
        <tbody>
          <tr
            data-testid="point-row"
            data-key={key}
            tabIndex={0}
            aria-selected={isSelected}
            onClick={() => onSelect?.(p)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return
              event.preventDefault()
              onSelect?.(p)
            }}
            style={{ cursor: onSelect ? 'pointer' : 'default' }}
          >
            <td style={{ width: COLUMNS[0].width }}>{p.ioa}</td>
            <td style={{ width: COLUMNS[1].width }}>{p.type}</td>
            <td
              style={{
                width: COLUMNS[2].width,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={p.name}
            >
              {p.name}
            </td>
            <td style={{ width: COLUMNS[3].width }}>{p.group ?? '-'}</td>
            <td style={{ width: COLUMNS[4].width }}>
              {p.enabled ? (
                <Tag size="sm" type="green">
                  {t('status.enabled')}
                </Tag>
              ) : (
                <Tag size="sm" type="cool-gray">
                  {t('status.disabled')}
                </Tag>
              )}
            </td>
            <td
              className="mono"
              style={{
                width: COLUMNS[5].width,
                textAlign: 'right',
                fontVariantNumeric: 'tabular-nums',
                cursor: hintForValue ? 'pointer' : undefined,
                color: isStalePoint(p) ? 'var(--cds-text-secondary)' : undefined,
              }}
              title={isStalePoint(p) ? staleTip : hintForValue ?? undefined}
              data-testid={`point-value-${key}`}
              onDoubleClick={(event) => {
                if (!onValueDoubleClick) return
                event.stopPropagation()
                onValueDoubleClick(p)
              }}
            >
              {formatMeasurement(p.value, p.decimal_places)}
              {p.unit ? <span style={{ marginInlineStart: 4, color: 'var(--cds-text-secondary)' }}>{p.unit}</span> : null}
            </td>
            <td style={{ width: COLUMNS[6].width }}>
              <CarbonQualityTags quality={p.quality} />
            </td>
          </tr>
        </tbody>
      </table>
    )
  }

  return (
    <div>
      <div className="app-hint" data-testid="points-hint">
        {hint}
      </div>
      {showToolbar ? (
        <div className="app-row" style={{ marginBottom: 8 }}>
          <div style={{ width: 280, minWidth: 280 }}>
            <Search
              id="carbon-pt-search"
              labelText={t('pt2.filterPlaceholder')}
              placeholder={t('pt2.filterPlaceholder')}
              value={keyword}
              size="md"
              onChange={(event) => setKeyword(event.target.value)}
              onClear={() => setKeyword('')}
            />
          </div>
          <span style={{ display: 'inline-flex', gap: 4 }}>
            {TYPE_TABS.map((tab) => (
              <Button
                key={tab}
                kind={type === tab ? 'primary' : 'tertiary'}
                size="sm"
                onClick={() => setType(tab)}
              >
                {tab === 'all' ? t('pt2.tab.all') : tab}
              </Button>
            ))}
          </span>
          <span style={{ marginLeft: 'auto', color: 'var(--cds-text-secondary)', fontSize: 13 }}>
            {t('common.total', { n: rows.length })}
          </span>
        </div>
      ) : null}

      {isError ? (
        <div style={{ padding: 12, color: 'var(--cds-text-error)' }}>
          {t('common.loadFailed')}: {error instanceof Error ? error.message : String(error ?? '')}
        </div>
      ) : null}

      <div className="app-table-frame">
        <div style={{ minWidth: 900 }}>
          {/* 表头固定在滚动容器外：滚动 10 万行时始终可见 */}
          <table
            className="cds--data-table cds--data-table--md"
            style={{
              width: '100%',
              tableLayout: 'fixed',
              margin: 0,
              background: 'var(--cds-layer)',
            }}
          >
            <thead>
              <tr>
                {COLUMNS.map((col) => (
                  <th
                    key={col.key}
                    style={{ width: col.width, textAlign: col.align === 'right' ? 'right' : 'left' }}
                  >
                    <span className="cds--table-header-label">{headLabels[col.key]}</span>
                  </th>
                ))}
              </tr>
            </thead>
          </table>

          <div ref={scrollRef} data-testid="points-scroll" style={{ height, overflow: 'auto' }}>
            {isLoading ? (
              <div style={{ padding: 24, color: 'var(--cds-text-secondary)' }}>…</div>
            ) : rows.length === 0 ? (
              <div style={{ padding: 24, color: 'var(--cds-text-secondary)' }}>{t('pt2.empty')}</div>
            ) : (
              <div style={{ height: totalHeight, position: 'relative' }}>
                {items.map((vi) => renderRow(vi))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
