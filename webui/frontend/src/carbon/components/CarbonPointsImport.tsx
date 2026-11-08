import { useRef, useState } from 'react'

import { Upload } from '@carbon/icons-react'
import { Button, Modal, TextArea } from '@carbon/react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import { queryKeys } from '../../api/queries'
import { useT } from '../../i18n'
import { Note } from './ui'

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

/** 这些扩展名走 SCD 预览（80-1 映射），其余直连 /api/points/import */
const SCD_EXTS = new Set(['scd', 'icd', 'cid', 'xml'])

interface PreviewState {
  yaml: string
  warnings: string[]
  stats: Record<string, number>
}

/**
 * 点表导入（T72）：SCD/CID/ICD 先经 `/api/scd/preview` 生成 104 点表 YAML
 * （80-1 精确映射 + CDC 推断），确认/编辑后再应用；YAML/CSV/JSON 直接导入。
 * 挂在子站工作台点表面板标题行——点表归子站管，主站页只读。
 */
export function CarbonPointsImport() {
  const t = useT()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [open, setOpen] = useState(false)
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.points() })
  }

  const close = (): void => {
    setOpen(false)
    setPreview(null)
    setError('')
  }

  const onPick = async (file: File): Promise<void> => {
    const text = await readText(file)
    const ext = (file.name.split('.').pop() ?? '').toLowerCase()
    setError('')
    setBusy(true)
    setOpen(true)
    try {
      if (SCD_EXTS.has(ext)) {
        const r = await api.scdPreview(text)
        if (r.ok) {
          setPreview({ yaml: r.yaml, warnings: r.warnings, stats: r.stats })
        } else {
          setError(t('pt.importFailed'))
        }
      } else {
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

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        data-testid="points-import-file"
        accept=".scd,.icd,.cid,.xml,.yaml,.yml,.csv,.json"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void onPick(file)
          e.target.value = ''
        }}
      />
      <Button
        kind="secondary"
        size="sm"
        hasIconOnly
        renderIcon={Upload}
        iconDescription={t('pt.import')}
        aria-label={t('pt.import')}
        tooltipAlignment="end"
        data-testid="points-import"
        onClick={() => fileRef.current?.click()}
      />
      <Modal
        open={open}
        modalHeading={t('pt.importScdTitle')}
        passiveModal
        size="lg"
        onRequestClose={close}
      >
        <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 12 }}>
          {t('pt.importScdHint')}
        </div>
        {error ? (
          <Note kind="error" title={t('pt.importFailed')} style={{ marginBottom: 12 }}>
            {error}
          </Note>
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
              <Note kind="warning" title={t('pt.importWarnings', { n: preview.warnings.length })} style={{ marginBottom: 12 }}>
                <ul style={{ margin: '4px 0 0', paddingInlineStart: 18 }}>
                  {preview.warnings.map((w) => (
                    <li key={w} style={{ fontSize: 12 }}>{w}</li>
                  ))}
                </ul>
              </Note>
            ) : null}
            <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 4 }}>
              {t('pt.importScdPreview')}
            </div>
            <TextArea
              labelText=""
              hideLabel
              rows={12}
              value={preview.yaml}
              onChange={(e) => setPreview({ ...preview, yaml: e.target.value })}
              style={{ fontFamily: 'var(--cds-code-01, monospace)', fontSize: 12 }}
              data-testid="scd-preview-yaml"
            />
            <div className="app-row" style={{ marginTop: 12, justifyContent: 'flex-end' }}>
              <Button kind="ghost" size="sm" onClick={close} disabled={busy}>
                {t('pt.importCancel')}
              </Button>
              <Button kind="primary" size="sm" onClick={() => void applyPreview()} disabled={busy} data-testid="scd-apply">
                {t('pt.importApply')}
              </Button>
            </div>
          </>
        ) : null}
      </Modal>
    </>
  )
}
