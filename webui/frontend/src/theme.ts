import { theme as antdTheme } from 'antd'
import type { ThemeConfig } from 'antd'

/**
 * 双主题配置（第二批体验改造 ①）：
 * 深色为默认（工业监控场景），浅色为可切换项。token 定制保持同一主色，
 * 布局配色随算法派生，避免硬编码颜色在另一主题下变死角。
 */

const sharedToken = {
  colorPrimary: '#13c2c2',
  colorInfo: '#13c2c2',
  borderRadius: 6,
  fontSize: 13,
}

/** 工业深色主题：antd darkAlgorithm + 少量 token 定制。 */
export const darkTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    ...sharedToken,
    colorBgLayout: '#10151c',
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

/** 浅色主题：default 算法即浅色（本 antd 版本无独立 lightAlgorithm 导出）。 */
export const lightTheme: ThemeConfig = {
  algorithm: antdTheme.defaultAlgorithm,
  token: {
    ...sharedToken,
    colorBgLayout: '#f5f6f8',
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#ffffff',
      bodyBg: '#f5f6f8',
    },
  },
}
