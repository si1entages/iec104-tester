import { describe, expect, it } from 'vitest'

import { DICTIONARIES, translate } from './index'

describe('i18n 字典', () => {
  it('zh/en 键集合完全一致（防止单边漏翻）', () => {
    expect(Object.keys(DICTIONARIES.en).sort()).toEqual(Object.keys(DICTIONARIES.zh).sort())
  })

  it('占位符按参数替换', () => {
    expect(translate('zh', 'history.view', { n: 3 })).toBe('视图 3')
    expect(translate('en', 'history.view', { n: 3 })).toBe('View 3')
    expect(translate('zh', 'header.dropped', { n: 12 })).toBe('后端背压丢帧 12 条')
    expect(translate('en', 'header.dropped', { n: 12 })).toBe(
      'Backend backpressure dropped 12 frames',
    )
  })

  it('未知 locale 回退 zh', () => {
    // @ts-expect-error 故意传入非法 locale，验证回退
    expect(translate('fr', 'menu.logs')).toBe('日志')
  })

  it('zh 文案与迁移前保持一致（既有测试依赖）', () => {
    expect(translate('zh', 'menu.master')).toBe('主站工作台')
    expect(translate('zh', 'logs.backendTotal', { n: 42 })).toBe('后端累计 42')
    expect(translate('zh', 'history.dataCount', { n: 2 })).toBe('数据 2')
    expect(translate('zh', 'sim.notInstalled')).toBe('引擎未启动')
    expect(translate('zh', 'error.title')).toBe('界面渲染出错')
  })
})
