import { useEffect, useRef, useState } from 'react'

import { Button, Tag } from '@carbon/react'

import { api } from '../../api/endpoints'
import { useAlarmsQuery } from '../../api/queries'
import { useT, type MessageKey } from '../../i18n'
import { alarmBeep } from '../../lib/alarmSound'
import { BoolField, Panel } from './ui'

/** Carbon Tag 语义色：按告警类别映射（一色一义 + 文字，见设计规范 §4.1）. */
const KIND_TAG: Record<string, 'red' | 'magenta' | 'warm-gray'> = {
  limit: 'red',
  comm: 'red',
  jump: 'magenta',
  stale: 'warm-gray',
}

/** 值守告警卡（T93，Carbon 版）：激活列表 + 确认 + 可选声音提示（2s 轮询）. */
export function CarbonAlarmCard() {
  const t = useT()
  const { data, refetch } = useAlarmsQuery()
  const [sound, setSound] = useState(false)
  const lastNew = useRef(0)

  useEffect(() => {
    if (sound && data && data.new_since_poll > lastNew.current) alarmBeep()
    lastNew.current = data?.new_since_poll ?? 0
  }, [sound, data])

  return (
    <Panel
      title={
        <span className="app-row">
          {t('alarms.title')}
          {data && data.active.length > 0 ? (
            <Tag size="sm" type="red">
              {data.active.length}
            </Tag>
          ) : null}
        </span>
      }
    >
      {data ? (
        <div className="app-row" style={{ marginBottom: 8 }}>
          <BoolField
            id="alarms-sound"
            label={t('alarms.sound')}
            value={sound}
            onChange={(v) => setSound(Boolean(v))}
          />
          <span style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>
            {t('alarms.history', { n: data.history_total })}
          </span>
        </div>
      ) : null}
      {data && data.active.length > 0 ? (
        data.active.map((a) => (
          <div key={a.id} className="app-row" style={{ marginBottom: 6, alignItems: 'flex-start' }}>
            <Tag size="sm" type={KIND_TAG[a.kind] ?? 'warm-gray'}>
              {t(`alarms.kind.${a.kind}` as MessageKey)}
            </Tag>
            <span style={{ fontSize: 13, flex: 1, minWidth: 200 }}>
              {a.ioa !== null ? <b>IOA {a.ioa}：</b> : null}
              {a.message}
              <span style={{ color: 'var(--cds-text-secondary)', fontSize: 12 }}>
                {' '}
                · {a.age_s}s{a.acked ? ` · ${t('alarms.acked')}` : ''}
              </span>
            </span>
            {!a.acked ? (
              <Button
                size="sm"
                kind="ghost"
                onClick={() => {
                  void api.alarmsAck(a.id).then(() => refetch())
                }}
              >
                {t('alarms.ack')}
              </Button>
            ) : null}
          </div>
        ))
      ) : (
        <div style={{ color: 'var(--cds-text-secondary)', fontSize: 13 }}>{t('alarms.empty')}</div>
      )}
    </Panel>
  )
}
