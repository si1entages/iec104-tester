import { useRef } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode, ThHTMLAttributes } from 'react'

import { useT } from '../i18n'

interface Props extends ThHTMLAttributes<HTMLTableCellElement> {
  width: number
  minWidth?: number
  onResize: (width: number) => void
  children?: ReactNode
}

/**
 * 可拖拽列宽的表头单元格（第二批体验改造 ③，零新依赖）。
 *
 * 右缘 8px 热区（.col-resizer）监听 pointerdown → document 级 pointermove/up，
 * 实时回调新宽度。宽度状态由 useResizableColumns 持有（会话内记忆，不持久化）。
 */
export function ResizableHeaderCell({ width, minWidth = 56, onResize, children, ...rest }: Props) {
  const t = useT()
  const startX = useRef(0)
  const startW = useRef(0)

  const handlePointerDown = (e: ReactPointerEvent<HTMLSpanElement>): void => {
    e.preventDefault()
    e.stopPropagation()
    startX.current = e.clientX
    startW.current = width
    document.body.style.cursor = 'col-resize'
    const move = (ev: PointerEvent): void => {
      onResize(Math.max(minWidth, startW.current + ev.clientX - startX.current))
    }
    const up = (): void => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      document.body.style.cursor = ''
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <th {...rest}>
      {children}
      <span
        className="col-resizer"
        aria-label={t('common.resizeColumn')}
        onPointerDown={handlePointerDown}
        onClick={(e) => e.stopPropagation()}
      />
    </th>
  )
}
