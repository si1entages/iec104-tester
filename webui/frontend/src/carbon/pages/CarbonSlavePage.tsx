import { useState } from 'react'

import { Tab, TabList, TabPanel, TabPanels, Tabs } from '@carbon/react'

import { useStatusQuery } from '../../api/queries'
import type { Point } from '../../api/types'
import { useT } from '../../i18n'
import { CarbonFrameViewer } from '../components/CarbonFrameViewer'
import { CarbonManualSetPanel } from '../components/CarbonManualSetPanel'
import { CarbonPointsImport } from '../components/CarbonPointsImport'
import { CarbonPointsTable } from '../components/CarbonPointsTable'
import { CarbonResponsePanel } from '../components/CarbonResponsePanel'
import { CarbonSimulationPanel } from '../components/CarbonSimulationPanel'
import { CarbonSlaveConnectionPanel } from '../components/CarbonSlaveConnectionPanel'
import { CarbonTestInjectionPanel } from '../components/CarbonTestInjectionPanel'
import { Panel } from '../components/ui'

/** 子站工作台：启动/客户端 → 点表 + 手动置数/应答行为/模拟控制/测试注入 → 报文。 */
export function CarbonSlavePage() {
  const t = useT()
  const { data: status } = useStatusQuery()
  const disabled = !status?.running
  const [selected, setSelected] = useState<Point | null>(null)
  const [tab, setTab] = useState(0)

  return (
    <div className="app-gap">
      <CarbonSlaveConnectionPanel />

      <Panel title={t('pt2.title')} right={<CarbonPointsImport />}>
        <CarbonPointsTable
          selected={selected}
          onSelect={setSelected}
          height={520}
          selectHint={t('slave.selectHint')}
        />
      </Panel>

      <Tabs selectedIndex={tab} onChange={({ selectedIndex }) => setTab(selectedIndex)}>
        <TabList aria-label={t('slave.tab.manual')}>
          <Tab>{t('slave.tab.manual')}</Tab>
          <Tab>{t('slave.tab.response')}</Tab>
          <Tab>{t('slave.tab.sim')}</Tab>
          <Tab>{t('slave.tab.inject')}</Tab>
        </TabList>
        <TabPanels>
          <TabPanel>
            <div style={{ marginTop: 12 }}>
              <CarbonManualSetPanel point={selected} disabled={disabled} />
            </div>
          </TabPanel>
          <TabPanel>
            <div style={{ marginTop: 12 }}>
              <CarbonResponsePanel disabled={disabled} />
            </div>
          </TabPanel>
          <TabPanel>
            <div style={{ marginTop: 12 }}>
              <CarbonSimulationPanel selected={selected} disabled={disabled} />
            </div>
          </TabPanel>
          <TabPanel>
            <div style={{ marginTop: 12 }}>
              <CarbonTestInjectionPanel disabled={disabled} />
            </div>
          </TabPanel>
        </TabPanels>
      </Tabs>

      <CarbonFrameViewer />
    </div>
  )
}
