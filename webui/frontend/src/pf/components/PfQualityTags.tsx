import { Label, Tooltip } from '@patternfly/react-core'

import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'

const FLAGS: Record<string, { color: 'red' | 'orange' | 'grey'; key: MessageKey }> = {
  IV: { color: 'red', key: 'quality.iv' },
  NT: { color: 'orange', key: 'quality.nt' },
  SB: { color: 'orange', key: 'quality.sb' },
  BL: { color: 'grey', key: 'quality.bl' },
  OV: { color: 'orange', key: 'quality.ov' },
}

const MAX_VISIBLE = 2

/** PF 版品质标签（§5.4）：中文标签 + 语义色 + tooltip，最多 2 个，其余 `+N`。 */
export function PfQualityTags({ quality }: { quality?: string }) {
  const t = useT()
  const text = (quality ?? '').trim()
  if (!text || text === 'GOOD') return <span style={{ opacity: 0.6 }}>-</span>

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
    <Tooltip content={tip}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {visible.map((f) => (
          <Label key={f} isCompact color={FLAGS[f].color}>
            {t(FLAGS[f].key)}
          </Label>
        ))}
        {hidden > 0 ? <span style={{ opacity: 0.65, fontSize: 12 }}>+{hidden}</span> : null}
      </span>
    </Tooltip>
  )
}
