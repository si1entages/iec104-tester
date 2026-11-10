import { useState } from 'react'

import {
  Card,
  CardBody,
  CardTitle,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Flex,
  FlexItem,
  PageSection,
  Title,
} from '@patternfly/react-core'

import {
  Button,
  FormSelect,
  FormSelectOption,
  TextInput,
} from '@patternfly/react-core'

import { useUiStore } from '../../store/uiStore'
import { usePointsQuery, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'
import { PfAlarmCard } from '../components/PfAlarmCard'
import { PfNetworkSimCard } from '../components/PfNetworkSimCard'
import { PfPointsTable } from '../components/PfPointsTable'

function Stat({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <Card isCompact>
      <CardTitle>{label}</CardTitle>
      <CardBody>
        <Title headingLevel="h2" size="3xl">
          {value}
          {unit ? (
            <span style={{ fontSize: '0.5em', marginInlineStart: 6, opacity: 0.7 }}>{unit}</span>
          ) : null}
        </Title>
      </CardBody>
    </Card>
  )
}

export function PfStatusPage() {
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
    <>
      <PageSection variant="secondary">
        <Flex justifyContent={{ default: 'justifyContentFlexEnd' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          <FormSelect
            id="pf-status-conclusion"
            aria-label={t('status.reportConclusion')}
            value={conclusionKind}
            onChange={(_e, v) => setConclusionKind(v)}
          >
            <FormSelectOption value="" label={t('status.reportConclusionNone')} />
            <FormSelectOption value="pass" label={t('status.reportConclusionPass')} />
            <FormSelectOption value="fail" label={t('status.reportConclusionFail')} />
            <FormSelectOption value="conditional" label={t('status.reportConclusionConditional')} />
          </FormSelect>
          <TextInput
            id="pf-status-conclusion-note"
            aria-label={t('status.reportConclusionNote')}
            placeholder={t('status.reportConclusionNote')}
            value={conclusionNote}
            onChange={(_e, v) => setConclusionNote(v)}
          />
          <Button variant="secondary" data-testid="export-report"
                  onClick={() => void exportReport()} title={t('status.exportReportHint')}>
            {t('status.exportReport')}
          </Button>
        </Flex>
      </PageSection>
      <PageSection variant="secondary">
        <Flex gap={{ default: 'gapMd' }} flexWrap={{ default: 'wrap' }}>
          <FlexItem flex={{ default: 'flex_1' }}>
            <Stat label={t('status.points')} value={String(status?.points ?? points.length)} unit={t('status.unit.points')} />
          </FlexItem>
          <FlexItem flex={{ default: 'flex_1' }}>
            <Stat label={t('status.tx')} value={String(status?.tx ?? 0)} unit={t('status.unit.frames')} />
          </FlexItem>
          <FlexItem flex={{ default: 'flex_1' }}>
            <Stat label={t('status.rx')} value={String(status?.rx ?? 0)} unit={t('status.unit.frames')} />
          </FlexItem>
          <FlexItem flex={{ default: 'flex_1' }}>
            <Stat label={t('status.dropped')} value={String(status?.dropped ?? 0)} unit={t('status.unit.frames')} />
          </FlexItem>
        </Flex>
      </PageSection>

      {/* T98：告警评估与网络模拟依赖引擎，bridge 角色不渲染（端点未注册，避免轮询 404） */}
      {status?.role !== 'bridge' ? (
        <PageSection>
          <PfAlarmCard />

          <PfNetworkSimCard />
        </PageSection>
      ) : null}

      <PageSection>
        <Card>
          <CardTitle>{t('status.runtime')}</CardTitle>
          <CardBody>
            <DescriptionList isHorizontal columnModifier={{ default: '3Col' }}>
              {runtime.map(({ term, value }) => (
                <DescriptionListGroup key={term}>
                  <DescriptionListTerm>{t(term)}</DescriptionListTerm>
                  <DescriptionListDescription>{value}</DescriptionListDescription>
                </DescriptionListGroup>
              ))}
            </DescriptionList>
          </CardBody>
        </Card>
      </PageSection>

      <PageSection>
        <Card>
          <CardTitle>{t('pt2.title')}</CardTitle>
          <CardBody>
            <PfPointsTable height={420} />
          </CardBody>
        </Card>
      </PageSection>
    </>
  )
}
