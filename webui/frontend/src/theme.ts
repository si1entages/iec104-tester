import { theme as antdTheme } from 'antd'
import type { ThemeConfig } from 'antd'

/** 工业深色主题：antd darkAlgorithm + 少量 token 定制。 */
export const appTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: '#13c2c2',
    colorInfo: '#13c2c2',
    colorBgLayout: '#10151c',
    borderRadius: 6,
    fontSize: 13,
  },
  components: {
    Layout: {
      headerBg: '#141a22',
      siderBg: '#0b0f14',
      bodyBg: '#10151c',
    },
    Menu: {
      darkItemBg: '#0b0f14',
      darkSubMenuItemBg: '#0b0f14',
    },
  },
}
