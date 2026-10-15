import type { ReactNode } from 'react'

import { DeleteOutlined } from '@ant-design/icons'
import { Button, Card, Collapse, Input, InputNumber, Space, Switch, Tag, Typography } from 'antd'

import type { DraftStation } from './stationDraft'

interface Props {
  station: DraftStation
  index: number
  /** 管理器运行中：草稿冻结，只能看 */
  frozen: boolean
  onChange: (patch: Partial<DraftStation>) => void
  onRemove: () => void
}

/** 带标题的窄字段（左标题右控件，节省横向空间） */
function Field({ label, width = 200, children }: { label: string; width?: number; children: ReactNode }) {
  return (
    <Space size={6}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
      <div style={{ width }}>{children}</div>
    </Space>
  )
}

/**
 * 单个子站配置卡片（T16 草稿编辑）。
 *
 * 展示 `StationConfig` 的常用字段：站标识/站名/绑定地址/端口/公共地址/最大连接数/
 * 是否自动生成点表（或指定点表文件）/四类点数量/自发上送/自动模拟。
 * `enabled` 是**纯本地**开关（不发给后端），用来表达「本次不启动该站」。
 */
export function StationCard({ station, index, frozen, onChange, onRemove }: Props) {
  const number = (v: number | null | undefined, fallback = 0): number =>
    v === null || v === undefined || !Number.isFinite(Number(v)) ? fallback : Number(v)

  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <Tag color={station.enabled ? 'blue' : 'default'}>{index + 1}</Tag>
          <span className="mono">{station.station_id || '（未命名）'}</span>
          {station.station_name ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {station.station_name}
            </Typography.Text>
          ) : null}
          <Tag className="mono">
            {station.host}:{station.port}
          </Tag>
          <Tag color="purple">CA={station.common_addr}</Tag>
        </Space>
      }
      extra={
        <Space>
          <span style={{ fontSize: 12, color: '#8c8c8c' }}>参与本次启动</span>
          <Switch
            size="small"
            aria-label={`参与本次启动-${station.station_id}`}
            checked={station.enabled}
            // 运行中仍可切换：它表达的是「下一次重建时的参与集合」，
            // 改完会出现「重建管理器以应用」提示（见 MultiPage）
            onChange={(v) => onChange({ enabled: v })}
          />
          <Button
            size="small"
            danger
            type="text"
            icon={<DeleteOutlined />}
            disabled={frozen}
            aria-label={`删除-${station.station_id}`}
            onClick={onRemove}
          >
            删除
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Space wrap size={12}>
          <Field label="站标识" width={180}>
            <Input
              value={station.station_id}
              disabled={frozen}
              placeholder="station_id（唯一、必填）"
              onChange={(e) => onChange({ station_id: e.target.value })}
            />
          </Field>
          <Field label="站名" width={180}>
            <Input
              value={station.station_name}
              disabled={frozen}
              onChange={(e) => onChange({ station_name: e.target.value })}
            />
          </Field>
          <Field label="绑定地址" width={160}>
            <Input
              value={station.host}
              disabled={frozen}
              placeholder="0.0.0.0"
              onChange={(e) => onChange({ host: e.target.value })}
            />
          </Field>
          <Field label="端口" width={120}>
            <InputNumber
              min={0}
              max={65535}
              style={{ width: '100%' }}
              value={station.port}
              disabled={frozen}
              onChange={(v) => onChange({ port: number(v, 2404) })}
            />
          </Field>
          <Field label="公共地址" width={110}>
            <InputNumber
              min={0}
              style={{ width: '100%' }}
              value={station.common_addr}
              disabled={frozen}
              onChange={(v) => onChange({ common_addr: number(v, 1) })}
            />
          </Field>
          <Field label="最大连接" width={110}>
            <InputNumber
              min={0}
              style={{ width: '100%' }}
              value={station.max_connections}
              disabled={frozen}
              onChange={(v) => onChange({ max_connections: number(v, 16) })}
            />
          </Field>
        </Space>

        <Collapse
          size="small"
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: 'points',
              label: '点表与模拟',
              children: (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Space wrap size={12}>
                    <Field label="自动生成点表" width={60}>
                      <Switch
                        size="small"
                        aria-label={`自动生成点表-${station.station_id}`}
                        checked={Boolean(station.auto_generate)}
                        disabled={frozen}
                        onChange={(v) => onChange({ auto_generate: v })}
                      />
                    </Field>
                    {!station.auto_generate ? (
                      <Field label="点表文件" width={280}>
                        <Input
                          value={station.point_table_file}
                          disabled={frozen}
                          placeholder="点表 YAML / CSV 路径"
                          onChange={(e) => onChange({ point_table_file: e.target.value })}
                        />
                      </Field>
                    ) : null}
                  </Space>
                  <Space wrap size={12}>
                    <Field label="YX 数" width={100}>
                      <InputNumber
                        min={0}
                        style={{ width: '100%' }}
                        value={station.yx_count}
                        disabled={frozen}
                        onChange={(v) => onChange({ yx_count: number(v, 100) })}
                      />
                    </Field>
                    <Field label="YC 数" width={100}>
                      <InputNumber
                        min={0}
                        style={{ width: '100%' }}
                        value={station.yc_count}
                        disabled={frozen}
                        onChange={(v) => onChange({ yc_count: number(v, 50) })}
                      />
                    </Field>
                    <Field label="YK 数" width={100}>
                      <InputNumber
                        min={0}
                        style={{ width: '100%' }}
                        value={station.yk_count}
                        disabled={frozen}
                        onChange={(v) => onChange({ yk_count: number(v, 20) })}
                      />
                    </Field>
                    <Field label="YM 数" width={100}>
                      <InputNumber
                        min={0}
                        style={{ width: '100%' }}
                        value={station.ym_count}
                        disabled={frozen}
                        onChange={(v) => onChange({ ym_count: number(v, 10) })}
                      />
                    </Field>
                  </Space>
                  <Space wrap size={16}>
                    <Space size={6}>
                      <Switch
                        size="small"
                        aria-label={`自发上送-${station.station_id}`}
                        checked={Boolean(station.spontaneous_enabled)}
                        disabled={frozen}
                        onChange={(v) => onChange({ spontaneous_enabled: v })}
                      />
                      <Typography.Text style={{ fontSize: 12 }}>自发上送</Typography.Text>
                    </Space>
                    <Space size={6}>
                      <Switch
                        size="small"
                        aria-label={`自动模拟-${station.station_id}`}
                        checked={Boolean(station.simulation_enabled)}
                        disabled={frozen}
                        onChange={(v) => onChange({ simulation_enabled: v })}
                      />
                      <Typography.Text style={{ fontSize: 12 }}>启动后自动模拟</Typography.Text>
                    </Space>
                  </Space>
                </Space>
              ),
            },
          ]}
        />
      </Space>
    </Card>
  )
}
