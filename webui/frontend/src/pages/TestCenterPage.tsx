import { useEffect, useRef, useState } from 'react'

import { ExperimentOutlined, PlayCircleOutlined, StopOutlined } from '@ant-design/icons'
import { App as AntdApp, Button, Card, Empty, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useQueryClient } from '@tanstack/react-query'

import { api, testReportUrl } from '../api/endpoints'
import { queryKeys, useTestScriptsQuery, useTestStatusQuery } from '../api/queries'
import type { TestReportInfo, TestScriptInfo } from '../api/types'
import { useT } from '../i18n'
import type { MessageKey } from '../i18n'

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

const STATUS_COLOR: Record<string, string> = {
  running: 'processing',
  passed: 'success',
  failed: 'error',
  stopped: 'warning',
  error: 'error',
}

const STATUS_KEY: Record<string, MessageKey> = {
  running: 'test.running',
  passed: 'test.passed',
  failed: 'test.failed',
  stopped: 'test.stopped',
  error: 'test.error',
}

function scriptColumns(t: TFn): TableColumnsType<TestScriptInfo> {
  return [
    { title: t('test.name'), dataIndex: 'name', width: 220, render: (v: string, row) => row.error ? <Tag color="error">{v}</Tag> : v },
    { title: t('test.description'), dataIndex: 'description', ellipsis: true },
    { title: t('test.role'), dataIndex: 'role', width: 100 },
    { title: t('test.steps'), dataIndex: 'steps', width: 90 },
    { title: 'YAML', dataIndex: 'id', width: 260, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
  ]
}

function reportColumns(t: TFn, runId: string): TableColumnsType<TestReportInfo> {
  return [
    { title: t('test.reportName'), dataIndex: 'name' },
    { title: t('test.format'), dataIndex: 'format', width: 90 },
    {
      title: t('test.download'),
      key: 'download',
      width: 120,
      render: (_, row) => (
        <Button size="small" href={testReportUrl(runId, row.name)} download>
          {t('test.download')}
        </Button>
      ),
    },
  ]
}

export function TestCenterPage() {
  const t = useT()
  const { message } = AntdApp.useApp()
  const queryClient = useQueryClient()
  const scriptsQuery = useTestScriptsQuery()
  const statusQuery = useTestStatusQuery()
  const run = statusQuery.data?.run
  const running = Boolean(statusQuery.data?.running)
  const [selected, setSelected] = useState<string[]>([])
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [run?.lines.length])

  const invalidate = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.testStatus })
  }

  const start = async (): Promise<void> => {
    try {
      const r = await api.tests.run(selected)
      if (r.ok) message.success(t('test.started'))
      else message.error(r.error ?? t('common.failed'))
      invalidate()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const stop = async (): Promise<void> => {
    try {
      const r = await api.tests.stop()
      if (!r.ok) message.error(r.error ?? t('common.failed'))
      invalidate()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card
        size="small"
        title={
          <Space size={4} wrap>
            <ExperimentOutlined />
            <span>{t('test.title')}</span>
            <Tag color={run ? STATUS_COLOR[run.status] : 'default'}>
              {run ? t(STATUS_KEY[run.status] ?? 'test.idle') : t('test.idle')}
            </Tag>
            {run?.summary ? (
              <Tag color="blue">
                {t('test.summary', {
                  scripts: run.summary.scripts,
                  passed: run.summary.passed,
                  failed: run.summary.failed,
                })}
              </Tag>
            ) : null}
          </Space>
        }
        extra={
          <Space>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              disabled={running || selected.length === 0}
              onClick={() => void start()}
            >
              {t('test.run')}
            </Button>
            <Button danger icon={<StopOutlined />} disabled={!running} onClick={() => void stop()}>
              {t('test.stop')}
            </Button>
          </Space>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          {t('test.desc')}
        </Typography.Paragraph>
        <Table<TestScriptInfo>
          rowKey="id"
          size="small"
          columns={scriptColumns(t)}
          dataSource={scriptsQuery.data ?? []}
          loading={scriptsQuery.isFetching}
          rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys as string[]) }}
          pagination={false}
          scroll={{ x: 900, y: 300 }}
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
          {t('test.startHint')}
        </Typography.Paragraph>
      </Card>

      <Card size="small" title={t('test.log')}>
        {run ? (
          <pre
            ref={logRef}
            style={{
              maxHeight: 340,
              overflow: 'auto',
              margin: 0,
              padding: 8,
              background: 'rgba(0,0,0,0.04)',
              fontSize: 12,
              lineHeight: 1.5,
            }}
          >
            {run.lines.join('\n')}
          </pre>
        ) : (
          <Empty description={t('test.noRun')} />
        )}
      </Card>

      <Card size="small" title={t('test.reports')}>
        {run ? (
          <Table<TestReportInfo>
            rowKey="name"
            size="small"
            columns={reportColumns(t, run.id)}
            dataSource={run.reports}
            pagination={false}
            locale={{ emptyText: t('test.noRun') }}
          />
        ) : (
          <Empty description={t('test.noRun')} />
        )}
      </Card>
    </div>
  )
}
