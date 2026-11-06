import { useEffect, useRef, useState } from 'react'

import { Popover, Spin, Typography } from 'antd'

import { api } from '../api/endpoints'
import type { FrameTranslation } from '../api/types'
import { useT } from '../i18n'

/** 翻译结果缓存（hex → 结果）；上限 500 条，满则丢弃最早插入项 */
const CACHE = new Map<string, FrameTranslation | { error: string }>()
const CACHE_MAX = 500

interface Result {
  data: FrameTranslation | null
  error: string | null
}

/**
 * 悬停翻译内容（第二批体验改造 ④）。
 *
 * 挂载即请求 `GET /api/frames/decode?hex=`（后端复用 core 协议解析器逐段翻译），
 * 结果按 hex 缓存——同帧重复悬停不再发请求。
 */
function TranslateContent({ hex }: { hex: string }) {
  const t = useT()
  const [result, setResult] = useState<Result | null>(() => {
    const cached = CACHE.get(hex)
    if (!cached) return null
    return 'error' in cached
      ? { data: null, error: cached.error }
      : { data: cached, error: null }
  })

  useEffect(() => {
    if (result) return
    let cancelled = false
    api
      .framesDecode(hex)
      .then((r) => {
        if (cancelled) return
        if (r.ok && r.translation) {
          if (CACHE.size >= CACHE_MAX) {
            const first = CACHE.keys().next().value
            if (first !== undefined) CACHE.delete(first)
          }
          CACHE.set(hex, r.translation)
          setResult({ data: r.translation, error: null })
        } else {
          setResult({ data: null, error: r.error ?? t('frameTranslate.failed') })
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setResult({ data: null, error: e.message })
      })
    return () => {
      cancelled = true
    }
    // result 就绪后不再重发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hex])

  if (!result) {
    return (
      <div style={{ minWidth: 240, textAlign: 'center', padding: 12 }}>
        <Spin size="small" />
      </div>
    )
  }
  if (result.error || !result.data) {
    return (
      <Typography.Text type="secondary">
        {t('frameTranslate.failedWith', {
          error: result.error ?? t('frameTranslate.unknown'),
        })}
      </Typography.Text>
    )
  }
  return (
    <div style={{ maxWidth: 560 }}>
      {result.data.segments.map((seg, i) => (
        <div key={i} style={{ marginBottom: i === result.data!.segments.length - 1 ? 0 : 8 }}>
          <Typography.Text strong style={{ display: 'block', fontSize: 12 }}>
            {seg.title}
          </Typography.Text>
          {seg.lines.map((line, j) => (
            <div key={j} className="mono" style={{ whiteSpace: 'pre-wrap' }}>
              {line}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

interface Props {
  hex: string
  children: React.ReactNode
}

/** 报文单元格悬停翻译入口：hover（300ms 延迟）拉起翻译 Popover。 */
export function FrameTranslatePopover({ hex, children }: Props) {
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        window.clearTimeout(timer.current)
        if (next) {
          // 延迟拉起：快速扫过报文流时不逐帧请求
          timer.current = window.setTimeout(() => setOpen(true), 300)
        } else {
          setOpen(false)
        }
      }}
      trigger={['hover']}
      placement="left"
      content={<TranslateContent hex={hex} />}
    >
      <span onMouseEnter={() => undefined} style={{ cursor: 'help' }}>{children}</span>
    </Popover>
  )
}
