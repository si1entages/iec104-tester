/**
 * 主站定义表「双击值直接发命令」的类型映射（T21）。
 *
 * 定义表同时承载监视点与命令点：只有可下发命令的类别才允许双击值单元格。
 * - YK（遥控）→ `/api/master/yk`，按点位 subtype 选择单/双命令
 * - YC（遥测/遥调目标）→ `/api/master/setpoint`，按点位 subtype 选择设点类型
 * - STEP（步位置）→ `/api/master/step`
 * - YX / YM 为只监不控，双击值单元格不产生命令
 *
 * 所有命令都只发一帧「执行」请求（`select=false`）：主站引擎会按点表
 * `sbo` 配置自动完成选择-执行两段式，选择失败时不会继续发送执行帧。
 */

import type { Point, SetpointKind, StepRequest, YkRequest } from '../api/types'
import { tNow } from '../i18n'

export type DirectCommandKind = 'yk' | 'setpoint' | 'step'

/** 点位类别 → 双击可下发的命令类型；只监不控的点返回 null。 */
export function directCommandKind(point: Pick<Point, 'type'>): DirectCommandKind | null {
  switch (point.type) {
    case 'YK':
      return 'yk'
    case 'YC':
      return 'setpoint'
    case 'STEP':
      return 'step'
    default:
      return null
  }
}

/** 值单元格悬停提示（仅命令点返回文案）。 */
export function directCommandHint(point: Pick<Point, 'type'>): string | null {
  switch (directCommandKind(point)) {
    case 'yk':
      return tNow('pointCommand.yk')
    case 'setpoint':
      return tNow('pointCommand.sp')
    case 'step':
      return tNow('pointCommand.step')
    default:
      return null
  }
}

/** 点表 subtype → 设点命令类型；未知时回落短浮点（与命令面板默认一致）。 */
export function setpointKindOf(point: Pick<Point, 'subtype'>): SetpointKind {
  if (point.subtype === 'normalized' || point.subtype === 'scaled') return point.subtype
  return 'short_float'
}

/** 遥控点 subtype 是否为双命令。 */
export function isDoubleCommand(point: Pick<Point, 'subtype'>): boolean {
  return point.subtype === 'double'
}

/**
 * 构造遥控请求体。
 *
 * 单命令 state: 0=分/1=合；双命令 state: 1=分/2=合（IEC 60870-5-101/104）。
 * `select=false` 交由后端按点表 SBO 配置自动选择-执行，绝不绕过选择确认。
 */
export function buildYkRequest(point: Pick<Point, 'ioa' | 'subtype'>, on: boolean): YkRequest {
  const double = isDoubleCommand(point)
  return {
    ioa: point.ioa,
    state: double ? (on ? 2 : 1) : on ? 1 : 0,
    select: false,
    double,
  }
}

/** 构建设点请求体（`select=false`，SBO 由后端按点表配置处理）。 */
export function buildSetpointRequest(
  point: Pick<Point, 'ioa' | 'subtype'>,
  value: number,
  kind: SetpointKind = setpointKindOf(point),
): { ioa: number; value: number; kind: SetpointKind; select: false } {
  return {
    ioa: point.ioa,
    value,
    kind,
    select: false,
  }
}

/** 构造升降请求体。 */
export function buildStepRequest(point: Pick<Point, 'ioa'>, up: boolean): StepRequest {
  return { ioa: point.ioa, state: up ? 2 : 1, select: false }
}
