import { useEffect, useRef, useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Checkbox,
  Flex,
  Label,
} from '@patternfly/react-core'
import { useQueryClient } from '@tanstack/react-query'

import { PfLoadTestCard } from '../components/PfLoadTestCard'
import { api, testReportUrl } from '../../api/endpoints'
import { queryKeys, useTestScriptsQuery, useTestStatusQuery } from '../../api/queries'
import type { TestScriptInfo } from '../../api/types'
import { useT } from '../../i18n'

const STATUS_COLOR: Record<string, 'blue' | 'green' | 'red' | 'orange' | 'grey'> = {
  running: 'blue',
  passed: 'green',
  failed: 'red',
  stopped: 'orange',
  error: 'red',
}

const STATUS_KEY: Record<string, 'test.running' | 'test.passed' | 'test.failed' | 'test.stopped' | 'test.idle'> = {
  running: 'test.running',
  passed: 'test.passed',
  failed: 'test.failed',
  stopped: 'test.stopped',
  error: 'test.failed',
}

export function PfTestCenterPage() {
  const t = useT()
  const queryClient = useQueryClient()
  const scriptsQuery = useTestScriptsQuery()
  const statusQuery = useTestStatusQuery()
  const run = statusQuery.data?.run
  const running = Boolean(statusQuery.data?.running)
  const [selected, setSelected] = useState<string[]>([])
  const [last, setLast] = useState<string | null>(null)
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [run?.lines.length])

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.testStatus() })
  }

  const start = async (): Promise<void> => {
    try {
      const r = await api.tests.run(selected)
      setLast(r.ok ? t('test.started') : `${t('test.startFailed')}: ${r.error ?? ''}`)
    } catch (e) {
      setLast(`${t('test.startFailed')}: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      invalidate()
    }
  }

  const stop = async (): Promise<void> => {
    try {
      await api.tests.stop()
      setLast(t('test.stopped'))
    } finally {
      invalidate()
    }
  }

  const toggle = (id: string, checked: boolean): void => {
    setSelected((prev) => (checked ? [...new Set([...prev, id])] : prev.filter((s) => s !== id)))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <CardTitle>
          <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
            <span>{t('test.title')}</span>
            <Label isCompact color={run ? (STATUS_COLOR[run.status] ?? 'grey') : 'grey'}>
              {run ? t(STATUS_KEY[run.status] ?? 'test.idle') : t('test.idle')}
            </Label>
            {run?.summary ? (
              <Label isCompact color="blue">
                {t('test.summary', {
                  scripts: run.summary.scripts,
                  passed: run.summary.passed,
                  failed: run.summary.failed,
                })}
              </Label>
            ) : null}
          </Flex>
        </CardTitle>
        <CardBody>
          {last ? <div style={{ marginBottom: 8, fontSize: 13 }}>{last}</div> : null}
          <Flex gap={{ default: 'gapSm' }} style={{ marginBottom: 8 }}>
            <Button variant="primary" isDisabled={running || selected.length === 0} onClick={() => void start()}>
              {t('test.run')}
            </Button>
            <Button variant="danger" isDisabled={!running} onClick={() => void stop()}>
              {t('test.stop')}
            </Button>
          </Flex>
          <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>{t('test.desc')}</div>

          <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
            <thead className="pf-v6-c-table__thead">
              <tr className="pf-v6-c-table__tr">
                <th className="pf-v6-c-table__th" style={{ width: 48, minWidth: 48 }} />
                <th className="pf-v6-c-table__th" style={{ width: 220, minWidth: 220 }}>{t('test.name')}</th>
                <th className="pf-v6-c-table__th">{t('test.description')}</th>
                <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>{t('test.role')}</th>
                <th className="pf-v6-c-table__th" style={{ width: 110, minWidth: 110, textAlign: 'right' }}>{t('test.steps')}</th>
              </tr>
            </thead>
            <tbody className="pf-v6-c-table__tbody">
              {(scriptsQuery.data ?? []).map((script: TestScriptInfo) => (
                <tr key={script.id} className="pf-v6-c-table__tr" data-testid="test-script">
                  <td className="pf-v6-c-table__td">
                    <Checkbox
                      id={`pf-test-${script.id}`}
                      aria-label={script.name}
                      isChecked={selected.includes(script.id)}
                      onChange={(_e, checked) => toggle(script.id, checked)}
                    />
                  </td>
                  <td className="pf-v6-c-table__td">
                    {script.error ? <Label isCompact color="red">{script.name}</Label> : script.name}
                  </td>
                  <td className="pf-v6-c-table__td">{script.description}</td>
                  <td className="pf-v6-c-table__td">{script.role}</td>
                  <td className="pf-v6-c-table__td" style={{ textAlign: 'right' }}>{script.steps}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>{t('test.startHint')}</div>
        </CardBody>
      </Card>

<PfLoadTestCard />

            <Card>
        <CardTitle>{t('test.log')}</CardTitle>
        <CardBody>
          {run ? (
            <pre
              ref={logRef}
              className="mono"
              style={{
                maxHeight: 340,
                overflow: 'auto',
                margin: 0,
                padding: 8,
                background: 'var(--pf-t--global--background--color--secondary--default)',
                fontSize: 12,
                lineHeight: 1.5,
              }}
            >
              {run.lines.join('\n')}
            </pre>
          ) : (
            <div style={{ opacity: 0.7 }}>{t('test.noRun')}</div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardTitle>{t('test.reports')}</CardTitle>
        <CardBody>
          {run && run.reports.length > 0 ? (
            <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
              <thead className="pf-v6-c-table__thead">
                <tr className="pf-v6-c-table__tr">
                  <th className="pf-v6-c-table__th">{t('test.reportName')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 100, minWidth: 100 }}>{t('test.format')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 110, minWidth: 110, textAlign: 'right' }}>{t('cap.size')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 110, minWidth: 110 }}>{t('cap.actions')}</th>
                </tr>
              </thead>
              <tbody className="pf-v6-c-table__tbody">
                {run.reports.map((report) => (
                  <tr key={report.name} className="pf-v6-c-table__tr">
                    <td className="pf-v6-c-table__td">{report.name}</td>
                    <td className="pf-v6-c-table__td">{report.format}</td>
                    <td className="pf-v6-c-table__td" style={{ textAlign: 'right' }}>{report.size}</td>
                    <td className="pf-v6-c-table__td">
                      <Button
                        variant="link"
                        size="sm"
                        component="a"
                        href={testReportUrl(run.id, report.name)}
                        download
                      >
                        {t('cap.download')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ opacity: 0.7 }}>{t('test.noReports')}</div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
