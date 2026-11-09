import type { CSSProperties, ReactNode } from 'react'

import {
  Checkbox,
  Pagination,
  InlineNotification,
  NumberInput,
  Select,
  SelectItem,
  Tag,
  TextInput,
  Tile,
  Toggle,
} from '@carbon/react'

import { useT } from '../../i18n'

/**
 * Carbon 套件的共享小件：把散落的 Carbon 用法收敛成语义组件，
 * 与 PF 的 FormGroup/FormSelect 用法一一对应，页面层保持同构。
 */

/** 面板容器（对应 PF Card / antd Card）：Tile + 标题行。 */
export function Panel({
  title,
  right,
  children,
  style,
}: {
  title?: ReactNode
  right?: ReactNode
  children: ReactNode
  style?: CSSProperties
}) {
  return (
    <Tile style={style}>
      {title ? (
        <div className="app-row" style={{ marginBottom: 12 }}>
          <h3 className="app-panel-title">{title}</h3>
          {right}
        </div>
      ) : null}
      {children}
    </Tile>
  )
}

export function NumField({
  id,
  label,
  value,
  onChange,
  min,
  max,
  step,
  width = 180,
  disabled,
  hideLabel,
}: {
  id: string
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  width?: number
  disabled?: boolean
  hideLabel?: boolean
}) {
  return (
    <div style={{ maxWidth: width, minWidth: width }}>
      <NumberInput
        id={id}
        label={label}
        hideLabel={hideLabel}
        value={Number.isFinite(value) ? value : 0}
        min={min}
        max={max}
        step={step}
        allowEmpty
        disabled={disabled}
        onChange={(_event, state) => {
          const n = Number(state.value)
          onChange(Number.isFinite(n) ? n : 0)
        }}
      />
    </div>
  )
}

export function BoolField({
  id,
  label,
  value,
  onChange,
  hint,
  disabled,
}: {
  id: string
  label: string
  value: boolean
  onChange: (v: boolean) => void
  hint?: string
  disabled?: boolean
}) {
  const t = useT()
  return (
    <div>
      <Toggle
        id={id}
        labelA={t('conn.off')}
        labelB={t('conn.on')}
        labelText={label}
        toggled={value}
        disabled={disabled}
        onToggle={onChange}
      />
      {hint ? <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginTop: 4 }}>{hint}</div> : null}
    </div>
  )
}

export function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
  width,
  disabled,
  hideLabel,
  min,
  max,
  step,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: 'text' | 'number' | 'password' | 'datetime-local'
  width?: number
  disabled?: boolean
  hideLabel?: boolean
  min?: number
  max?: number
  step?: number
}) {
  return (
    <div style={width ? { maxWidth: width, minWidth: width } : undefined}>
      <TextInput
        id={id}
        type={type}
        labelText={label}
        hideLabel={hideLabel}
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        min={type === 'number' ? min : undefined}
        max={type === 'number' ? max : undefined}
        step={type === 'number' ? step : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}

export interface SelectOption {
  value: string
  label: string
}

export function SelectField({
  id,
  label,
  value,
  options,
  onChange,
  disabled,
  width,
  hideLabel,
}: {
  id: string
  label: string
  value: string
  options: SelectOption[]
  onChange: (v: string) => void
  disabled?: boolean
  width?: number
  hideLabel?: boolean
}) {
  return (
    <div style={width ? { maxWidth: width, minWidth: width } : undefined}>
      <Select
        id={id}
        labelText={label}
        hideLabel={hideLabel}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange((event.target as HTMLSelectElement).value)}
      >
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value} text={o.label} />
        ))}
      </Select>
    </div>
  )
}

export function CheckField({
  id,
  label,
  checked,
  onChange,
  disabled,
}: {
  id: string
  label?: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <Checkbox
      id={id}
      labelText={label ?? ''}
      checked={checked}
      disabled={disabled}
      onChange={(_evt, data) => onChange(data.checked)}
    />
  )
}

/** 内联提示（对应 PF Alert / antd Alert）：kind 为语义色。 */
export function Note({
  kind,
  title,
  children,
  style,
}: {
  kind: 'success' | 'error' | 'warning' | 'info'
  title: string
  children?: ReactNode
  style?: CSSProperties
}) {
  return (
    <div style={style}>
      <InlineNotification kind={kind} title={title} lowContrast hideCloseButton>
        {children}
      </InlineNotification>
    </div>
  )
}

/**
 * 分页器：Carbon Pagination 的内置文案是英文，这里统一换成本地化字符串，
 * 三个分页页面共用同一形态。
 */
export function Pager({
  page,
  pageSize,
  totalItems,
  onChange,
}: {
  page: number
  pageSize: number
  totalItems: number
  onChange: (page: number) => void
}) {
  const t = useT()
  return (
    <Pagination
      page={page}
      pageSize={pageSize}
      totalItems={totalItems}
      onChange={({ page: next }) => onChange(next)}
      itemsPerPageText={t('common.perPage')}
      itemRangeText={(min, max, total) => t('common.itemRange', { min, max, total })}
      pageRangeText={(current, total) => t('common.pageRange', { current, total })}
      backwardText={t('common.prevPage')}
      forwardText={t('common.nextPage')}
    />
  )
}

export type TagTone = 'blue' | 'green' | 'gray' | 'red' | 'magenta' | 'cool-gray' | 'warm-gray'

/** 状态标签（对应 PF Label）：tone 已按浅/深主题校准，只用 Carbon 预设色。 */
export function ToneTag({ tone, children }: { tone: TagTone; children: ReactNode }) {
  return (
    <Tag size="sm" type={tone === 'gray' ? 'gray' : tone}>
      {children}
    </Tag>
  )
}

/** 统计卡（状态页四张）：Tile + 大数字。 */
export function Stat({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <Tile>
      <div className="app-stat-label">{label}</div>
      <div className="app-stat-value">
        {value}
        {unit ? <span className="app-stat-unit">{unit}</span> : null}
      </div>
    </Tile>
  )
}

/** 键值行（对应 PF DescriptionList / antd Descriptions 的紧凑形态）。 */
export function KvList({ items }: { items: { term: string; value: ReactNode }[] }) {
  return (
    <div className="app-kv">
      {items.map(({ term, value }) => (
        <div key={term} className="app-kv-row">
          <span className="app-kv-term">{term}</span>
          <span className="app-kv-value">{value}</span>
        </div>
      ))}
    </div>
  )
}

/** 表格外框（横向滚动 + Carbon 表格容器语义）。 */
export function TableFrame({ children, testid }: { children: ReactNode; testid?: string }) {
  return (
    <div className="app-table-scroll">
      <div className="cds--data-table-container">
        <div data-testid={testid}>{children}</div>
      </div>
    </div>
  )
}
