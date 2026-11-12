import { useEffect, useState } from 'react'

import {
  Button,
  Checkbox,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  TextInput,
} from '@patternfly/react-core'

import type { Point, PointUpsertRequest } from '../../api/types'
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'
import {
  draftFromPoint, usePointEdit,
  type PointDraft,
} from '../../lib/pointEdit'

const TYPES: PointUpsertRequest['type'][] = ['YX', 'YC', 'YK', 'YM', 'STEP']

/** 点表在线编辑对话框（WP10a）：PF 版。 */
export function PfPointEditDialog({
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
  const errText = edit.error.startsWith('pointEdit.err.')
    ? t(edit.error as MessageKey)
    : edit.error

  const submit = async (): Promise<void> => {
    if (await edit.save(draft)) onClose()
  }
  const remove = async (): Promise<void> => {
    if (point && await edit.remove(point.type, point.ioa)) onClose()
  }

  return (
    <Modal isOpen={open} variant="small" onClose={onClose}
      aria-labelledby="pf-point-edit-title">
      <ModalHeader
        title={isEdit ? t('pointEdit.editTitle') : t('pointEdit.addTitle')}
        labelId="pf-point-edit-title"
      />
      <ModalBody>
        <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 12 }}>
          {t('pointEdit.hint')}
        </div>
        {edit.error ? (
          <div style={{ marginBottom: 10, color: 'var(--pf-t--global--text--color--status--danger--default)' }}>
            {errText}
          </div>
        ) : null}

        <FormGroup label={t('pointEdit.col.type')} fieldId="pf-pe-type">
          <FormSelect id="pf-pe-type" value={draft.type} isDisabled={isEdit}
            onChange={(_e, v) => set({ type: v as PointDraft['type'] })}>
            {TYPES.map((ty) => <FormSelectOption key={ty} value={ty} label={ty} />)}
          </FormSelect>
        </FormGroup>
        <FormGroup label={t('pointEdit.col.ioa')} fieldId="pf-pe-ioa">
          <TextInput id="pf-pe-ioa" type="number" value={draft.ioa}
            isDisabled={isEdit} onChange={(_e, v) => set({ ioa: v })} />
        </FormGroup>
        <FormGroup label={t('pointEdit.col.name')} fieldId="pf-pe-name">
          <TextInput id="pf-pe-name" value={draft.name}
            onChange={(_e, v) => set({ name: v })} />
        </FormGroup>
        <FormGroup label={t('pointEdit.col.group')} fieldId="pf-pe-group">
          <TextInput id="pf-pe-group" type="number" value={draft.group}
            onChange={(_e, v) => set({ group: v })} />
        </FormGroup>
        <Checkbox id="pf-pe-enabled" label={t('pointEdit.enabled')}
          isChecked={draft.enabled}
          onChange={(_e, checked) => set({ enabled: checked })} />

        {draft.type === 'YC' || draft.type === 'STEP' ? (
          <>
            <FormGroup label={t('pointEdit.min')} fieldId="pf-pe-min">
              <TextInput id="pf-pe-min" type="number" value={draft.min_value}
                onChange={(_e, v) => set({ min_value: v })} />
            </FormGroup>
            <FormGroup label={t('pointEdit.max')} fieldId="pf-pe-max">
              <TextInput id="pf-pe-max" type="number" value={draft.max_value}
                onChange={(_e, v) => set({ max_value: v })} />
            </FormGroup>
          </>
        ) : null}
        {draft.type === 'YC' ? (
          <>
            <FormGroup label={t('pointEdit.unit')} fieldId="pf-pe-unit">
              <TextInput id="pf-pe-unit" value={draft.unit}
                onChange={(_e, v) => set({ unit: v })} />
            </FormGroup>
            <FormGroup label={t('pointEdit.decimals')} fieldId="pf-pe-dec">
              <TextInput id="pf-pe-dec" type="number" value={draft.decimal_places}
                onChange={(_e, v) => set({ decimal_places: v })} />
            </FormGroup>
          </>
        ) : null}
        {draft.type === 'YK' ? (
          <Checkbox id="pf-pe-sbo" label={t('pointEdit.sbo')}
            isChecked={draft.sbo}
            onChange={(_e, checked) => set({ sbo: checked })} />
        ) : null}
      </ModalBody>
      <ModalFooter>
        <Button variant="primary" isDisabled={edit.busy} onClick={() => void submit()}>
          {t('pointEdit.save')}
        </Button>
        <Button variant="link" isDisabled={edit.busy} onClick={onClose}>
          {t('pointEdit.cancel')}
        </Button>
        {isEdit ? (
          <Button variant="danger" isDisabled={edit.busy} onClick={() => void remove()}>
            {t('pointEdit.delete')}
          </Button>
        ) : null}
      </ModalFooter>
    </Modal>
  )
}

/** 编辑入口按钮（PF 点表工具栏用） */
export function PfPointEditButtons({
  selected, onAdd, onEdit,
}: {
  selected: Point | null
  onAdd: () => void
  onEdit: () => void
}) {
  const t = useT()
  return (
    <>
      <Button variant="link" isInline onClick={onAdd} data-testid="point-add">
        {t('pointEdit.add')}
      </Button>
      <Button variant="link" isInline isDisabled={!selected} onClick={onEdit}
        data-testid="point-edit">
        {t('pointEdit.edit')}
      </Button>
    </>
  )
}
