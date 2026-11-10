import { useState } from 'react'

import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FormGroup,
  Label,
  Pagination,
  Progress,
  TextInput,
} from '@patternfly/react-core'

import { api, captureDownloadUrl } from '../../api/endpoints'
import { useCaptureFramesQuery, useCaptureStatusQuery } from '../../api/queries'
import type { CaptureDiffResponse, CaptureFileInfo } from '../../api/types'
import { useLocale, useT } from '../../i18n'
import { formatDateTime, localeTag } from '../../lib/format'

const PAGE_SIZE = 100

function formatBytes(n: number): string {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function PfCapturePage() {
  const t = useT()
  const locale = useLocale()
  const statusQuery = useCaptureStatusQuery()
  const status = statusQuery.data
  const playback = status?.playback
  const [speed, setSpeed] = useState(1)
  const [page, setPage] = useState(1)
  const [last, setLast] = useState<{ ok: boolean; text: string } | null>(null)
  // T96 报文对比
  const [diffA, setDiffA] = useState('')
  const [diffB, setDiffB] = useState('')
  const [diff, setDiff] = useState<CaptureDiffResponse | null>(null)
  const [diffErr, setDiffErr] = useState('')

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

  const fileOptions = (status?.files ?? []).map((f: CaptureFileInfo) => f.name)

  const runDiff = async (): Promise<void> => {
    setDiffErr('')
    try {
      const r = await api.capture.diff(diffA, diffB)
      if (r.ok) {
        setDiff(r)
      } else {
        setDiff(null)
        setDiffErr(r.error ?? t('cmd.unknown'))
      }
    } catch (e) {
      setDiff(null)
      setDiffErr((e as Error).message)
    }
  }

  const fileRow = (file: CaptureFileInfo) => (
    <tr key={file.name} className="pf-v6-c-table__tr" data-testid="capture-file">
      <td className="pf-v6-c-table__td">{file.name}</td>
      <td className="pf-v6-c-table__td" style={{ textAlign: 'right' }}>
        {formatBytes(file.size)}
      </td>
      <td className="pf-v6-c-table__td mono">{formatDateTime(file.mtime, localeTag(locale))}</td>
      <td className="pf-v6-c-table__td">
        <Flex gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setPage(1)
              void run(t('cap.loaded', { file: file.name }), api.capture.load(file.name))
            }}
          >
            {t('cap.load')}
          </Button>
          <Button variant="link" size="sm" component="a" href={captureDownloadUrl(file.name)} download>
            {t('cap.download')}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void run(t('cap.exported', { file: file.name }), api.capture.export(file.name, 'pcap'))}
          >
            {t('cap.exportPcap')}
          </Button>
        </Flex>
      </td>
    </tr>
  )

  return (
    <>
      <Card>
        <CardTitle>
          <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
            <span>{t('cap.title')}</span>
            <Label isCompact color={recording ? 'red' : 'grey'}>
              {recording ? t('cap.recording') : t('cap.stopped')}
            </Label>
            {paused ? <Label isCompact color="orange">{t('cap.paused')}</Label> : null}
            <Label isCompact>{t('cap.frames', { n: status?.frames ?? 0 })}</Label>
            <Label isCompact>{t('cap.rx', { n: status?.rx ?? 0 })}</Label>
            <Label isCompact>{t('cap.tx', { n: status?.tx ?? 0 })}</Label>
            <Label isCompact color={(status?.dropped ?? 0) > 0 ? 'orange' : 'grey'}>
              {t('cap.dropped', { n: status?.dropped ?? 0 })}
            </Label>
          </Flex>
        </CardTitle>
        <CardBody>
          {last ? (
            <div
              style={{
                marginBottom: 8,
                color: last.ok
                  ? 'var(--pf-t--global--text--color--status--success--default)'
                  : 'var(--pf-t--global--text--color--status--danger--default)',
              }}
            >
              {last.text}
            </div>
          ) : null}
          <Flex gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
            <Button variant="primary" isDisabled={recording} onClick={() => void run(t('cap.started'), api.capture.start())}>
              {t('cap.start')}
            </Button>
            <Button variant="danger" isDisabled={!recording} onClick={() => void run(t('cap.stopped'), api.capture.stop())}>
              {t('cap.stop')}
            </Button>
            <Button
              variant="secondary"
              isDisabled={!recording || paused}
              onClick={() => void run(t('cap.paused'), api.capture.pause())}
            >
              {t('cap.pause')}
            </Button>
            <Button
              variant="secondary"
              isDisabled={!recording || !paused}
              onClick={() => void run(t('cap.resume'), api.capture.resume())}
            >
              {t('cap.resume')}
            </Button>
          </Flex>
          <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>{t('cap.startHint')}</div>

          <div style={{ marginTop: 16, fontSize: 13, marginBottom: 4 }}>{t('cap.files')}</div>
          {(status?.files ?? []).length === 0 ? (
            <div style={{ opacity: 0.7, fontSize: 12 }}>{t('cap.noFiles')}</div>
          ) : (
            <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
              <thead className="pf-v6-c-table__thead">
                <tr className="pf-v6-c-table__tr">
                  <th className="pf-v6-c-table__th">{t('cap.name')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 110, minWidth: 110, textAlign: 'right' }}>{t('cap.size')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 190, minWidth: 190 }}>{t('cap.time')}</th>
                  <th className="pf-v6-c-table__th" style={{ width: 300, minWidth: 300 }}>{t('cap.actions')}</th>
                </tr>
              </thead>
              <tbody className="pf-v6-c-table__tbody">{(status?.files ?? []).map(fileRow)}</tbody>
            </table>
          )}
        </CardBody>
      </Card>

      <div style={{ marginTop: 16 }}>
        <Card>
          <CardTitle>
            <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
              <span>{t('cap.playback')}</span>
              {playback?.loaded ? <Label isCompact color="blue">{playback.file}</Label> : null}
              {playback?.state ? <Label isCompact>{playback.state}</Label> : null}
            </Flex>
          </CardTitle>
          <CardBody>
            <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
              <div style={{ width: 110, minWidth: 110 }}>
                <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 4 }}>{t('cap.speed')}</div>
                <TextInput
                  type="number"
                  min={0.1}
                  step={0.5}
                  value={String(speed)}
                  onChange={(_e, v) => setSpeed(Number(v) || 1)}
                  aria-label={t('cap.speed')}
                />
              </div>
              <Button variant="primary" isDisabled={!playback?.loaded} onClick={() => void run(t('cap.play'), api.capture.play(speed))}>
                {t('cap.play')}
              </Button>
              <Button
                variant="secondary"
                isDisabled={!playback?.loaded}
                onClick={() => void run(t('cap.pause'), api.capture.pausePlayback())}
              >
                {t('cap.pause')}
              </Button>
              <Button
                variant="secondary"
                isDisabled={!playback?.loaded}
                onClick={() => void run(t('cap.stopPlayback'), api.capture.stopPlayback())}
              >
                {t('cap.stopPlayback')}
              </Button>
              <Button
                variant="secondary"
                isDisabled={!playback?.loaded}
                onClick={() => void run(t('cap.prev'), api.capture.step('backward'))}
              >
                {t('cap.prev')}
              </Button>
              <Button
                variant="secondary"
                isDisabled={!playback?.loaded}
                onClick={() => void run(t('cap.next'), api.capture.step('forward'))}
              >
                {t('cap.next')}
              </Button>
            </Flex>
            <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>{t('cap.playbackHint')}</div>

            {playback?.loaded ? (
              <div style={{ marginTop: 12 }}>
                <Progress
                  value={Math.round((playback.progress ?? 0) * 100)}
                  title={t('cap.playback')}
                />
                <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>
                  {playback.index ?? 0}/{playback.total ?? 0}
                </div>
              </div>
            ) : (
              <div style={{ opacity: 0.7, fontSize: 12, marginTop: 12 }}>{t('cap.noLoaded')}</div>
            )}

            {playback?.loaded ? (
              <>
                <div style={{ marginTop: 16, overflowX: 'auto' }}>
                  <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
                    <thead className="pf-v6-c-table__thead">
                      <tr className="pf-v6-c-table__tr">
                        <th className="pf-v6-c-table__th" style={{ width: 130, minWidth: 130 }}>{t('cap.frameTime')}</th>
                        <th className="pf-v6-c-table__th" style={{ width: 80, minWidth: 80 }}>{t('cap.direction')}</th>
                        <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90 }}>{t('cap.type')}</th>
                        <th className="pf-v6-c-table__th" style={{ width: 80, minWidth: 80, textAlign: 'right' }}>{t('frameViewer.col.len')}</th>
                        <th className="pf-v6-c-table__th">{t('cap.hex')}</th>
                      </tr>
                    </thead>
                    <tbody className="pf-v6-c-table__tbody">
                      {(framesQuery.data?.rows ?? []).map((frame, i) => (
                        <tr key={`${frame.timestamp}-${i}`} className="pf-v6-c-table__tr">
                          <td className="pf-v6-c-table__td mono">{frame.timestamp.toFixed(3)}</td>
                          <td className="pf-v6-c-table__td">
                            <Label isCompact color={frame.direction === 'rx' ? 'blue' : 'green'}>
                              {frame.direction}
                            </Label>
                          </td>
                          <td className="pf-v6-c-table__td">{frame.frame_type}</td>
                          <td className="pf-v6-c-table__td" style={{ textAlign: 'right' }}>{frame.length}</td>
                          <td className="pf-v6-c-table__td mono" style={{ wordBreak: 'break-all' }}>{frame.hex}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ marginTop: 8 }}>
                  <Pagination
                    itemCount={total}
                    perPage={PAGE_SIZE}
                    page={page}
                    onSetPage={(_event, p) => setPage(p)}
                    isCompact
                  />
                </div>
              </>
            ) : null}
          </CardBody>
        </Card>
      </div>

      <div style={{ marginTop: 16 }}>
        <Card>
          <CardTitle>{t('cap.diffTitle')}</CardTitle>
          <CardBody>
            <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsFlexEnd' }} flexWrap={{ default: 'wrap' }}>
              <FormGroup label={t('cap.diffA')} fieldId="pf-cap-diff-a">
                <select
                  id="pf-cap-diff-a"
                  className="pf-v6-c-form-control"
                  value={diffA}
                  onChange={(e) => {
                    setDiffA(e.target.value)
                    setDiff(null)
                  }}
                  data-testid="pf-cap-diff-a"
                >
                  <option value="">—</option>
                  {fileOptions.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </FormGroup>
              <FormGroup label={t('cap.diffB')} fieldId="pf-cap-diff-b">
                <select
                  id="pf-cap-diff-b"
                  className="pf-v6-c-form-control"
                  value={diffB}
                  onChange={(e) => {
                    setDiffB(e.target.value)
                    setDiff(null)
                  }}
                  data-testid="pf-cap-diff-b"
                >
                  <option value="">—</option>
                  {fileOptions.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </FormGroup>
              <Button
                variant="primary"
                isDisabled={!diffA || !diffB}
                onClick={() => void runDiff()}
                data-testid="capture-diff-run"
              >
                {t('cap.diffRun')}
              </Button>
            </Flex>
            {diffErr ? (
              <div style={{ marginTop: 8, color: 'var(--pf-t--global--text--color--status--danger--default)', fontSize: 13 }}>
                {diffErr}
              </div>
            ) : null}
            {diff ? (
              <div style={{ marginTop: 10 }}>
                <Label isCompact color={diff.identical ? 'green' : 'red'} data-testid="capture-diff-verdict">
                  {diff.identical
                    ? t('cap.diffIdentical')
                    : t('cap.diffNotIdentical', { n: diff.diff_total })}
                </Label>
                <span style={{ fontSize: 12, opacity: 0.75, marginLeft: 8 }}>
                  {diff.total_a} / {diff.total_b}
                </span>
                {!diff.identical ? (
                  <div style={{ marginTop: 10, overflowX: 'auto' }} data-testid="capture-diff-table">
                    <table className="pf-v6-c-table pf-m-compact" style={{ width: '100%', tableLayout: 'fixed' }}>
                      <thead className="pf-v6-c-table__thead">
                        <tr className="pf-v6-c-table__tr">
                          <th className="pf-v6-c-table__th">{t('cap.diffColSig')}</th>
                          <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90, textAlign: 'right' }}>{t('cap.diffColA')}</th>
                          <th className="pf-v6-c-table__th" style={{ width: 90, minWidth: 90, textAlign: 'right' }}>{t('cap.diffColB')}</th>
                          <th className="pf-v6-c-table__th" style={{ width: 70, minWidth: 70, textAlign: 'right' }}>{t('cap.diffDiff')}</th>
                        </tr>
                      </thead>
                      <tbody className="pf-v6-c-table__tbody">
                        {diff.entries.slice(0, 50).map((e) => (
                          <tr key={e.signature} className="pf-v6-c-table__tr">
                            <td className="pf-v6-c-table__td mono" style={{ wordBreak: 'break-all' }}>{e.signature}</td>
                            <td className="pf-v6-c-table__td" style={{ textAlign: 'right' }}>{e.count_a}</td>
                            <td className="pf-v6-c-table__td" style={{ textAlign: 'right' }}>{e.count_b}</td>
                            <td className="pf-v6-c-table__td" style={{ textAlign: 'right' }}>{e.delta > 0 ? `+${e.delta}` : e.delta}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
            ) : null}
          </CardBody>
        </Card>
      </div>
    </>
  )
}
