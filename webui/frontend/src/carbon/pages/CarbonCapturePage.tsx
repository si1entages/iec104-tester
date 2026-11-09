import { useState } from 'react'

import { Button, Link, ProgressBar, Tag } from '@carbon/react'

import { api, captureDownloadUrl } from '../../api/endpoints'
import { useCaptureFramesQuery, useCaptureStatusQuery } from '../../api/queries'
import type { CaptureFileInfo } from '../../api/types'
import { useLocale, useT } from '../../i18n'
import { formatDateTime, localeTag } from '../../lib/format'
import { Pager, Panel, TableFrame, TextField } from '../components/ui'

const PAGE_SIZE = 100

function formatBytes(n: number): string {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function CarbonCapturePage() {
  const t = useT()
  const locale = useLocale()
  const statusQuery = useCaptureStatusQuery()
  const status = statusQuery.data
  const playback = status?.playback
  const [speed, setSpeed] = useState(1)
  const [page, setPage] = useState(1)
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)

  const framesQuery = useCaptureFramesQuery((page - 1) * PAGE_SIZE, PAGE_SIZE, Boolean(playback?.loaded))
  const total = framesQuery.data?.total ?? 0

  const run = async (label: string, task: Promise<{ ok: boolean; error?: string }>): Promise<void> => {
    const result = await task
    setLast(
      result.ok
        ? { ok: true, text: label }
        : { ok: false, text: `${label}: ${result.error ?? t('cmd.unknown')}` },
    )
  }

  const recording = Boolean(status?.recording)
  const paused = Boolean(status?.paused)

  return (
    <div className="app-gap">
      <Panel
        title={
          <span className="app-row">
            {t('cap.title')}
            <Tag size="sm" type={recording ? 'red' : 'gray'}>
              {recording ? t('cap.recording') : t('cap.stopped')}
            </Tag>
            {paused ? <Tag size="sm" type="magenta">{t('cap.paused')}</Tag> : null}
            <Tag size="sm" type="gray">{t('cap.frames', { n: status?.frames ?? 0 })}</Tag>
            <Tag size="sm" type="gray">{t('cap.rx', { n: status?.rx ?? 0 })}</Tag>
            <Tag size="sm" type="gray">{t('cap.tx', { n: status?.tx ?? 0 })}</Tag>
            <Tag size="sm" type={(status?.dropped ?? 0) > 0 ? 'magenta' : 'gray'}>
              {t('cap.dropped', { n: status?.dropped ?? 0 })}
            </Tag>
          </span>
        }
      >
        {last ? (
          <div style={{ marginBottom: 8, color: last.ok ? 'var(--cds-support-success)' : 'var(--cds-text-error)' }}>
            {last.text}
          </div>
        ) : null}
        <div className="app-row">
          <Button kind="primary" disabled={recording} onClick={() => void run(t('cap.started'), api.capture.start())}>
            {t('cap.start')}
          </Button>
          <Button kind="danger" disabled={!recording} onClick={() => void run(t('cap.stopped'), api.capture.stop())}>
            {t('cap.stop')}
          </Button>
          <Button
            kind="secondary"
            disabled={!recording || paused}
            onClick={() => void run(t('cap.paused'), api.capture.pause())}
          >
            {t('cap.pause')}
          </Button>
          <Button
            kind="secondary"
            disabled={!recording || !paused}
            onClick={() => void run(t('cap.resume'), api.capture.resume())}
          >
            {t('cap.resume')}
          </Button>
        </div>
        <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginTop: 8 }}>{t('cap.startHint')}</div>

        <div style={{ marginTop: 16, fontSize: 13, marginBottom: 4 }}>{t('cap.files')}</div>
        {(status?.files ?? []).length === 0 ? (
          <div style={{ color: 'var(--cds-text-secondary)', fontSize: 12 }}>{t('cap.noFiles')}</div>
        ) : (
          <TableFrame>
            <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
              <thead>
                <tr>
                  <th><span className="cds--table-header-label">{t('cap.name')}</span></th>
                  <th style={{ width: 110, minWidth: 110, textAlign: 'right' }}><span className="cds--table-header-label">{t('cap.size')}</span></th>
                  <th style={{ width: 190, minWidth: 190 }}><span className="cds--table-header-label">{t('cap.time')}</span></th>
                  <th style={{ width: 300, minWidth: 300 }}><span className="cds--table-header-label">{t('cap.actions')}</span></th>
                </tr>
              </thead>
              <tbody>
                {(status?.files ?? []).map((file: CaptureFileInfo) => (
                  <tr key={file.name} data-testid="capture-file">
                    <td>{file.name}</td>
                    <td style={{ textAlign: 'right' }}>{formatBytes(file.size)}</td>
                    <td className="mono">{formatDateTime(file.mtime, localeTag(locale))}</td>
                    <td>
                      <div className="app-row">
                        <Button
                          kind="secondary"
                          size="sm"
                          onClick={() => {
                            setPage(1)
                            void run(t('cap.loaded', { file: file.name }), api.capture.load(file.name))
                          }}
                        >
                          {t('cap.load')}
                        </Button>
                        <Link href={captureDownloadUrl(file.name)} download>
                          {t('cap.download')}
                        </Link>
                        <Button
                          kind="secondary"
                          size="sm"
                          onClick={() => void run(t('cap.exported', { file: file.name }), api.capture.export(file.name, 'pcap'))}
                        >
                          {t('cap.exportPcap')}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
        )}
      </Panel>

      <Panel
        title={
          <span className="app-row">
            {t('cap.playback')}
            {playback?.loaded ? <Tag size="sm" type="blue">{playback.file}</Tag> : null}
            {playback?.state ? <Tag size="sm" type="gray">{playback.state}</Tag> : null}
          </span>
        }
      >
        <div className="app-row" style={{ alignItems: 'flex-end' }}>
          <TextField
            id="cb-cap-speed"
            label={t('cap.speed')}
            type="number"
            width={110}
            value={String(speed)}
            onChange={(v) => setSpeed(Number(v) || 1)}
          />
          <Button kind="primary" disabled={!playback?.loaded} onClick={() => void run(t('cap.play'), api.capture.play(speed))}>
            {t('cap.play')}
          </Button>
          <Button
            kind="secondary"
            disabled={!playback?.loaded}
            onClick={() => void run(t('cap.pause'), api.capture.pausePlayback())}
          >
            {t('cap.pause')}
          </Button>
          <Button
            kind="secondary"
            disabled={!playback?.loaded}
            onClick={() => void run(t('cap.stopPlayback'), api.capture.stopPlayback())}
          >
            {t('cap.stopPlayback')}
          </Button>
          <Button
            kind="secondary"
            disabled={!playback?.loaded}
            onClick={() => void run(t('cap.prev'), api.capture.step('backward'))}
          >
            {t('cap.prev')}
          </Button>
          <Button
            kind="secondary"
            disabled={!playback?.loaded}
            onClick={() => void run(t('cap.next'), api.capture.step('forward'))}
          >
            {t('cap.next')}
          </Button>
        </div>
        <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginTop: 8 }}>{t('cap.playbackHint')}</div>

        {playback?.loaded ? (
          <div style={{ marginTop: 12 }}>
            <ProgressBar
              value={Math.round((playback.progress ?? 0) * 100)}
              max={100}
              label={t('cap.playback')}
            />
            <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)', marginTop: 4 }}>
              {playback.index ?? 0}/{playback.total ?? 0}
            </div>
          </div>
        ) : (
          <div style={{ color: 'var(--cds-text-secondary)', fontSize: 12, marginTop: 12 }}>{t('cap.noLoaded')}</div>
        )}

        {playback?.loaded ? (
          <>
            <div style={{ marginTop: 16 }}>
              <TableFrame>
                <table className="cds--data-table cds--data-table--md" style={{ width: '100%', tableLayout: 'fixed' }}>
                  <thead>
                    <tr>
                      <th style={{ width: 130, minWidth: 130 }}><span className="cds--table-header-label">{t('cap.frameTime')}</span></th>
                      <th style={{ width: 80, minWidth: 80 }}><span className="cds--table-header-label">{t('cap.direction')}</span></th>
                      <th style={{ width: 90, minWidth: 90 }}><span className="cds--table-header-label">{t('cap.type')}</span></th>
                      <th style={{ width: 80, minWidth: 80, textAlign: 'right' }}><span className="cds--table-header-label">{t('frameViewer.col.len')}</span></th>
                      <th><span className="cds--table-header-label">{t('cap.hex')}</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(framesQuery.data?.rows ?? []).map((frame, i) => (
                      <tr key={`${frame.timestamp}-${i}`}>
                        <td className="mono">{frame.timestamp.toFixed(3)}</td>
                        <td>
                          <Tag size="sm" type={frame.direction === 'rx' ? 'blue' : 'green'}>
                            {frame.direction}
                          </Tag>
                        </td>
                        <td>{frame.frame_type}</td>
                        <td style={{ textAlign: 'right' }}>{frame.length}</td>
                        <td className="mono" style={{ wordBreak: 'break-all' }}>{frame.hex}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableFrame>
            </div>
            <div style={{ marginTop: 8 }}>
              <Pager page={page} pageSize={PAGE_SIZE} totalItems={total} onChange={setPage} />
            </div>
          </>
        ) : null}
      </Panel>
    </div>
  )
}
