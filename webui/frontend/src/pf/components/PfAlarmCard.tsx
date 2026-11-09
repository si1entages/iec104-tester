import { useEffect, useRef, useState } from 'react'

import { Button, Card, CardBody, CardTitle, Label, Switch } from '@patternfly/react-core'

import { api } from '../../api/endpoints'
import { useAlarmsQuery } from '../../api/queries'
import { useT, type MessageKey } from '../../i18n'
import { alarmBeep } from '../../lib/alarmSound'

/** PF Label 语义色：按告警类别映射（一色一义 + 文字，见设计规范 §4.1）. */
const KIND_COLOR: Record<string, 'red' | 'orangered' | 'grey'> = {
  limit: 'red',
  comm: 'red',
  jump: 'orangered',
  stale: 'grey',
}

/** 值守告警卡（T93，PatternFly 版）：激活列表 + 确认 + 可选声音提示（2s 轮询）. */
export function PfAlarmCard() {
  const t = useT()
  const { data, refetch } = useAlarmsQuery()
  const [sound, setSound] = useState(false)
  const lastNew = useRef(0)

  useEffect(() => {
    if (sound && data && data.new_since_poll > lastNew.current) alarmBeep()
    lastNew.current = data?.new_since_poll ?? 0
  }, [sound, data])

  return (
    <Card>
      <CardTitle>
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          {t('alarms.title')}
          {data && data.active.length > 0 ? (
            <Label isCompact color="red">
              {data.active.length}
            </Label>
          ) : null}
        </span>
      </CardTitle>
      <CardBody>
        {data ? (
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 8 }}>
            <Switch
              id="alarms-sound"
              label={t('alarms.sound')}
              isChecked={sound}
              onChange={(_e, v) => setSound(v)}
            />
            <span style={{ fontSize: 12, color: 'var(--pf-t--global--text--color--subtle)' }}>
              {t('alarms.history', { n: data.history_total })}
            </span>
          </div>
        ) : null}
        {data && data.active.length > 0 ? (
          data.active.map((a) => (
            <div
              key={a.id}
              style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 6 }}
            >
              <Label isCompact color={KIND_COLOR[a.kind] ?? 'grey'}>
                {t(`alarms.kind.${a.kind}` as MessageKey)}
              </Label>
              <span style={{ fontSize: 13, flex: 1 }}>
                {a.ioa !== null ? <b>IOA {a.ioa}：</b> : null}
                {a.message}
                <span
                  style={{ color: 'var(--pf-t--global--text--color--subtle)', fontSize: 12 }}
                >
                  {' '}
                  · {a.age_s}s{a.acked ? ` · ${t('alarms.acked')}` : ''}
                </span>
              </span>
              {!a.acked ? (
                <Button
                  variant="secondary"
                  size="sm"
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
          <div style={{ color: 'var(--pf-t--global--text--color--subtle)', fontSize: 13 }}>
            {t('alarms.empty')}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
