import { Fragment, useEffect, useMemo, useRef, useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FormSelect,
  FormSelectOption,
  Label,
  Popover,
  SearchInput,
  TextInput,
} from '@patternfly/react-core'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { clearFrames, replaceFrames, useLiveFrames } from '../../api/queries'
import type { Frame, FrameTranslation } from '../../api/types'
import { useT } from '../../i18n'
import { formatClock, groupHex } from '../../lib/format'
import { FrameExpandButton, FrameObjectsRow } from '../../carbon/components/FrameObjectTable'
import { parseFrame } from '../../lib/frame'
import type { ParsedFrame } from '../../lib/frame'
import { normalizeFrames } from '../../lib/records'

const CACHE = new Map<string, FrameTranslation | { error: string }>()
const CACHE_MAX = 500

function TranslateBody({ hex }: { hex: string }) {
  const t = useT()
  const [result, setResult] = useState<{ data: FrameTranslation | null; error: string | null } | null>(
    () => {
      const cached = CACHE.get(hex)
      if (!cached) return null
      return 'error' in cached ? { data: null, error: cached.error } : { data: cached, error: null }
    },
  )

  useEffect(() => {
    if (result) return
    let cancelled = false
    api
      .framesDecode(hex)
      .then((r) => {
        if (cancelled) return
        if (r.ok && r.segments) {
          const translation: FrameTranslation = { format: r.format ?? '?', segments: r.segments }
          if (CACHE.size >= CACHE_MAX) {
            const first = CACHE.keys().next().value
            if (first !== undefined) CACHE.delete(first)
          }
          CACHE.set(hex, translation)
          setResult({ data: translation, error: null })
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
    // 只按 hex 请求一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hex])

  if (!result) return <div style={{ padding: 8, opacity: 0.75 }}>…</div>
  if (result.error || !result.data) {
    return (
      <div style={{ opacity: 0.8 }}>
        {t('frameTranslate.failedWith', { error: result.error ?? t('frameTranslate.unknown') })}
      </div>
    )
  }
  return (
    <div style={{ maxWidth: 560 }}>
      {result.data.segments.map((seg, i) => (
        <div key={`${seg.title}-${i}`} style={{ marginBottom: 8 }}>
          <strong style={{ display: 'block', fontSize: 12 }}>{seg.title}</strong>
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

/** 悬停 300ms 拉起翻译（与旧版一致：快速扫过报文流时不逐帧请求）。 */
function TranslateHover({ hex, children }: { hex: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <Popover
      isVisible={open}
      position="left"
      hasAutoWidth
      bodyContent={open ? <TranslateBody hex={hex} /> : null}
    >
      <span
        style={{ cursor: 'help' }}
        onMouseEnter={() => {
          window.clearTimeout(timer.current)
          timer.current = window.setTimeout(() => setOpen(true), 300)
        }}
        onMouseLeave={() => {
          window.clearTimeout(timer.current)
          setOpen(false)
        }}
      >
        {children}
      </span>
    </Popover>
  )
}

interface Row {
  key: string
  frame: Frame
  parsed: ParsedFrame | null
}

export function PfFrameViewer() {
  const t = useT()
  const queryClient = useQueryClient()
  const frames = useLiveFrames()
  const [paused, setPaused] = useState(false)
  const [frozen, setFrozen] = useState<Frame[]>([])
  const [direction, setDirection] = useState('')
  const [format, setFormat] = useState('')
  const [minLen, setMinLen] = useState('')
  const [keyword, setKeyword] = useState('')
  // WP7：展开值域子表的报文 key（同一时刻只展开一行）
  const [expandedKey, setExpandedKey] = useState<string | null>(null)

  // 首屏预热：WS 只推增量，用 /api/recent 补齐历史
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
    const min = minLen.trim() === '' ? undefined : Number(minLen)
    const out: Row[] = []
    for (let i = 0; i < source.length; i += 1) {
      const frame = source[i]
      const parsed = parseFrame(frame.hex)
      if (direction && frame.direction !== direction) continue
      if (format && parsed?.format !== format) continue
      if (min !== undefined && Number.isFinite(min) && frame.len < min) continue
      if (kw) {
        const hay = `${frame.hex} ${parsed?.typeName ?? ''} ${parsed?.cotName ?? ''}`.toLowerCase()
        if (!hay.includes(kw)) continue
      }
      out.push({ key: `${frame.ts ?? 0}-${i}`, frame, parsed })
    }
    return out
  }, [source, direction, format, minLen, keyword])

  return (
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
          <span>{t('frameViewer.title')}</span>
          <Label isCompact color="blue">
            {t('frameViewer.buffer', { n: rows.length })}
          </Label>
          {paused ? <Label isCompact color="orange">{t('frameViewer.paused')}</Label> : null}
        </Flex>
      </CardTitle>
      <CardBody>
        <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
          <div style={{ width: 160, minWidth: 160 }}>
            <FormSelect
              value={direction}
              onChange={(_e, v) => setDirection(v)}
              aria-label={t('common.direction')}
            >
            <FormSelectOption value="" label={t('common.all')} />
            <FormSelectOption value="rx" label={t('frameViewer.receive')} />
            <FormSelectOption value="tx" label={t('frameViewer.send')} />
            </FormSelect>
          </div>
          <div style={{ width: 140, minWidth: 140 }}>
            <FormSelect
              value={format}
              onChange={(_e, v) => setFormat(v)}
              aria-label={t('frameViewer.col.format')}
            >
            <FormSelectOption value="" label={t('common.all')} />
            <FormSelectOption value="I" label="I" />
            <FormSelectOption value="S" label="S" />
            <FormSelectOption value="U" label="U" />
            </FormSelect>
          </div>
          <div style={{ width: 140, minWidth: 140 }}>
          <TextInput
            type="number"
            min={0}
            placeholder={t('frameViewer.minLen')}
            value={minLen}
            onChange={(_e, v) => setMinLen(v)}
            aria-label={t('frameViewer.minLen')}
          />
          </div>
          <div style={{ width: 280, minWidth: 280 }}>
          <SearchInput
            placeholder={t('frameViewer.search')}
            value={keyword}
            onChange={(_e, v) => setKeyword(v)}
            onClear={() => setKeyword('')}
          />
          </div>
          <Button
            variant="secondary"
            onClick={() => {
              if (paused) {
                setPaused(false)
                setFrozen([])
              } else {
                setFrozen(frames)
                setPaused(true)
              }
            }}
          >
            {paused ? t('frameViewer.resume') : t('frameViewer.pause')}
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              clearFrames(queryClient)
              setFrozen([])
              setPaused(false)
            }}
          >
            {t('frameViewer.clear')}
          </Button>
        </Flex>

        <div style={{ marginTop: 8, maxHeight: 420, overflow: 'auto' }}>
          <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
            <thead className="pf-v6-c-table__thead">
              <tr className="pf-v6-c-table__tr">
                <th className="pf-v6-c-table__th">{t('frameViewer.col.time')}</th>
                <th className="pf-v6-c-table__th">{t('frameViewer.col.direction')}</th>
                <th className="pf-v6-c-table__th">{t('frameViewer.col.format')}</th>
                <th className="pf-v6-c-table__th" style={{ textAlign: 'right' }}>
                  {t('frameViewer.col.len')}
                </th>
                <th className="pf-v6-c-table__th">{t('frameViewer.col.type')}</th>
                <th className="pf-v6-c-table__th">{t('frameViewer.col.cot')}</th>
                <th className="pf-v6-c-table__th">{t('frameViewer.col.seq')}</th>
                <th className="pf-v6-c-table__th">{t('frameViewer.col.hex')}</th>
                <th className="pf-v6-c-table__th" style={{ width: 96 }}>
                  {t('frameTree.col.objects')}
                </th>
              </tr>
            </thead>
            <tbody className="pf-v6-c-table__tbody">
              {rows.length === 0 ? (
                <tr className="pf-v6-c-table__tr">
                  <td className="pf-v6-c-table__td" colSpan={9} style={{ textAlign: 'center', padding: 24, opacity: 0.7 }}>
                    {t('frameViewer.empty')}
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <Fragment key={row.key}>
                  <tr className="pf-v6-c-table__tr" data-testid="frame-row">
                    <td className="pf-v6-c-table__td mono">{formatClock(row.frame.ts ?? 0)}</td>
                    <td className="pf-v6-c-table__td">
                      <Label isCompact color={row.frame.direction === 'rx' ? 'blue' : 'green'}>
                        {row.frame.direction}
                      </Label>
                    </td>
                    <td className="pf-v6-c-table__td">{row.parsed?.format ?? '-'}</td>
                    <td className="pf-v6-c-table__td" style={{ textAlign: 'right' }}>
                      {row.frame.len}
                    </td>
                    <td className="pf-v6-c-table__td">{row.parsed?.typeName ?? '-'}</td>
                    <td className="pf-v6-c-table__td">{row.parsed?.cotName ?? '-'}</td>
                    <td className="pf-v6-c-table__td mono">
                      {row.parsed?.ns !== undefined ? `S${row.parsed.ns}` : '-'} /{' '}
                      {row.parsed?.nr !== undefined ? `R${row.parsed.nr}` : '-'}
                    </td>
                    <td className="pf-v6-c-table__td">
                      <TranslateHover hex={row.frame.hex}>
                        <span className="mono hex-wrap" style={{ wordBreak: 'break-all' }}>
                          {groupHex(row.frame.hex)}
                        </span>
                      </TranslateHover>
                    </td>
                    <td className="pf-v6-c-table__td">
                      <FrameExpandButton kit="pf"
                        open={expandedKey === row.key}
                        onToggle={() => setExpandedKey(
                          expandedKey === row.key ? null : row.key)} />
                    </td>
                  </tr>
                  {expandedKey === row.key ? (
                    <FrameObjectsRow hex={row.frame.hex} kit="pf" />
                  ) : null}
                  </Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>
      </CardBody>
    </Card>
  )
}
