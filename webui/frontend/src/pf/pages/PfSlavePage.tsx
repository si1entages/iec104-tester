import { useState } from 'react'

import { Card, CardBody, PageSection, Tab, Tabs } from '@patternfly/react-core'

import { useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { useT } from '../../i18n'
import { PfFrameViewer } from '../components/PfFrameViewer'
import { PfManualSetPanel } from '../components/PfManualSetPanel'
import { PfPointsTable } from '../components/PfPointsTable'
import { PfResponsePanel } from '../components/PfResponsePanel'
import { PfSimulationPanel } from '../components/PfSimulationPanel'
import { PfSlaveConnectionPanel } from '../components/PfSlaveConnectionPanel'
import { PfTestInjectionPanel } from '../components/PfTestInjectionPanel'

/** 子站工作台：启动/客户端 → 点表 + 手动置数/应答行为/模拟控制/测试注入 → 报文。 */
export function PfSlavePage() {
  const t = useT()
  const { data: status } = useStatusQuery()
  const disabled = !status?.running
  const [selected, setSelected] = useState<Point | null>(null)
  const [tab, setTab] = useState<string | number>('manual')

  return (
    <>
      <PageSection variant="secondary">
        <PfSlaveConnectionPanel />
      </PageSection>

      <PageSection>
        <Card>
          <CardBody>
            <PfPointsTable selected={selected} onSelect={setSelected} height={520} selectHint={t('slave.selectHint')} />
          </CardBody>
        </Card>

        <div style={{ marginTop: 16 }}>
          <Tabs activeKey={tab} onSelect={(_event, key) => setTab(key)}>
            <Tab eventKey="manual" title={t('slave.tab.manual')}>
              <div style={{ marginTop: 12 }}>
                <PfManualSetPanel point={selected} disabled={disabled} />
              </div>
            </Tab>
            <Tab eventKey="response" title={t('slave.tab.response')}>
              <div style={{ marginTop: 12 }}>
                <PfResponsePanel disabled={disabled} />
              </div>
            </Tab>
            <Tab eventKey="sim" title={t('slave.tab.sim')}>
              <div style={{ marginTop: 12 }}>
                <PfSimulationPanel selected={selected} disabled={disabled} />
              </div>
            </Tab>
            <Tab eventKey="inject" title={t('slave.tab.inject')}>
              <div style={{ marginTop: 12 }}>
                <PfTestInjectionPanel disabled={disabled} />
              </div>
            </Tab>
          </Tabs>
        </div>
      </PageSection>

      <PageSection>
        <PfFrameViewer />
      </PageSection>
    </>
  )
}
