import { useRef, useState } from 'react'

import {
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  TextArea,
} from '@patternfly/react-core'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { queryKeys } from '../../api/queries'
import { useT } from '../../i18n'
import type { XlsxPreviewResponse } from '../../api/types'

/** 读文件文本：File.text() 在部分环境（如 jsdom）缺失，FileReader 兜底 */
function readText(file: File): Promise<string> {
  if (typeof file.text === 'function') return file.text()
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error ?? new Error('read file failed')) // i18n-ignore 内部异常
    reader.readAsText(file)
  })
}

/** 读二进制文件：xlsx 点表用（T95） */
function readArrayBuffer(file: File): Promise<ArrayBuffer> {
  if (typeof file.arrayBuffer === 'function') return file.arrayBuffer()
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.onerror = () => reject(reader.error ?? new Error('read file failed')) // i18n-ignore 内部异常
    reader.readAsArrayBuffer(file)
  })
}

/** 这些扩展名走 SCD 预览（80-1 映射），xlsx 走 T95 Excel 预览，其余直连 /api/points/import */
const SCD_EXTS = new Set(['scd', 'icd', 'cid', 'xml'])
const XLSX_EXTS = new Set(['xlsx'])

interface PreviewState {
  yaml: string
  warnings: string[]
  stats: Record<string, number>
}

/**
 * 点表导入（T72）：与 CarbonPointsImport 同构——SCD/CID/ICD 先经
 * `/api/scd/preview` 生成 104 点表 YAML（80-1 精确映射 + CDC 推断），
 * xlsx 先经 `/api/points/xlsx/preview` 解析确认（T95），
 * 确认/编辑后再应用；YAML/CSV/JSON 直接导入。
 */
export function PfPointsImport() {
  const t = useT()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [open, setOpen] = useState(false)
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [xlsx, setXlsx] = useState<XlsxPreviewResponse | null>(null)
  const [xlsxData, setXlsxData] = useState<ArrayBuffer | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.points() })
    void queryClient.invalidateQueries({ queryKey: queryKeys.designDiff() })
  }

  const close = (): void => {
    setOpen(false)
    setPreview(null)
    setXlsx(null)
    setXlsxData(null)
    setError('')
  }

  const onPick = async (file: File): Promise<void> => {
    const ext = (file.name.split('.').pop() ?? '').toLowerCase()
    setError('')
    setBusy(true)
    setOpen(true)
    try {
      if (XLSX_EXTS.has(ext)) {
        const data = await readArrayBuffer(file)
        const r = await api.pointsXlsxPreview(data)
        if (r.ok) {
          setXlsx(r)
          setXlsxData(data)
        } else {
          setError(r.error ?? t('pt.importFailed'))
        }
      } else if (SCD_EXTS.has(ext)) {
        const text = await readText(file)
        const r = await api.scdPreview(text)
        if (r.ok) {
          setPreview({ yaml: r.yaml, warnings: r.warnings, stats: r.stats })
        } else {
          setError(t('pt.importFailed'))
        }
      } else {
        const text = await readText(file)
        const r = await api.importPoints(text, 'auto')
        if (r.ok) {
          close()
          invalidate()
        } else {
          setError(r.error ?? t('pt.importFailed'))
        }
      }
    } catch (e) {
      setError(t('pt.importScdFailed', { error: (e as Error).message }))
    } finally {
      setBusy(false)
    }
  }

  const applyPreview = async (): Promise<void> => {
    if (!preview) return
    setBusy(true)
    setError('')
    try {
      const r = await api.importPoints(preview.yaml, 'yaml')
      if (r.ok) {
        close()
        invalidate()
      } else {
        setError(r.error ?? t('pt.importFailed'))
      }
    } catch (e) {
      setError(t('pt.importFailedWith', { error: (e as Error).message }))
    } finally {
      setBusy(false)
    }
  }

  const applyXlsx = async (): Promise<void> => {
    if (!xlsxData) return
    setBusy(true)
    setError('')
    try {
      const r = await api.pointsXlsxImport(xlsxData)
      if (r.ok) {
        close()
        invalidate()
      } else {
        setError(r.error ?? t('pt.importFailed'))
      }
    } catch (e) {
      setError(t('pt.importFailedWith', { error: (e as Error).message }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        data-testid="points-import-file"
        accept=".scd,.icd,.cid,.xml,.yaml,.yml,.csv,.json,.xlsx"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void onPick(file)
          e.target.value = ''
        }}
      />
      <Button
        variant="secondary"
        data-testid="points-import"
        onClick={() => fileRef.current?.click()}
      >
        {t('pt.import')}
      </Button>
      <Modal isOpen={open} variant="medium" onClose={close} aria-labelledby="pf-pti-title">
        <ModalHeader title={t('pt.importScdTitle')} labelId="pf-pti-title" />
        <ModalBody>
          <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 12 }}>
            {t('pt.importScdHint')}
          </div>
          {error ? (
            <div
              role="alert"
              style={{
                marginBottom: 12,
                padding: '8px 12px',
                borderRadius: 4,
                fontSize: 13,
                border: '1px solid var(--pf-t--global--color--status--danger--default)',
                color: 'var(--pf-t--global--text--color--status--danger--default)',
              }}
            >
              {error}
            </div>
          ) : null}
          {xlsx ? (
            <>
              <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 12 }}>
                {t('pt.xlsxHint')}
              </div>
              <div className="app-row" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12, opacity: 0.8 }}>
                  <strong>{t('pt.xlsxParsed', { n: xlsx.total })}</strong>
                </span>
                {Object.entries(xlsx.stats)
                  .filter(([, n]) => n > 0)
                  .map(([k, n]) => (
                    <span key={k} style={{ fontSize: 12, opacity: 0.8 }}>
                      {k}: <strong>{n}</strong>
                    </span>
                  ))}
              </div>
              {xlsx.errors.length > 0 ? (
                <div
                  role="alert"
                  style={{
                    marginBottom: 12,
                    padding: '8px 12px',
                    borderRadius: 4,
                    fontSize: 12,
                    border: '1px solid var(--pf-t--global--color--status--warning--default)',
                  }}
                >
                  <div>{t('pt.xlsxRowErrors', { n: xlsx.errors.length })}</div>
                  <ul style={{ margin: '4px 0 0', paddingInlineStart: 18 }}>
                    {xlsx.errors.slice(0, 20).map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div
                style={{ maxHeight: 180, overflow: 'auto', fontSize: 12, opacity: 0.8, marginBottom: 4 }}
                data-testid="xlsx-preview-rows"
              >
                {xlsx.rows.map((r) => (
                  <div key={r.ioa}>
                    IOA {r.ioa} · {r.name}
                  </div>
                ))}
              </div>
            </>
          ) : null}
          {preview ? (
            <>
              <div className="app-row" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
                {Object.entries(preview.stats)
                  .filter(([, n]) => n > 0)
                  .map(([k, n]) => (
                    <span key={k} style={{ fontSize: 12, opacity: 0.8 }}>
                      {k}: <strong>{n}</strong>
                    </span>
                  ))}
              </div>
              {preview.warnings.length > 0 ? (
                <div
                  role="alert"
                  style={{
                    marginBottom: 12,
                    padding: '8px 12px',
                    borderRadius: 4,
                    fontSize: 12,
                    border: '1px solid var(--pf-t--global--color--status--warning--default)',
                  }}
                >
                  <div>{t('pt.importWarnings', { n: preview.warnings.length })}</div>
                  <ul style={{ margin: '4px 0 0', paddingInlineStart: 18 }}>
                    {preview.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 4 }}>
                {t('pt.importScdPreview')}
              </div>
              <TextArea
                aria-label={t('pt.importScdPreview')}
                rows={12}
                value={preview.yaml}
                onChange={(_e, v) => setPreview({ ...preview, yaml: v })}
                style={{ fontFamily: 'var(--pf-t--global--font--family--mono)', fontSize: 12 }}
                data-testid="scd-preview-yaml"
              />
            </>
          ) : null}
        </ModalBody>
        <ModalFooter>
          <Button variant="link" onClick={close} isDisabled={busy}>
            {t('pt.importCancel')}
          </Button>
          <Button
            variant="primary"
            onClick={() => void (preview ? applyPreview() : applyXlsx())}
            isDisabled={busy || (!preview && !xlsxData)}
            data-testid={preview ? 'scd-apply' : 'xlsx-apply'}
          >
            {preview ? t('pt.importApply') : t('pt.xlsxApply')}
          </Button>
        </ModalFooter>
      </Modal>
    </>
  )
}
