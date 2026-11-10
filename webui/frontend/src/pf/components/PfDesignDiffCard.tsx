import { useQueryClient } from '@tanstack/react-query'

import { Button, Card, CardBody, CardTitle, Label } from '@patternfly/react-core'

import { api, POINTS_XLSX_URL } from '../../api/endpoints'
import { queryKeys, useDesignDiffQuery } from '../../api/queries'
import { apiUrl } from '../../api/client'
import { useT } from '../../i18n'

/** 差异条目行（缺/多共用：ioa + 类型 + 名称） */
function DiffRow({ ioa, type, name }: { ioa: number; type: string; name: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 4, alignItems: 'baseline' }}>
      <span style={{ fontSize: 13, minWidth: 76 }}>
        <b>IOA {ioa}</b>
      </span>
      <span style={{ fontSize: 12, color: 'var(--pf-t--global--text--color--subtle)', minWidth: 34 }}>
        {type}
      </span>
      <span style={{ fontSize: 13, flex: 1, minWidth: 120 }}>{name}</span>
    </div>
  )
}

/**
 * 设计 vs 实测比对卡（T95，PatternFly 版）：设计基准（导入 xlsx 自动建立或手动快照）
 * 与实测（含自动学习点 + 观测值域）的缺/多/值域差异清单（5s 轮询）。
 * 挂主站工作台——「设计点表对不上真机 IOA」的核对入口。
 */
export function PfDesignDiffCard() {
  const t = useT()
  const queryClient = useQueryClient()
  const { data, refetch } = useDesignDiffQuery()
  const busy = data === undefined

  const setBaseline = async (action: 'set' | 'clear'): Promise<void> => {
    await api.pointsDesign(action)
    void queryClient.invalidateQueries({ queryKey: queryKeys.designDiff() })
  }

  const summary = data?.summary
  const total = summary ? summary.missing + summary.extra + summary.mismatch : 0

  return (
    <Card>
      <CardTitle>
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          {t('design.title')}
          {data?.has_design ? (
            <Label isCompact color="blue">
              {t('design.baselineOn')}
            </Label>
          ) : null}
        </span>
      </CardTitle>
      <CardBody>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          <Button variant="secondary" size="sm" onClick={() => void setBaseline('set')} data-testid="design-set">
            {t('design.setBaseline')}
          </Button>
          <Button variant="link" size="sm" isDisabled={!data?.has_design} onClick={() => void setBaseline('clear')}>
            {t('design.clearBaseline')}
          </Button>
          <Button variant="link" size="sm" isDisabled={busy} onClick={() => void refetch()}>
            {t('design.refresh')}
          </Button>
          <a href={apiUrl(POINTS_XLSX_URL)} download style={{ textDecoration: 'none' }}>
            <Button variant="link" size="sm">
              {t('design.exportXlsx')}
            </Button>
          </a>
        </div>

        {!data ? null : !data.has_design ? (
          <div style={{ color: 'var(--pf-t--global--text--color--subtle)', fontSize: 13 }}>
            {t('design.noBaseline')}
          </div>
        ) : total === 0 ? (
          <div style={{ color: 'var(--pf-t--global--text--color--subtle)', fontSize: 13 }}>
            {t('design.empty')}
          </div>
        ) : (
          <>
            {data.truncated ? (
              <div style={{ color: 'var(--pf-t--global--warning--color--100)', fontSize: 12, marginBottom: 8 }}>
                {t('design.truncated')}
              </div>
            ) : null}
            {summary && summary.missing > 0 ? (
              <div style={{ marginBottom: 8 }}>
                <Label isCompact color="red">
                  {t('design.missing')} · {summary.missing}
                </Label>
                {data.missing.slice(0, 50).map((p) => (
                  <DiffRow key={`m-${p.ioa}-${p.type}`} ioa={p.ioa} type={p.type} name={p.name} />
                ))}
              </div>
            ) : null}
            {summary && summary.extra > 0 ? (
              <div style={{ marginBottom: 8 }}>
                <Label isCompact color="orangered">
                  {t('design.extra')} · {summary.extra}
                </Label>
                {data.extra.slice(0, 50).map((p) => (
                  <DiffRow key={`e-${p.ioa}-${p.type}`} ioa={p.ioa} type={p.type} name={p.name} />
                ))}
              </div>
            ) : null}
            {summary && summary.mismatch > 0 ? (
              <div>
                <Label isCompact color="grey">
                  {t('design.mismatch')} · {summary.mismatch}
                </Label>
                {data.mismatch.slice(0, 50).map((m) => (
                  <div key={`x-${m.ioa}`} style={{ display: 'flex', gap: 8, marginBottom: 4, alignItems: 'baseline' }}>
                    <span style={{ fontSize: 13, minWidth: 76 }}>
                      <b>IOA {m.ioa}</b>
                    </span>
                    <span style={{ fontSize: 13, flex: 1, minWidth: 120 }}>{m.reason}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  )
}
