import { useEffect, useRef, useState } from 'react'

import { Button, Link, Select, SelectItem, Tag } from '@carbon/react'

import { profileExportUrl } from '../../api/endpoints'
import { useT } from '../../i18n'
import { useProfiles } from '../../lib/useProfiles'
import { Note, Panel, TableFrame, TextField } from '../components/ui'

/** 工程配置方案卡片（WP5）：命名方案保存/切换/导入导出 + 刷新后自动恢复。 */
export function CarbonProfilesCard() {
  const t = useT()
  const p = useProfiles()
  const [importText, setImportText] = useState('')
  const restored = useRef(false)

  // 挂载时恢复上次应用的方案——"刷新后参数/阈值/点表全部还原"的落点
  useEffect(() => {
    if (restored.current) return
    restored.current = true
    void p.actions.restore()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Panel
      title={t('profiles.title')}
      right={
        <span className="app-row">
          <Button kind="ghost" size="sm" onClick={p.refresh}
            data-testid="profiles-refresh">{t('profiles.refresh')}</Button>
          <Button kind="primary" size="sm" disabled={p.busy} onClick={() => p.actions.apply(p.selected)}
            data-testid="profiles-apply">{t('profiles.apply')}</Button>
        </span>
      }
    >
      <div className="app-hint">{t('profiles.hint')}</div>
      {p.error ? <Note kind="error" title={t('common.error')}>{p.error}</Note> : null}
      {p.message ? <Note kind="success" title={t('profiles.applied', { detail: p.message })} /> : null}

      <div className="app-row" style={{ marginTop: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ width: 260, minWidth: 220 }}>
          <Select
            id="profiles-select"
            labelText={t('profiles.current')}
            value={p.selected}
            onChange={(event) => p.setSelected((event.target as HTMLSelectElement).value)}
          >
            <SelectItem value="" text={t('profiles.none')} />
            {p.profiles.map((row) => (
              <SelectItem key={row.name} value={row.name}
                text={row.name === p.active ? `${row.name} ●` : row.name} />
            ))}
          </Select>
        </div>
        <Button kind="ghost" size="sm" disabled={p.busy || !p.selected}
          onClick={() => p.actions.apply(p.selected)}>{t('profiles.apply')}</Button>
        <Button kind="danger--ghost" size="sm" disabled={p.busy || !p.selected}
          onClick={() => p.actions.remove(p.selected)}>{t('profiles.delete')}</Button>
        <Link href={p.selected ? profileExportUrl(p.selected) : undefined} download>
          {t('profiles.export')}
        </Link>
      </div>

      <div className="app-row" style={{ marginTop: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <TextField id="profiles-new-name" label={t('profiles.newName')}
          value={p.newName} onChange={p.setNewName} width={220} />
        <Button kind="secondary" size="sm" disabled={p.busy || !p.newName.trim()}
          onClick={() => p.actions.save(p.newName)} data-testid="profiles-save">
          {t('profiles.saveAs')}
        </Button>
        <Button kind="ghost" size="sm" disabled={p.busy || !p.selected}
          onClick={() => p.actions.save(p.selected)}>
          {t('profiles.overwrite')}
        </Button>
      </div>

      <div style={{ marginTop: 14 }}>
        <div className="app-hint" style={{ marginBottom: 6 }}>{t('profiles.importHint')}</div>
        <textarea
          className="cds--text-area"
          style={{ width: '100%', minHeight: 90, fontFamily: 'monospace', fontSize: 12 }}
          aria-label={t('profiles.importHint')}
          placeholder={t('profiles.importPlaceholder')}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
        />
        <Button kind="ghost" size="sm" disabled={p.busy || !importText.trim() || !p.newName.trim()}
          onClick={() => { p.actions.importText(p.newName, importText); setImportText('') }}>
          {t('profiles.import')}
        </Button>
      </div>

      {p.profiles.length === 0 ? (
        <div className="app-hint" style={{ marginTop: 10 }}>{t('profiles.empty')}</div>
      ) : (
        <div style={{ marginTop: 12 }}>
          <TableFrame testid="profiles-table">
            <table className="cds--data-table cds--data-table--md"
              style={{ width: '100%', tableLayout: 'fixed' }}>
              <thead><tr>
                <th style={{ width: 200 }}>{t('profiles.col.name')}</th>
                <th>{t('profiles.col.summary')}</th>
                <th style={{ width: 90 }}>{t('profiles.col.active')}</th>
              </tr></thead>
              <tbody>
                {p.profiles.map((row) => (
                  <tr key={row.name} onClick={() => p.setSelected(row.name)}
                    style={{ cursor: 'pointer' }}>
                    <td>{row.name}</td>
                    <td style={{ fontSize: 12 }}>{p.actions.summaryOf(row) || '—'}</td>
                    <td>
                      {row.name === p.active
                        ? <Tag size="sm" type="green">{t('profiles.activeTag')}</Tag>
                        : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
        </div>
      )}
    </Panel>
  )
}
