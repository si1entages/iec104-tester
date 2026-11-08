import { useRef, useState } from 'react'

import {
  DownloadOutlined,
  ImportOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { App as AntdApp, Button, Dropdown, Input, InputNumber, Popover, Select, Space } from 'antd'
import type { MenuProps } from 'antd'

import { api } from '../api/endpoints'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '../api/queries'
import type { BatchAction, BatchPointsRequest, ImportFormat, Point } from '../api/types'
import { useT } from '../i18n'

const TYPE_OPTIONS = ['YX', 'YC', 'YK', 'YM', 'STEP'].map((v) => ({ value: v, label: v }))

/** 读文件文本：File.text() 在部分环境（如 jsdom）缺失，FileReader 兜底 */
function readText(file: File): Promise<string> {
  if (typeof file.text === 'function') return file.text()
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error ?? new Error('read file failed')) // i18n-ignore 内部异常
    reader.readAsText(file)
  })
}

/**
 * 点表工具（T19 补齐旧页能力②③）：
 *  - 导入点表（YAML / CSV / JSON，按扩展名选 format，服务端内容嗅探兜底）
 *  - 导出（YAML / CSV / 会话 JSON，直开下载链接）
 *  - 批量操作（POST /api/points/batch：启用 / 禁用 / 改组；IOA 留空 = 对所选类型全部生效）
 * 挂在共享 PointsTable 卡片工具区，主站/子站页均可用。
 */
export function PointsTools() {
  const t = useT()
  const { message } = AntdApp.useApp()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement | null>(null)

  // 批量操作状态
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchType, setBatchType] = useState<string>('YX')
  const [batchIoas, setBatchIoas] = useState('')
  const [batchGroup, setBatchGroup] = useState(1)
  const [batchBusy, setBatchBusy] = useState(false)

  const invalidate = (): void => {
    // 导入/批量后让点表缓存失效重拉（批量可能改变值/组/使能）
    void queryClient.invalidateQueries({ queryKey: queryKeys.points() })
  }

  const doImport = async (file: File): Promise<void> => {
    const text = await readText(file)
    const ext = (file.name.split('.').pop() ?? '').toLowerCase()
    const format: ImportFormat = ext === 'csv' ? 'csv' : ext === 'json' ? 'json' : 'yaml'
    try {
      const r = await api.importPoints(text, format)
      if (r.ok) {
        message.success(t('pt.imported', {
          n: String((r as Record<string, unknown>).points ?? ''),
        }))
        invalidate()
      } else {
        message.error(r.error ?? t('pt.importFailed'))
      }
    } catch (e) {
      message.error(t('pt.importFailedWith', { error: (e as Error).message }))
    }
  }

  const exportItems: MenuProps['items'] = [
    { key: 'yaml', label: t('pt.exportYaml') },
    { key: 'csv', label: t('pt.exportCsv') },
    { key: 'session', label: t('pt.exportSession') },
  ]
  const onExport: MenuProps['onClick'] = ({ key }) => {
    const url =
      key === 'yaml' ? '/api/points/yaml' : key === 'csv' ? '/api/export/points.csv' : '/api/export/session.json'
    window.open(url, '_blank')
  }

  const resolveIoas = (points: Point[] | undefined): number[] => {
    // 先丢弃空 token（否则 Number('')=0 会把 IOA 0 误当作有效输入）
    const parsed = batchIoas
      .split(/[,\s，]+/)
      .filter((s) => s.trim() !== '')
      .map(Number)
      .filter((n) => Number.isInteger(n) && n >= 0)
    if (parsed.length > 0) return parsed
    // IOA 留空 = 对所选类型的全部点生效（从点表缓存展开）
    return (points ?? []).filter((p) => p.type === batchType).map((p) => p.ioa)
  }

  const doBatch = async (action: BatchAction, points: Point[] | undefined): Promise<void> => {
    const ioas = resolveIoas(points)
    if (ioas.length === 0) {
      message.warning(t('pt.needIoas'))
      return
    }
    const body: BatchPointsRequest = { type: batchType, ioas, action, group: action === 'group' ? batchGroup : null }
    setBatchBusy(true)
    try {
      const r = await api.batchPoints(body)
      if (r.ok) {
        message.success(t('pt.updated', {
          n: String((r as Record<string, unknown>).changed ?? ioas.length),
        }))
        setBatchOpen(false)
        invalidate()
      } else {
        message.error(r.error ?? t('pt.batchFailed'))
      }
    } catch (e) {
      message.error(t('pt.batchFailedWith', { error: (e as Error).message }))
    } finally {
      setBatchBusy(false)
    }
  }

  return (
    <Space wrap size={4}>
      {/* 导入：隐藏 file input，按钮触发（旧页同款交互，支持连续导入同一文件） */}
      <input
        ref={fileRef}
        type="file"
        accept=".yaml,.yml,.csv,.json"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void doImport(file)
          e.target.value = ''
        }}
      />
      <Button size="small" icon={<ImportOutlined />} onClick={() => fileRef.current?.click()}>
        {t('pt.import')}
      </Button>
      <Dropdown menu={{ items: exportItems, onClick: onExport }}>
        <Button size="small" icon={<DownloadOutlined />}>
          {t('pt.export')}
        </Button>
      </Dropdown>
      <Popover
        open={batchOpen}
        onOpenChange={setBatchOpen}
        trigger={['click']}
        placement="bottomRight"
        title={t('pt.batchTitle')}
        content={
          <Space orientation="vertical" size={8} style={{ width: 300 }}>
            <Space wrap>
              <span style={{ fontSize: 12 }}>{t('pt.type')}</span>
              <Select size="small" style={{ width: 90 }} value={batchType} options={TYPE_OPTIONS} onChange={setBatchType} />
              <span style={{ fontSize: 12 }}>{t('pt.group')}</span>
              <InputNumber size="small" min={1} value={batchGroup} onChange={(v) => setBatchGroup(Number(v ?? 1))} />
            </Space>
            <Input
              size="small"
              value={batchIoas}
              placeholder={t('pt.ioasPlaceholder')}
              onChange={(e) => setBatchIoas(e.target.value)}
            />
            <Space wrap>
              <Button
                size="small"
                type="primary"
                loading={batchBusy}
                onClick={() => void doBatch('enable', queryClient.getQueryData<Point[]>(queryKeys.points()))}
              >
                {t('pt.enable')}
              </Button>
              <Button
                size="small"
                loading={batchBusy}
                onClick={() => void doBatch('disable', queryClient.getQueryData<Point[]>(queryKeys.points()))}
              >
                {t('pt.disable')}
              </Button>
              <Button
                size="small"
                loading={batchBusy}
                onClick={() => void doBatch('group', queryClient.getQueryData<Point[]>(queryKeys.points()))}
              >
                {t('pt.regroup')}
              </Button>
            </Space>
          </Space>
        }
      >
        <Button size="small" icon={<ToolOutlined />}>
          {t('pt.batch')}
        </Button>
      </Popover>
    </Space>
  )
}
