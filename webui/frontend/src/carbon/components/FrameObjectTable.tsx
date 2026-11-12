import { useEffect, useState } from 'react'

import { api } from '../../api/endpoints'
import type { FrameTree } from '../../api/types'
import { useT } from '../../i18n'
import { expandable, objectValue, qualityBad, qualityFlags, treeSummaryParts } from '../../lib/frameTree'

const CACHE = new Map<string, FrameTree | null>()
const CACHE_MAX = 300

/** 按 hex 取结构化树（缓存；失败缓存 null 以免反复请求脏帧） */
export function useFrameTree(hex: string): { tree: FrameTree | null; loading: boolean } {
  const [tree, setTree] = useState<FrameTree | null>(() => CACHE.get(hex) ?? null)
  const [loading, setLoading] = useState(!CACHE.has(hex))

  useEffect(() => {
    if (!hex) {
      setTree(null)
      setLoading(false)
      return
    }
    if (CACHE.has(hex)) {
      setTree(CACHE.get(hex) ?? null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    void api
      .framesDecode(hex)
      .then((r) => {
        if (cancelled) return
        const t = r.tree ?? null
        if (CACHE.size >= CACHE_MAX) {
          const first = CACHE.keys().next().value
          if (first !== undefined) CACHE.delete(first)
        }
        CACHE.set(hex, t)
        setTree(t)
      })
      .catch(() => {
        if (!cancelled) {
          CACHE.set(hex, null)
          setTree(null)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [hex])

  return { tree, loading }
}

/** 展开按钮（放在报文行的一个单元格里；展开状态由查看器持有） */
export function FrameExpandButton({
  open, onToggle, kit,
}: { open: boolean; onToggle: () => void; kit: 'carbon' | 'pf' }) {
  const t = useT()
  return (
    <button
      type="button"
      className={kit === 'carbon'
        ? 'cds--btn cds--btn--ghost cds--btn--sm'
        : 'pf-v6-c-button pf-m-link pf-m-inline'}
      style={{ padding: '0 4px', minHeight: 0, fontSize: 12 }}
      aria-expanded={open}
      title={t('frameTree.expandHint')}
      data-testid="frame-expand"
      onClick={onToggle}
    >
      {open ? '▾' : '▸'} {t('frameTree.expand')}
    </button>
  )
}

/**
 * 展开行：报文的值域子表（WP7）。
 *
 * 直接内嵌在同一表格的下一行（`colSpan` 跨列），不弹窗——现场常要边看
 * 报文流边对照多个对象，弹窗会挡住上下文。
 * 只对含信息对象的 I 帧出子表；S/U 帧给出「无信息体」说明而不是空表。
 */
export function FrameObjectsRow({
  hex, kit, colSpan = 9,
}: { hex: string; kit: 'carbon' | 'pf'; colSpan?: number }) {
  const t = useT()
  const { tree, loading } = useFrameTree(hex)
  const tdCls = kit === 'carbon' ? 'mono' : 'pf-v6-c-table__td mono'
  const tableCls = kit === 'carbon'
    ? 'cds--data-table cds--data-table--sm'
    : 'pf-v6-c-table pf-m-compact'
  const thCls = kit === 'carbon' ? '' : 'pf-v6-c-table__th'
  const cellCls = kit === 'carbon' ? '' : 'pf-v6-c-table__td'

  return (
    <tr data-testid="frame-objects">
      <td colSpan={colSpan} className={tdCls}
        style={{ background: 'var(--cds-layer-02)', padding: 0 }}>
        {loading ? (
          <div style={{ padding: 8 }}>{t('frameTree.loading')}</div>
        ) : !expandable(tree) ? (
          <div style={{ padding: 8, color: 'var(--cds-text-secondary)' }}>
            {t('frameTree.noObjects')}
          </div>
        ) : (
          <div style={{ padding: '6px 4px' }}>
            <div style={{ fontSize: 12, marginBottom: 6 }}>
              {(() => {
                const p = treeSummaryParts(tree)
                if (!p) return null
                return t('frameTree.summary', {
                  type: p.typeName, count: p.count,
                  sq: p.sq ? 'SQ=1' : 'SQ=0', ca: p.commonAddr,
                })
              })()}
              {' · '}
              {t('frameTree.apci', {
                vs: tree?.apci?.tx_seq ?? '-', vr: tree?.apci?.rx_seq ?? '-',
              })}
            </div>
            <table className={tableCls} style={{ width: '100%', tableLayout: 'fixed' }}>
              <thead>
                <tr>
                  <th className={thCls} style={{ width: 56 }}>#</th>
                  <th className={thCls} style={{ width: 110 }}>{t('frameTree.col.ioa')}</th>
                  <th className={thCls}>{t('frameTree.col.value')}</th>
                  <th className={thCls} style={{ width: 130 }}>{t('frameTree.col.quality')}</th>
                  <th className={thCls} style={{ width: 170 }}>{t('frameTree.col.timestamp')}</th>
                  <th className={thCls} style={{ width: 150 }}>{t('frameTree.col.raw')}</th>
                </tr>
              </thead>
              <tbody>
                {(tree?.objects ?? []).map((o) => (
                  <tr key={`${o.index}-${o.ioa}`}>
                    <td className={cellCls}>{o.index}</td>
                    <td className={`${cellCls} mono`}>{o.ioa}</td>
                    <td className={`${cellCls} mono`} style={{ wordBreak: 'break-all' }}>
                      {objectValue(o)}
                    </td>
                    <td className={cellCls}
                      style={{ color: qualityBad(o.quality_bits)
                        ? 'var(--cds-support-error)' : undefined }}>
                      {qualityFlags(o.quality_bits) || o.quality || '—'}
                    </td>
                    <td className={`${cellCls} mono`} style={{ fontSize: 11 }}>
                      {o.timestamp ?? '—'}
                    </td>
                    <td className={`${cellCls} mono`} style={{ fontSize: 11, wordBreak: 'break-all' }}>
                      {o.raw_hex ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </td>
    </tr>
  )
}
