import { useEffect, useRef, useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FormSelect,
  FormSelectOption,
  Label,
} from '@patternfly/react-core'

import { profileExportUrl } from '../../api/endpoints'
import { useT } from '../../i18n'
import { useProfiles } from '../../lib/useProfiles'

/** 工程配置方案卡片（WP5）：命名方案保存/切换/导入导出 + 刷新后自动恢复。 */
export function PfProfilesCard() {
  const t = useT()
  const p = useProfiles()
  const [importText, setImportText] = useState('')
  const restored = useRef(false)

  useEffect(() => {
    if (restored.current) return
    restored.current = true
    void p.actions.restore()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Card>
      <CardTitle>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}
          flexWrap={{ default: 'wrap' }}>
          <span>{t('profiles.title')}</span>
          <Button variant="link" isInline size="sm" onClick={p.refresh}
            data-testid="profiles-refresh">{t('profiles.refresh')}</Button>
          <Button variant="primary" size="sm" isDisabled={p.busy || !p.selected}
            onClick={() => p.actions.apply(p.selected)}
            data-testid="profiles-apply">{t('profiles.apply')}</Button>
        </Flex>
      </CardTitle>
      <CardBody>
        <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 12 }}>{t('profiles.hint')}</div>
        {p.error ? <Label isCompact color="red">{p.error}</Label> : null}
        {p.message ? (
          <div style={{ marginBottom: 8 }}>
            <Label isCompact color="green">
              {t('profiles.applied', { detail: p.message })}
            </Label>
          </div>
        ) : null}

        <Flex alignItems={{ default: 'alignItemsFlexEnd' }} gap={{ default: 'gapSm' }}
          flexWrap={{ default: 'wrap' }} style={{ marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 12, marginBottom: 4 }}>{t('profiles.current')}</div>
            <FormSelect id="pf-profiles-select" value={p.selected}
              aria-label={t('profiles.current')}
              onChange={(_e, v) => p.setSelected(v)}>
              <FormSelectOption value="" label={t('profiles.none')} />
              {p.profiles.map((row) => (
                <FormSelectOption key={row.name} value={row.name}
                  label={row.name === p.active ? `${row.name} ●` : row.name} />
              ))}
            </FormSelect>
          </div>
          <Button variant="danger" size="sm" isDisabled={p.busy || !p.selected}
            onClick={() => p.actions.remove(p.selected)}>{t('profiles.delete')}</Button>
          <a href={p.selected ? profileExportUrl(p.selected) : undefined} download>
            {t('profiles.export')}
          </a>
        </Flex>

        <Flex alignItems={{ default: 'alignItemsFlexEnd' }} gap={{ default: 'gapSm' }}
          flexWrap={{ default: 'wrap' }} style={{ marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 12, marginBottom: 4 }}>{t('profiles.newName')}</div>
            <input className="pf-v6-c-form-control" value={p.newName}
              aria-label={t('profiles.newName')}
              onChange={(e) => p.setNewName(e.target.value)} />
          </div>
          <Button variant="secondary" size="sm" isDisabled={p.busy || !p.newName.trim()}
            onClick={() => p.actions.save(p.newName)} data-testid="profiles-save">
            {t('profiles.saveAs')}
          </Button>
          <Button variant="link" isInline size="sm" isDisabled={p.busy || !p.selected}
            onClick={() => p.actions.save(p.selected)}>
            {t('profiles.overwrite')}
          </Button>
        </Flex>

        <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>{t('profiles.importHint')}</div>
        <textarea
          className="pf-v6-c-form-control"
          style={{ width: '100%', minHeight: 90, fontFamily: 'monospace', fontSize: 12 }}
          aria-label={t('profiles.importHint')}
          placeholder={t('profiles.importPlaceholder')}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
        />
        <Button variant="link" isInline size="sm"
          isDisabled={p.busy || !importText.trim() || !p.newName.trim()}
          onClick={() => { p.actions.importText(p.newName, importText); setImportText('') }}>
          {t('profiles.import')}
        </Button>

        {p.profiles.length === 0 ? (
          <div style={{ fontSize: 12, opacity: 0.7, marginTop: 10 }}>{t('profiles.empty')}</div>
        ) : (
          <div style={{ marginTop: 12 }}>
            <div style={{ overflowX: 'auto' }} data-testid="profiles-table">
              <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
                <thead className="pf-v6-c-table__thead">
                  <tr className="pf-v6-c-table__tr">
                    <th className="pf-v6-c-table__th" style={{ width: 200, minWidth: 200 }}>
                      {t('profiles.col.name')}
                    </th>
                    <th className="pf-v6-c-table__th">{t('profiles.col.summary')}</th>
                    <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>
                      {t('profiles.col.active')}
                    </th>
                  </tr>
                </thead>
                <tbody className="pf-v6-c-table__tbody">
                  {p.profiles.map((row) => (
                    <tr key={row.name} className="pf-v6-c-table__tr"
                      onClick={() => p.setSelected(row.name)} style={{ cursor: 'pointer' }}>
                      <td className="pf-v6-c-table__td">{row.name}</td>
                      <td className="pf-v6-c-table__td" style={{ fontSize: 12 }}>
                        {p.actions.summaryOf(row) || '—'}
                      </td>
                      <td className="pf-v6-c-table__td">
                        {row.name === p.active ? (
                          <Label isCompact color="green">{t('profiles.activeTag')}</Label>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
