import { useEffect, useMemo, useRef, useState } from 'react'

import { Button, Popover, PopoverContent, Search, Tag } from '@carbon/react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { clearFrames, replaceFrames, useLiveFrames } from '../../api/queries'
import type { Frame, FrameTranslation } from '../../api/types'
import { useT } from '../../i18n'
import { formatClock, groupHex } from '../../lib/format'
import { parseFrame } from '../../lib/frame'
import type { ParsedFrame } from '../../lib/frame'
import { normalizeFrames } from '../../lib/records'
import { Panel, SelectField, TableFrame, TextField } from './ui'

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

/** 悬停 300ms 拉起翻译（与 PF 版一致：快速扫过报文流时不逐帧请求）。 */
function TranslateHover({ hex, children }: { hex: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <Popover open={open} align="left">
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
      {open ? (
        <PopoverContent>
          <div style={{ padding: 12 }}>
            <TranslateBody hex={hex} />
          </div>
        </PopoverContent>
      ) : null}
    </Popover>
  )
}

interface Row {
  key: string
  frame: Frame
  parsed: ParsedFrame | null
}

export function CarbonFrameViewer() {
  const t = useT()
  const queryClient = useQueryClient()
  const frames = useLiveFrames()
  const [paused, setPaused] = useState(false)
  const [frozen, setFrozen] = useState<Frame[]>([])
  const [direction, setDirection] = useState('')
  const [format, setFormat] = useState('')
  const [minLen, setMinLen] = useState('')
  const [keyword, setKeyword] = useState('')

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
    <Panel
      title={
        <span className="app-row">
          {t('frameViewer.title')}
          <Tag size="sm" type="blue">
            {t('frameViewer.buffer', { n: rows.length })}
          </Tag>
          {paused ? <Tag size="sm" type="magenta">{t('frameViewer.paused')}</Tag> : null}
        </span>
      }
    >
      <div className="app-row">
        <SelectField
          id="cb-frame-direction"
          label={t('common.direction')}
          hideLabel
          width={160}
          value={direction}
          onChange={setDirection}
          options={[
            { value: '', label: t('common.all') },
            { value: 'rx', label: t('frameViewer.receive') },
            { value: 'tx', label: t('frameViewer.send') },
          ]}
        />
        <SelectField
          id="cb-frame-format"
          label={t('frameViewer.col.format')}
          hideLabel
          width={140}
          value={format}
          onChange={setFormat}
          options={[
            { value: '', label: t('common.all') },
            { value: 'I', label: 'I' },
            { value: 'S', label: 'S' },
            { value: 'U', label: 'U' },
          ]}
        />
        <div style={{ width: 140, minWidth: 140 }}>
          <TextField
            id="cb-frame-minlen"
            label={t('frameViewer.minLen')}
            hideLabel
            type="number"
            width={140}
            value={minLen}
            onChange={setMinLen}
            placeholder={t('frameViewer.minLen')}
          />
        </div>
        <div style={{ width: 280, minWidth: 280 }}>
          <Search
            id="cb-frame-search"
            labelText={t('frameViewer.search')}
            placeholder={t('frameViewer.search')}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onClear={() => setKeyword('')}
          />
        </div>
        <Button
          kind="secondary"
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
          kind="secondary"
          onClick={() => {
            clearFrames(queryClient)
            setFrozen([])
            setPaused(false)
          }}
        >
          {t('frameViewer.clear')}
        </Button>
      </div>

      <div style={{ marginTop: 8, maxHeight: 420, overflow: 'auto' }}>
        <TableFrame>
          <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
            <thead>
              <tr>
                <th><span className="cds--table-header-label">{t('frameViewer.col.time')}</span></th>
                <th><span className="cds--table-header-label">{t('frameViewer.col.direction')}</span></th>
                <th><span className="cds--table-header-label">{t('frameViewer.col.format')}</span></th>
                <th style={{ textAlign: 'right' }}><span className="cds--table-header-label">{t('frameViewer.col.len')}</span></th>
                <th><span className="cds--table-header-label">{t('frameViewer.col.type')}</span></th>
                <th><span className="cds--table-header-label">{t('frameViewer.col.cot')}</span></th>
                <th><span className="cds--table-header-label">{t('frameViewer.col.seq')}</span></th>
                <th><span className="cds--table-header-label">{t('frameViewer.col.hex')}</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: 24, opacity: 0.7 }}>
                    {t('frameViewer.empty')}
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.key} data-testid="frame-row">
                    <td className="mono">{formatClock(row.frame.ts ?? 0)}</td>
                    <td>
                      <Tag size="sm" type={row.frame.direction === 'rx' ? 'blue' : 'green'}>
                        {row.frame.direction}
                      </Tag>
                    </td>
                    <td>{row.parsed?.format ?? '-'}</td>
                    <td style={{ textAlign: 'right' }}>{row.frame.len}</td>
                    <td>{row.parsed?.typeName ?? '-'}</td>
                    <td>{row.parsed?.cotName ?? '-'}</td>
                    <td className="mono">
                      {row.parsed?.ns !== undefined ? `S${row.parsed.ns}` : '-'} /{' '}
                      {row.parsed?.nr !== undefined ? `R${row.parsed.nr}` : '-'}
                    </td>
                    <td>
                      <TranslateHover hex={row.frame.hex}>
                        <span className="mono" style={{ wordBreak: 'break-all' }}>
                          {groupHex(row.frame.hex)}
                        </span>
                      </TranslateHover>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </TableFrame>
      </div>
    </Panel>
  )
}
