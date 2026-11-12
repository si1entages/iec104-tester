import { useEffect, useState } from 'react'

import {
  Button, Checkbox, Modal, Select, SelectItem, TextInput,
} from '@carbon/react'

import type { Point, PointUpsertRequest } from '../../api/types'
import { useT } from '../../i18n'
import {
  draftFromPoint, usePointEdit,
  type PointDraft,
} from '../../lib/pointEdit'
import { Note } from './ui'

const TYPES: PointUpsertRequest['type'][] = ['YX', 'YC', 'YK', 'YM', 'STEP']

/** 点表在线编辑对话框（WP10a）：新增 / 编辑 / 删除，Carbon 版。 */
export function CarbonPointEditDialog({
  point, open, onClose,
}: { point: Point | null; open: boolean; onClose: () => void }) {
  const t = useT()
  const [draft, setDraft] = useState<PointDraft>(() => draftFromPoint(point))
  const edit = usePointEdit()

  useEffect(() => {
    if (open) {
      setDraft(draftFromPoint(point))
      edit.setError('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, point])

  const isEdit = point !== null
  const set = (patch: Partial<PointDraft>) => setDraft((d) => ({ ...d, ...patch }))

  const submit = async (): Promise<void> => {
    const ok = await edit.save(draft)
    if (ok) onClose()
  }

  const remove = async (): Promise<void> => {
    if (!point) return
    const ok = await edit.remove(point.type, point.ioa)
    if (ok) onClose()
  }

  return (
    <Modal
      open={open}
      size="sm"
      modalHeading={isEdit ? t('pointEdit.editTitle') : t('pointEdit.addTitle')}
      primaryButtonText={t('pointEdit.save')}
      secondaryButtonText={t('pointEdit.cancel')}
      primaryButtonDisabled={edit.busy}
      danger={isEdit}
      onRequestSubmit={() => void submit()}
      onRequestClose={onClose}
      onSecondarySubmit={onClose}
      secondaryButtons={isEdit ? [
        { buttonText: t('pointEdit.delete'), onClick: () => void remove() },
      ] : undefined}
    >
      {edit.error ? (
        <Note kind="error" title={t('common.error')}>
          {edit.error.startsWith('pointEdit.err.')
            ? t(edit.error as Parameters<typeof t>[0])
            : edit.error}
        </Note>
      ) : null}
      <div className="app-hint" style={{ marginBottom: 10 }}>{t('pointEdit.hint')}</div>

      <div style={{ display: 'grid', gap: 8 }}>
        <Select
          id="pe-type"
          labelText={t('pointEdit.col.type')}
          value={draft.type}
          onChange={(e) => set({ type: e.target.value as PointDraft['type'] })}
          disabled={isEdit}
        >
          {TYPES.map((ty) => <SelectItem key={ty} value={ty} text={ty} />)}
        </Select>
        <TextInput
          id="pe-ioa"
          type="number"
          labelText={t('pointEdit.col.ioa')}
          value={draft.ioa}
          disabled={isEdit}
          onChange={(e) => set({ ioa: e.target.value })}
        />
        <TextInput
          id="pe-name"
          labelText={t('pointEdit.col.name')}
          value={draft.name}
          onChange={(e) => set({ name: e.target.value })}
        />
        <TextInput
          id="pe-group"
          type="number"
          labelText={t('pointEdit.col.group')}
          value={draft.group}
          onChange={(e) => set({ group: e.target.value })}
        />
        <Checkbox
          id="pe-enabled"
          labelText={t('pointEdit.enabled')}
          checked={draft.enabled}
          onChange={(_e, checked) => set({ enabled: Boolean(checked) })}
        />

        {draft.type === 'YC' || draft.type === 'STEP' ? (
          <>
            <TextInput
              id="pe-min"
              type="number"
              labelText={t('pointEdit.min')}
              value={draft.min_value}
              onChange={(e) => set({ min_value: e.target.value })}
            />
            <TextInput
              id="pe-max"
              type="number"
              labelText={t('pointEdit.max')}
              value={draft.max_value}
              onChange={(e) => set({ max_value: e.target.value })}
            />
          </>
        ) : null}
        {draft.type === 'YC' ? (
          <>
            <TextInput
              id="pe-unit"
              labelText={t('pointEdit.unit')}
              value={draft.unit}
              onChange={(e) => set({ unit: e.target.value })}
            />
            <TextInput
              id="pe-decimals"
              type="number"
              labelText={t('pointEdit.decimals')}
              value={draft.decimal_places}
              onChange={(e) => set({ decimal_places: e.target.value })}
            />
          </>
        ) : null}
        {draft.type === 'YK' ? (
          <Checkbox
            id="pe-sbo"
            labelText={t('pointEdit.sbo')}
            checked={draft.sbo}
            onChange={(_e, checked) => set({ sbo: Boolean(checked) })}
          />
        ) : null}
      </div>
    </Modal>
  )
}

/** 编辑入口按钮（点表工具栏用；新增/编辑共用同一个对话框） */
export function CarbonPointEditButtons({
  selected, onAdd, onEdit,
}: {
  selected: Point | null
  onAdd: () => void
  onEdit: () => void
}) {
  const t = useT()
  return (
    <>
      <Button kind="ghost" size="sm" onClick={onAdd} data-testid="point-add">
        {t('pointEdit.add')}
      </Button>
      <Button kind="ghost" size="sm" disabled={!selected} onClick={onEdit}
        data-testid="point-edit">
        {t('pointEdit.edit')}
      </Button>
    </>
  )
}
