import { Button, Select, SelectItem, TextInput } from '@carbon/react'

import { exportReportUrl } from '../../api/endpoints'
import { useState } from 'react'

import { usePointsQuery, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'
import { CarbonNetworkSimCard } from '../components/CarbonNetworkSimCard'
import { CarbonPointsTable } from '../components/CarbonPointsTable'
import { KvList, Panel, Stat } from '../components/ui'

export function CarbonStatusPage() {
  const t = useT()
  const { data: status } = useStatusQuery()
  const { data: points = [] } = usePointsQuery()

  const runtime: { term: MessageKey; value: string }[] = [
    { term: 'status.host', value: status?.host ?? '-' },
    { term: 'status.port', value: String(status?.port ?? '-') },
    { term: 'status.addr', value: String(status?.addr ?? '-') },
    { term: 'conn.vsVr', value: `${status?.vs ?? '-'} / ${status?.vr ?? '-'}` },
    { term: 'conn.window', value: status?.window ?? '-' },
  ]

  const [conclusionKind, setConclusionKind] = useState('')
  const [conclusionNote, setConclusionNote] = useState('')
  const conclusionTexts: Record<string, string> = {
    pass: t('status.reportConclusionPass'),
    fail: t('status.reportConclusionFail'),
    conditional: t('status.reportConclusionConditional'),
  }
  const exportReport = (): void => {
    const conclusion = conclusionKind
      ? conclusionTexts[conclusionKind] + (conclusionNote ? `：${conclusionNote}` : '')
      : ''
    window.open(
      exportReportUrl(t('status.exportReportTitle', { role: status?.role ?? '-' }), {
        conclusion,
        conclusion_kind: conclusionKind,
      }),
      '_blank',
    )
  }

  return (
    <div className="app-gap">
      <div className="app-row" style={{ justifyContent: 'flex-end', alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ width: 150, minWidth: 150 }}>
          <Select
            id="cb-status-conclusion"
            labelText={t('status.reportConclusion')}
            hideLabel
            value={conclusionKind}
            onChange={(event) => setConclusionKind((event.target as HTMLSelectElement).value)}
          >
            <SelectItem value="" text={t('status.reportConclusionNone')} />
            <SelectItem value="pass" text={t('status.reportConclusionPass')} />
            <SelectItem value="fail" text={t('status.reportConclusionFail')} />
            <SelectItem value="conditional" text={t('status.reportConclusionConditional')} />
          </Select>
        </div>
        <div style={{ width: 220, minWidth: 220 }}>
          <TextInput
            id="cb-status-conclusion-note"
            type="text"
            labelText={t('status.reportConclusionNote')}
            hideLabel
            placeholder={t('status.reportConclusionNote')}
            value={conclusionNote}
            onChange={(event) => setConclusionNote(event.target.value)}
          />
        </div>
        <Button
          kind="secondary"
          size="sm"
          data-testid="export-report"
          onClick={exportReport}
          title={t('status.exportReportHint')}
        >
          {t('status.exportReport')}
        </Button>
      </div>
      <div className="app-tiles">
        <Stat label={t('status.points')} value={String(status?.points ?? points.length)} unit={t('status.unit.points')} />
        <Stat label={t('status.tx')} value={String(status?.tx ?? 0)} unit={t('status.unit.frames')} />
        <Stat label={t('status.rx')} value={String(status?.rx ?? 0)} unit={t('status.unit.frames')} />
        <Stat label={t('status.dropped')} value={String(status?.dropped ?? 0)} unit={t('status.unit.frames')} />
      </div>

      <CarbonNetworkSimCard />

      <Panel title={t('status.runtime')}>
        <KvList items={runtime.map(({ term, value }) => ({ term: t(term), value }))} />
      </Panel>

      <Panel title={t('pt2.title')}>
        <CarbonPointsTable height={420} />
      </Panel>
    </div>
  )
}
