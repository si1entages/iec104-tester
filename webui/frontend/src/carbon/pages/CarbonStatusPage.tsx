import { Button, Select, SelectItem, TextInput } from '@carbon/react'

import { useUiStore } from '../../store/uiStore'
import { useState } from 'react'

import { reportDownloadUrl } from '../../api/endpoints'
import { usePointsQuery, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'
import { CarbonAlarmCard } from '../components/CarbonAlarmCard'
import { CarbonNetworkSimCard } from '../components/CarbonNetworkSimCard'
import { CarbonPointsTable } from '../components/CarbonPointsTable'
import { CarbonLinkStatsCard } from '../components/CarbonLinkStatsCard'
import { CarbonProfilesCard } from '../components/CarbonProfilesCard'
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
    {
      term: 'status.asduAddress',
      value: status?.asdu_address
        ? `${status.asdu_address.ca_length}/${status.asdu_address.ioa_length}/${status.asdu_address.cot_length} B`
        : '-',
    },
  ]

  const [conclusionKind, setConclusionKind] = useState('')
  const [conclusionNote, setConclusionNote] = useState('')
  const conclusionTexts: Record<string, string> = {
    pass: t('status.reportConclusionPass'),
    fail: t('status.reportConclusionFail'),
    conditional: t('status.reportConclusionConditional'),
  }
  const chartSnapshots = useUiStore((s) => s.chartSnapshots)
  const exportReport = async (): Promise<void> => {
    const conclusion = conclusionKind
      ? conclusionTexts[conclusionKind] + (conclusionNote ? `：${conclusionNote}` : '')
      : ''
    // POST 报告（T87：曲线快照 base64 放 GET query 会超长）→ Blob 打开
    try {
      const res = await fetch('/api/export/report.html', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
        title: t('status.exportReportTitle', { role: status?.role ?? '-' }),
        conclusion,
        conclusion_kind: conclusionKind,
          chart_images: chartSnapshots,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const text = await res.text()
      const blob = new Blob([text], { type: 'text/html;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const win = window.open(url, '_blank')
      if (!win) URL.revokeObjectURL(url)
      else setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch {
      // 网络失败降级为 GET（无曲线快照）
      window.open(
        `/api/export/report.html?${new URLSearchParams({
          title: t('status.exportReportTitle', { role: status?.role ?? '-' }),
          conclusion, conclusion_kind: conclusionKind,
        }).toString()}`,
        '_blank',
      )
    }
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
          onClick={() => void exportReport()}
          title={t('status.exportReportHint')}
        >
          {t('status.exportReport')}
        </Button>
        {/* WP8：原生 xlsx / PDF（PDF 需后端 report[pdf] extra，缺失时后端返回可读错误） */}
        <Button kind="ghost" size="sm" data-testid="export-report-xlsx"
          title={t('status.exportReportXlsxHint')}
          onClick={() => { window.location.href = reportDownloadUrl('xlsx') }}>
          {t('status.exportReportXlsx')}
        </Button>
        <Button kind="ghost" size="sm" data-testid="export-report-pdf"
          title={t('status.exportReportPdfHint')}
          onClick={() => { window.location.href = reportDownloadUrl('pdf') }}>
          {t('status.exportReportPdf')}
        </Button>
      </div>
      <div className="app-tiles">
        <Stat label={t('status.points')} value={String(status?.points ?? points.length)} unit={t('status.unit.points')} />
        <Stat label={t('status.tx')} value={String(status?.tx ?? 0)} unit={t('status.unit.frames')} />
        <Stat label={t('status.rx')} value={String(status?.rx ?? 0)} unit={t('status.unit.frames')} />
        <Stat label={t('status.dropped')} value={String(status?.dropped ?? 0)} unit={t('status.unit.frames')} />
      </div>

      {/* T98：告警评估与网络模拟依赖引擎，bridge 角色不渲染（端点未注册）；
          角色未知（status 未加载）时也不渲染——否则首帧闪现会轮询 404 */}
      {status && status.role !== 'bridge' ? <CarbonAlarmCard /> : null}

      {status && status.role !== 'bridge' ? <CarbonNetworkSimCard /> : null}

      <Panel title={t('status.runtime')}>
        <KvList items={runtime.map(({ term, value }) => ({ term: t(term), value }))} />
      </Panel>

      {/* WP6：链路参数可观测（bridge 角色无 104 引擎，不渲染） */}
      {status && status.role !== 'bridge' ? <CarbonLinkStatsCard status={status} /> : null}

      <Panel title={t('pt2.title')}>
        <CarbonPointsTable height={420} />
      </Panel>

      {/* WP5：工程配置方案——bridge 角色无连接参数，不渲染 */}
      {status && status.role !== 'bridge' ? <CarbonProfilesCard /> : null}
    </div>
  )
}
