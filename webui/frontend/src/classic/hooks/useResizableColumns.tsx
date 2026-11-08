import { useCallback, useMemo, useState } from 'react'
import type React from 'react'
import type { ReactNode } from 'react'
import type { TableColumnsType } from 'antd'

import { ResizableHeaderCell } from '../components/ResizableHeaderCell'

/** 列标识：优先 key，其次 dataIndex（数组用 . 连接）。 */
function keyOf<T>(col: TableColumnsType<T>[number]): string {
  if (col.key !== undefined) return String(col.key)
  const di = (col as { dataIndex?: unknown }).dataIndex
  if (typeof di === 'string' || typeof di === 'number') return String(di)
  if (Array.isArray(di)) return di.join('.')
  return ''
}

interface ResizableColumns<T> {
  /** 注入当前宽度与 onHeaderCell 的列定义 */
  columns: TableColumnsType<T>
  /** 传给 Table 的 components.header */
  headerComponents: { header: { cell: (props: Record<string, unknown>) => ReactNode } }
  /** 当前全部列宽之和（用于 scroll.x） */
  totalWidth: number
}

/**
 * 列宽拖拽（第二批体验改造 ③）：
 * - 初始宽度取列定义的 `width`（antd virtual 表需要确定列宽，故默认值即初始基线，
 *   长文本列给宽默认值实现"自适应"；用户拖拽后以拖拽结果为准）
 * - 拖拽结果仅**会话内记忆**（组件状态），不持久化
 */
export function useResizableColumns<T extends object>(
  base: TableColumnsType<T>,
  fallbackWidth = 150,
): ResizableColumns<T> {
  const [widths, setWidths] = useState<Record<string, number>>(() => {
    const out: Record<string, number> = {}
    for (const col of base) {
      const k = keyOf(col)
      if (k) out[k] = Number(col.width ?? fallbackWidth)
    }
    return out
  })

  const onResize = useCallback((key: string, w: number) => {
    setWidths((prev) => (prev[key] === w ? prev : { ...prev, [key]: w }))
  }, [])

  const columns = useMemo(
    () =>
      base.map((col) => {
        const k = keyOf(col)
        if (!k || widths[k] === undefined) return col
        return {
          ...col,
          width: widths[k],
          onHeaderCell: () =>
            ({ 'data-resize-key': k }) as unknown as React.ThHTMLAttributes<HTMLTableCellElement>,
        }
      }),
    [base, widths],
  )

  const headerComponents = useMemo(
    () => ({
      header: {
        cell: (props: Record<string, unknown>) => {
          const key = props['data-resize-key'] as string | undefined
          if (!key || widths[key] === undefined) return <th {...(props as object)} />
          return (
            <ResizableHeaderCell
              {...(props as object)}
              width={widths[key]}
              onResize={(w) => onResize(key, w)}
            />
          )
        },
      },
    }),
    [widths, onResize],
  )

  const totalWidth = useMemo(
    () => Object.values(widths).reduce((sum, w) => sum + w, 0),
    [widths],
  )

  return { columns, headerComponents, totalWidth }
}
