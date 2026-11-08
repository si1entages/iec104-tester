import { Card, CardBody, CardTitle, PageSection, Title } from '@patternfly/react-core'

import { useT } from '../../i18n'

/** 尚未迁移的页面占位：明确说明当前状态，避免空白页。 */
export function PfPlaceholder() {
  const t = useT()
  return (
    <PageSection>
      <Card>
        <CardTitle>{t('pf.wip')}</CardTitle>
        <CardBody>
          <Title headingLevel="h3" size="md" style={{ marginBottom: 8 }}>
            {t('pf.wipDesc')}
          </Title>
        </CardBody>
      </Card>
    </PageSection>
  )
}
