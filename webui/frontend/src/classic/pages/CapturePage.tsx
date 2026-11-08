import { useState } from 'react'

import {
  CameraOutlined,
  DownloadOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  StepBackwardOutlined,
  StepForwardOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { App as AntdApp, Button, Card, InputNumber, Progress, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useQueryClient } from '@tanstack/react-query'

import { api, captureDownloadUrl } from '../api/endpoints'
import { useCaptureFramesQuery, useCaptureStatusQuery, queryKeys } from '../api/queries'
import type { CaptureFileInfo, CaptureFrame } from '../api/types'
import { useT } from '../i18n'
import type { MessageKey } from '../i18n'

type TFn = (key: MessageKey, params?: Record<string, string | number>) => string

const PAGE_SIZE = 100

function formatBytes(n: number): string {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(ts: number): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}

function fileColumns(t: TFn, onLoad: (name: string) => void, onExport: (name: string) => void): TableColumnsType<CaptureFileInfo> {
  return [
    { title: t('cap.name'), dataIndex: 'name', ellipsis: true },
    { title: t('cap.size'), dataIndex: 'size', width: 110, render: (v: number) => formatBytes(v) },
    { title: t('cap.time'), dataIndex: 'mtime', width: 190, render: (v: number) => formatTime(v) },
    {
      title: t('cap.actions'),
      key: 'actions',
      width: 300,
      render: (_, row) => (
        <Space size={4} wrap>
          <Button size="small" onClick={() => onLoad(row.name)}>{t('cap.load')}</Button>
          <Button size="small" icon={<DownloadOutlined />} href={captureDownloadUrl(row.name)} download>
            {t('cap.download')}
          </Button>
          <Button size="small" onClick={() => onExport(row.name)}>{t('cap.exportPcap')}</Button>
        </Space>
      ),
    },
  ]
}

function frameColumns(t: TFn): TableColumnsType<CaptureFrame> {
  return [
    { title: t('cap.frameTime'), dataIndex: 'timestamp', width: 130, render: (v: number) => v.toFixed(3) },
    { title: t('cap.direction'), dataIndex: 'direction', width: 80 },
    { title: t('cap.type'), dataIndex: 'frame_type', width: 80 },
    { title: t('cap.hex'), dataIndex: 'hex', render: (v: string) => <span className="mono">{v}</span> },
  ]
}

export function CapturePage() {
  const t = useT()
  const { message } = AntdApp.useApp()
  const queryClient = useQueryClient()
  const statusQuery = useCaptureStatusQuery()
  const status = statusQuery.data
  const playback = status?.playback
  const [speed, setSpeed] = useState(1)
  const [page, setPage] = useState(1)
  const framesQuery = useCaptureFramesQuery((page - 1) * PAGE_SIZE, PAGE_SIZE, Boolean(playback?.loaded))

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.captureStatus() })
  }

  const run = async (promise: Promise<{ ok: boolean; error?: string; file?: string | null; frames?: number }>, okKey: MessageKey, params?: Record<string, string | number>): Promise<void> => {
    try {
      const r = await promise
      if (r.ok) message.success(t(okKey, params))
      else message.error(r.error ?? t('common.failed'))
      refresh()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const start = (): void => void run(api.capture.start(), 'cap.started')
  const stop = (): void => void run(api.capture.stop(), 'cap.stopped')
  const pause = (): void => void run(api.capture.pause(), 'common.ok')
  const resume = (): void => void run(api.capture.resume(), 'common.ok')
  const load = (name: string): void => {
    setPage(1)
    void run(api.capture.load(name), 'cap.loaded', { file: name })
  }
  const exportPcap = (name: string): void => void run(api.capture.export(name, 'pcap'), 'cap.exported', { file: name })
  const play = (): void => void run(api.capture.play(speed), 'common.ok')
  const stopPlayback = (): void => void run(api.capture.stopPlayback(), 'common.ok')
  const step = (direction: 'forward' | 'backward'): void => {
    if (direction === 'forward' && playback?.index !== undefined && playback.total !== undefined && playback.index >= playback.total - 1) return
    void run(api.capture.step(direction), 'common.ok')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card
        size="small"
        title={
          <Space size={4} wrap>
            <CameraOutlined />
            <span>{t('cap.title')}</span>
            <Tag color={status?.recording ? 'red' : 'default'}>
              {status?.recording ? t('cap.recording') : t('cap.stopped')}
            </Tag>
            {status?.paused ? <Tag color="warning">{t('cap.paused')}</Tag> : null}
          </Space>
        }
        extra={
          <Space wrap>
            <Button type="primary" disabled={status?.recording} onClick={start}>{t('cap.start')}</Button>
            <Button danger disabled={!status?.recording} onClick={stop}>{t('cap.stop')}</Button>
            <Button icon={<PauseCircleOutlined />} disabled={!status?.recording || status?.paused} onClick={pause}>{t('cap.pause')}</Button>
            <Button icon={<PlayCircleOutlined />} disabled={!status?.recording || !status?.paused} onClick={resume}>{t('cap.resume')}</Button>
          </Space>
        }
      >
        <Space wrap>
          <Tag>{t('cap.frames', { n: status?.frames ?? 0 })}</Tag>
          <Tag>{t('cap.rx', { n: status?.rx ?? 0 })}</Tag>
          <Tag>{t('cap.tx', { n: status?.tx ?? 0 })}</Tag>
          <Tag color={(status?.dropped ?? 0) > 0 ? 'warning' : 'default'}>
            {t('cap.dropped', { n: status?.dropped ?? 0 })}
          </Tag>
          <Tag>{t('cap.elapsed', { n: status?.elapsed ?? 0 })}</Tag>
          {status?.file ? <Typography.Text code>{status.file}</Typography.Text> : null}
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
          {t('cap.startHint')}
        </Typography.Paragraph>
      </Card>

      <Card size="small" title={t('cap.files')}>
        <Table<CaptureFileInfo>
          rowKey="name"
          size="small"
          columns={fileColumns(t, load, exportPcap)}
          dataSource={status?.files ?? []}
          pagination={false}
          locale={{ emptyText: t('cap.noFiles') }}
          scroll={{ x: 700 }}
        />
      </Card>

      <Card
        size="small"
        title={
          <Space size={4}>
            <span>{t('cap.playback')}</span>
            {playback?.loaded ? <Tag color="blue">{playback.file}</Tag> : null}
            {playback?.state ? <Tag>{playback.state}</Tag> : null}
          </Space>
        }
        extra={
          <Space wrap>
            <span>{t('cap.speed')}</span>
            <InputNumber min={0.1} max={100} step={0.5} value={speed} onChange={(v) => setSpeed(Number(v ?? 1))} style={{ width: 90 }} />
            <Button type="primary" icon={<PlayCircleOutlined />} disabled={!playback?.loaded} onClick={play}>{t('cap.play')}</Button>
            <Button icon={<PauseCircleOutlined />} disabled={!playback?.loaded} onClick={() => void run(api.capture.pausePlayback(), 'common.ok')}>{t('cap.pause')}</Button>
            <Button icon={<StopOutlined />} disabled={!playback?.loaded} onClick={stopPlayback}>{t('cap.stopPlayback')}</Button>
            <Button icon={<StepBackwardOutlined />} disabled={!playback?.loaded} onClick={() => step('backward')}>{t('cap.prev')}</Button>
            <Button icon={<StepForwardOutlined />} disabled={!playback?.loaded} onClick={() => step('forward')}>{t('cap.next')}</Button>
          </Space>
        }
      >
        {playback?.loaded ? (
          <>
            <Space wrap style={{ marginBottom: 8 }}>
              <Progress
                percent={Math.round((playback.progress ?? 0) * 100)}
                style={{ width: 260 }}
                size="small"
              />
              <Tag>{`${playback.index ?? 0}/${playback.total ?? 0}`}</Tag>
              {playback.current ? (
                <Typography.Text code>{`${playback.current.direction} ${playback.current.frame_type} ${playback.current.hex}`}</Typography.Text>
              ) : null}
            </Space>
            <Table<CaptureFrame>
              rowKey={(row) => `${row.absolute_time}-${row.timestamp}-${row.direction}-${row.hex}`}
              size="small"
              columns={frameColumns(t)}
              dataSource={framesQuery.data?.rows ?? []}
              loading={framesQuery.isFetching}
              pagination={{
                current: page,
                pageSize: PAGE_SIZE,
                total: framesQuery.data?.total ?? 0,
                onChange: setPage,
                showSizeChanger: false,
              }}
              scroll={{ x: 900, y: 320 }}
            />
          </>
        ) : (
          <Typography.Text type="secondary">{t('cap.noLoaded')}</Typography.Text>
        )}
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
          {t('cap.playbackHint')}
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
