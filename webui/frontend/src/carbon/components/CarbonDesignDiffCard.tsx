import { useQueryClient } from '@tanstack/react-query'

import { Button } from '@carbon/react'

import { api, POINTS_XLSX_URL } from '../../api/endpoints'
import { queryKeys, useDesignDiffQuery } from '../../api/queries'
import { apiUrl } from '../../api/client'
import { useT } from '../../i18n'
import { Note, Panel, ToneTag } from './ui'

/** 差异条目行（缺/多共用：ioa + 类型 + 名称） */
function DiffRow({ ioa, type, name }: { ioa: number; type: string; name: string }) {
  return (
    <div className="app-row" style={{ marginBottom: 4, alignItems: 'baseline' }}>
      <span style={{ fontSize: 13, minWidth: 76 }}>
        <b>IOA {ioa}</b>
      </span>
      <span style={{ fontSize: 12, color: 'var(--cds-text-secondary)', minWidth: 34 }}>{type}</span>
      <span style={{ fontSize: 13, flex: 1, minWidth: 120 }}>{name}</span>
    </div>
  )
}

/**
 * 设计 vs 实测比对卡（T95，Carbon 版）：设计基准（导入 xlsx 自动建立或手动快照）
 * 与实测（含自动学习点 + 观测值域）的缺/多/值域差异清单（5s 轮询）。
 * 挂主站工作台——「设计点表对不上真机 IOA」的核对入口。
 */
export function CarbonDesignDiffCard() {
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
    <Panel
      title={
        <span className="app-row">
          {t('design.title')}
          {data?.has_design ? <ToneTag tone="blue">{t('design.baselineOn')}</ToneTag> : null}
        </span>
      }
    >
      <div className="app-row" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
        <Button kind="secondary" size="sm" onClick={() => void setBaseline('set')} data-testid="design-set">
          {t('design.setBaseline')}
        </Button>
        <Button kind="ghost" size="sm" disabled={!data?.has_design} onClick={() => void setBaseline('clear')}>
          {t('design.clearBaseline')}
        </Button>
        <Button kind="ghost" size="sm" disabled={busy} onClick={() => void refetch()}>
          {t('design.refresh')}
        </Button>
        <a href={apiUrl(POINTS_XLSX_URL)} download style={{ textDecoration: 'none' }}>
          <Button kind="ghost" size="sm">
            {t('design.exportXlsx')}
          </Button>
        </a>
      </div>

      {!data ? null : !data.has_design ? (
        <div style={{ color: 'var(--cds-text-secondary)', fontSize: 13 }}>{t('design.noBaseline')}</div>
      ) : total === 0 ? (
        <div style={{ color: 'var(--cds-text-secondary)', fontSize: 13 }}>{t('design.empty')}</div>
      ) : (
        <>
          {data.truncated ? (
            <Note kind="warning" title={t('design.truncated')} style={{ marginBottom: 8 }} />
          ) : null}
          {summary && summary.missing > 0 ? (
            <div style={{ marginBottom: 8 }}>
              <ToneTag tone="red">{t('design.missing')} · {summary.missing}</ToneTag>
              {data.missing.slice(0, 50).map((p) => (
                <DiffRow key={`m-${p.ioa}-${p.type}`} ioa={p.ioa} type={p.type} name={p.name} />
              ))}
            </div>
          ) : null}
          {summary && summary.extra > 0 ? (
            <div style={{ marginBottom: 8 }}>
              <ToneTag tone="magenta">{t('design.extra')} · {summary.extra}</ToneTag>
              {data.extra.slice(0, 50).map((p) => (
                <DiffRow key={`e-${p.ioa}-${p.type}`} ioa={p.ioa} type={p.type} name={p.name} />
              ))}
            </div>
          ) : null}
          {summary && summary.mismatch > 0 ? (
            <div>
              <ToneTag tone="warm-gray">{t('design.mismatch')} · {summary.mismatch}</ToneTag>
              {data.mismatch.slice(0, 50).map((m) => (
                <div key={`x-${m.ioa}`} className="app-row" style={{ marginBottom: 4, alignItems: 'baseline' }}>
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
    </Panel>
  )
}
