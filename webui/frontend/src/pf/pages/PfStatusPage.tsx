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

import { Button } from '@patternfly/react-core'

import { exportReportUrl } from '../../api/endpoints'
import { usePointsQuery, useStatusQuery } from '../../api/queries'
import { useT } from '../../i18n'
import type { MessageKey } from '../../i18n'
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

  const exportReport = (): void => {
    window.open(exportReportUrl(t('status.exportReportTitle', { role: status?.role ?? '-' })), '_blank')
  }

  return (
    <>
      <PageSection variant="secondary">
        <Flex justifyContent={{ default: 'justifyContentFlexEnd' }}>
          <Button variant="secondary" data-testid="export-report"
                  onClick={exportReport} title={t('status.exportReportHint')}>
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

      <PageSection>
        <PfNetworkSimCard />
      </PageSection>

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
