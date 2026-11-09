import { Tag } from '@carbon/react'

import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'

/** Carbon Tag type 与品质位的语义映射（IV 最重 → 红；BL 最轻 → 灰）。 */
const FLAGS: Record<
  string,
  { type: 'red' | 'blue' | 'magenta' | 'purple' | 'cool-gray' | 'warm-gray'; key: MessageKey }
> = {
  IV: { type: 'red', key: 'quality.iv' },
  NT: { type: 'warm-gray', key: 'quality.nt' },
  SB: { type: 'blue', key: 'quality.sb' },
  BL: { type: 'cool-gray', key: 'quality.bl' },
  OV: { type: 'magenta', key: 'quality.ov' },
}

const MAX_VISIBLE = 2

/** Carbon 版品质标签（§5.4）：中文标签 + 语义色 + tooltip，最多 2 个，其余 `+N`。 */
export function CarbonQualityTags({ quality }: { quality?: string }) {
  const t = useT()
  const text = (quality ?? '').trim()
  if (!text || text === 'GOOD') return <span style={{ color: 'var(--cds-text-secondary)' }}>-</span>

  const flags = text
    .split('|')
    .map((s) => s.trim())
    .filter(Boolean)
  const known = flags.filter((f) => FLAGS[f])
  const unknown = flags.filter((f) => !FLAGS[f])
  const visible = known.slice(0, MAX_VISIBLE)
  const hidden = known.length - visible.length + unknown.length
  const tip = t('quality.tip', {
    flags: flags.map((f) => (FLAGS[f] ? `${f} ${t(FLAGS[f].key)}` : f)).join(' · '),
  })

  return (
    <span title={tip} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      {visible.map((f) => (
        <Tag key={f} size="sm" type={FLAGS[f].type}>
          {t(FLAGS[f].key)}
        </Tag>
      ))}
      {hidden > 0 ? <span style={{ color: 'var(--cds-text-secondary)', fontSize: 12 }}>+{hidden}</span> : null}
    </span>
  )
}
