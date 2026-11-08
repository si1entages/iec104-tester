import { useEffect, useRef, useState } from 'react'

import { Button, Checkbox, Link, Tag } from '@carbon/react'
import { useQueryClient } from '@tanstack/react-query'

import { api, testReportUrl } from '../../api/endpoints'
import { queryKeys, useTestScriptsQuery, useTestStatusQuery } from '../../api/queries'
import type { TestScriptInfo } from '../../api/types'
import { useT } from '../../i18n'
import { Panel, TableFrame } from '../components/ui'

const STATUS_TONE: Record<string, 'blue' | 'green' | 'red' | 'magenta' | 'gray'> = {
  running: 'blue',
  passed: 'green',
  failed: 'red',
  stopped: 'magenta',
  error: 'red',
}

const STATUS_KEY: Record<string, 'test.running' | 'test.passed' | 'test.failed' | 'test.stopped' | 'test.idle'> = {
  running: 'test.running',
  passed: 'test.passed',
  failed: 'test.failed',
  stopped: 'test.stopped',
  error: 'test.failed',
}

export function CarbonTestCenterPage() {
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
    <div className="app-gap">
      <Panel
        title={
          <span className="app-row">
            {t('test.title')}
            <Tag size="sm" type={run ? (STATUS_TONE[run.status] ?? 'gray') : 'gray'}>
              {run ? t(STATUS_KEY[run.status] ?? 'test.idle') : t('test.idle')}
            </Tag>
            {run?.summary ? (
              <Tag size="sm" type="blue">
                {t('test.summary', {
                  scripts: run.summary.scripts,
                  passed: run.summary.passed,
                  failed: run.summary.failed,
                })}
              </Tag>
            ) : null}
          </span>
        }
      >
        {last ? <div style={{ marginBottom: 8, fontSize: 13 }}>{last}</div> : null}
        <div className="app-row" style={{ marginBottom: 8 }}>
          <Button kind="primary" disabled={running || selected.length === 0} onClick={() => void start()}>
            {t('test.run')}
          </Button>
          <Button kind="danger" disabled={!running} onClick={() => void stop()}>
            {t('test.stop')}
          </Button>
        </div>
        <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>{t('test.desc')}</div>

        <TableFrame>
          <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
            <thead>
              <tr>
                <th style={{ width: 48, minWidth: 48 }} />
                <th style={{ width: 220, minWidth: 220 }}><span className="cds--table-header-label">{t('test.name')}</span></th>
                <th><span className="cds--table-header-label">{t('test.description')}</span></th>
                <th style={{ width: 90, minWidth: 90 }}><span className="cds--table-header-label">{t('test.role')}</span></th>
                <th style={{ width: 110, minWidth: 110, textAlign: 'right' }}><span className="cds--table-header-label">{t('test.steps')}</span></th>
              </tr>
            </thead>
            <tbody>
              {(scriptsQuery.data ?? []).map((script: TestScriptInfo) => (
                <tr key={script.id} data-testid="test-script">
                  <td>
                    <Checkbox
                      id={`cb-test-${script.id}`}
                      labelText=""
                      aria-label={script.name}
                      checked={selected.includes(script.id)}
                      onChange={(_evt, data) => toggle(script.id, data.checked)}
                    />
                  </td>
                  <td>
                    {script.error ? <Tag size="sm" type="red">{script.name}</Tag> : script.name}
                  </td>
                  <td>{script.description}</td>
                  <td>{script.role}</td>
                  <td style={{ textAlign: 'right' }}>{script.steps}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableFrame>
        <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>{t('test.startHint')}</div>
      </Panel>

      <Panel title={t('test.log')}>
        {run ? (
          <pre ref={logRef} className="mono app-log">
            {run.lines.join('\n')}
          </pre>
        ) : (
          <div style={{ opacity: 0.7 }}>{t('test.noRun')}</div>
        )}
      </Panel>

      <Panel title={t('test.reports')}>
        {run && run.reports.length > 0 ? (
          <TableFrame>
            <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
              <thead>
                <tr>
                  <th><span className="cds--table-header-label">{t('test.reportName')}</span></th>
                  <th style={{ width: 100, minWidth: 100 }}><span className="cds--table-header-label">{t('test.format')}</span></th>
                  <th style={{ width: 110, minWidth: 110, textAlign: 'right' }}><span className="cds--table-header-label">{t('cap.size')}</span></th>
                  <th style={{ width: 110, minWidth: 110 }}><span className="cds--table-header-label">{t('cap.actions')}</span></th>
                </tr>
              </thead>
              <tbody>
                {run.reports.map((report) => (
                  <tr key={report.name}>
                    <td>{report.name}</td>
                    <td>{report.format}</td>
                    <td style={{ textAlign: 'right' }}>{report.size}</td>
                    <td>
                      <Link href={testReportUrl(run.id, report.name)} download>
                        {t('cap.download')}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
        ) : (
          <div style={{ opacity: 0.7 }}>{t('test.noReports')}</div>
        )}
      </Panel>
    </div>
  )
}
