import { useMemo, useRef, useState } from 'react'

import { Button, Label, SearchInput, Toolbar, ToolbarContent, ToolbarItem } from '@patternfly/react-core'
import { useVirtualizer } from '@tanstack/react-virtual'

import { usePointsQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { useT } from '../../i18n'
import { formatMeasurement } from '../../lib/format'
import { directCommandHint } from '../../lib/pointCommand'
import { pointKey } from '../../lib/pointValue'
import { PfQualityTags } from './PfQualityTags'

/** PF 默认密度：compact 表格行高约 38px（实测），虚拟化按此估算。 */
const ROW_HEIGHT = 38
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

/**
 * PatternFly 点表：TanStack Virtual 承载 10 万行。
 *
 * PF 没有内建虚拟滚动（官方扩展依赖已停维护的 react-virtualized），
 * 这里用固定列宽 + 绝对定位行实现：表头 sticky，行高 38px（PF compact 实测值）。
 */
export function PfPointsTable({
  selected,
  onSelect,
  height = DEFAULT_HEIGHT,
  showToolbar = true,
  onValueDoubleClick,
  selectHint,
}: Props) {
  const t = useT()
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
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
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

  return (
    <div>
      <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 4 }} data-testid="points-hint">
        {hint}
      </div>
      {showToolbar ? (
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem>
              <SearchInput
                placeholder={t('pt2.filterPlaceholder')}
                value={keyword}
                onChange={(_e, v) => setKeyword(v)}
                onClear={() => setKeyword('')}
              />
            </ToolbarItem>
            <ToolbarItem>
              <span style={{ display: 'inline-flex', gap: 4 }}>
                {TYPE_TABS.map((tab) => (
                  <Button
                    key={tab}
                    size="sm"
                    variant={type === tab ? 'primary' : 'tertiary'}
                    onClick={() => setType(tab)}
                  >
                    {tab === 'all' ? t('pt2.tab.all') : tab}
                  </Button>
                ))}
              </span>
            </ToolbarItem>
            <ToolbarItem align={{ default: 'alignEnd' }}>
              <span style={{ opacity: 0.75, fontSize: 13 }}>{t('common.total', { n: rows.length })}</span>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      ) : null}

      {isError ? (
        <div style={{ padding: 12, color: 'var(--pf-t--global--text--color--status--danger--default)' }}>
          {t('common.loadFailed')}: {error instanceof Error ? error.message : String(error ?? '')}
        </div>
      ) : null}

      <div
        style={{
          border: '1px solid var(--pf-t--global--border--color--default)',
          borderRadius: 6,
          overflowX: 'auto',
          overflowY: 'hidden',
        }}
      >
        <div style={{ minWidth: 900 }}>
        {/* 表头固定在滚动容器外：滚动 10 万行时始终可见（不依赖 sticky 的层叠行为） */}
        <table
          className="pf-v6-c-table pf-m-compact"
          style={{
            width: '100%',
            tableLayout: 'fixed',
            margin: 0,
            background: 'var(--pf-t--global--background--color--primary--default)',
          }}
        >
          <thead className="pf-v6-c-table__thead">
            <tr className="pf-v6-c-table__tr">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className="pf-v6-c-table__th"
                  style={{ width: col.width, textAlign: col.align === 'right' ? 'right' : 'left' }}
                >
                  {headLabels[col.key]}
                </th>
              ))}
            </tr>
          </thead>
        </table>

        <div ref={scrollRef} data-testid="points-scroll" style={{ height, overflow: 'auto' }}>
          {isLoading ? (
            <div style={{ padding: 24, opacity: 0.7 }}>…</div>
          ) : rows.length === 0 ? (
            <div style={{ padding: 24, opacity: 0.7 }}>{t('pt2.empty')}</div>
          ) : (
            <div style={{ height: totalHeight, position: 'relative' }}>
              {items.map((vi) => {
              const p = rows[vi.index]
              const key = pointKey(p)
              const isSelected = selectedKey === key
              return (
                <table
                  key={key}
                  className={`pf-v6-c-table pf-m-compact${isSelected ? ' pf-m-selected' : ''}`}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    tableLayout: 'fixed',
                    margin: 0,
                    transform: `translateY(${vi.start}px)`,
                  }}
                >
                  <tbody className="pf-v6-c-table__tbody">
                    <tr
                      className={`pf-v6-c-table__tr${isSelected ? ' pf-m-selected' : ''}`}
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
                      <td className="pf-v6-c-table__td" style={{ width: COLUMNS[0].width }}>
                        {p.ioa}
                      </td>
                      <td className="pf-v6-c-table__td" style={{ width: COLUMNS[1].width }}>
                        {p.type}
                      </td>
                      <td
                        className="pf-v6-c-table__td"
                        style={{ width: COLUMNS[2].width, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={p.name}
                      >
                        {p.name}
                      </td>
                      <td className="pf-v6-c-table__td" style={{ width: COLUMNS[3].width }}>
                        {p.group ?? '-'}
                      </td>
                      <td className="pf-v6-c-table__td" style={{ width: COLUMNS[4].width }}>
                        <Label isCompact color={p.enabled ? 'green' : 'grey'}>
                          {p.enabled ? t('status.enabled') : t('status.disabled')}
                        </Label>
                      </td>
                      <td
                        className="pf-v6-c-table__td"
                        style={{
                          width: COLUMNS[5].width,
                          textAlign: 'right',
                          fontVariantNumeric: 'tabular-nums',
                          ...(onValueDoubleClick && directCommandHint(p)
                            ? { cursor: 'pointer' }
                            : {}),
                        }}
                        title={(onValueDoubleClick ? directCommandHint(p) : undefined) ?? undefined}
                        data-testid={`point-value-${key}`}
                        onDoubleClick={(event) => {
                          if (!onValueDoubleClick) return
                          event.stopPropagation()
                          onValueDoubleClick(p)
                        }}
                      >
                        {formatMeasurement(p.value, p.decimal_places)}
                        {p.unit ? <span style={{ marginInlineStart: 4, opacity: 0.65 }}>{p.unit}</span> : null}
                      </td>
                      <td className="pf-v6-c-table__td" style={{ width: COLUMNS[6].width }}>
                        <PfQualityTags quality={p.quality} />
                      </td>
                    </tr>
                  </tbody>
                </table>
              )
            })}
            </div>
          )}
        </div>
        </div>
      </div>
    </div>
  )
}
