import { FormGroup, Switch, TextInput } from '@patternfly/react-core'

/** PF 数字输入（原生 number 输入，保持可控与整数/小数输入体验）。 */
export function NumField({
  id,
  label,
  value,
  onChange,
  min,
  max,
  step,
  width = 170,
}: {
  id: string
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  width?: number
}) {
  return (
    <FormGroup label={label} fieldId={id} style={{ maxWidth: width }}>
      <TextInput
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={String(value)}
        onChange={(_event, v) => {
          const n = Number(v)
          onChange(Number.isFinite(n) ? n : 0)
        }}
      />
    </FormGroup>
  )
}

/** PF 布尔开关（带标签的 Switch）。 */
export function BoolField({
  id,
  label,
  value,
  onChange,
  hint,
}: {
  id: string
  label: string
  value: boolean
  onChange: (v: boolean) => void
  hint?: string
}) {
  return (
    <FormGroup label={label} fieldId={id}>
      <Switch
        id={id}
        aria-label={label}
        isChecked={value}
        onChange={(_event, checked) => onChange(checked)}
      />
      {hint ? <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>{hint}</div> : null}
    </FormGroup>
  )
}
