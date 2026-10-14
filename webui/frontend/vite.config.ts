import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * 后端地址（dev 代理目标）。可用 IEC104_BACKEND 覆盖，例如：
 *   IEC104_BACKEND=http://127.0.0.1:8766 npm run dev   # 子站
 */
const BACKEND = process.env.IEC104_BACKEND || 'http://127.0.0.1:8765'

export default defineConfig({
  // aiohttp 在 /app/ 路径下托管构建产物，base 必须与之匹配，
  // 否则产物会去请求 /assets/... 导致 404。
  base: '/app/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    // 独立子目录，绝不覆盖同级的旧原生页（master.html/slave.html/js/css）
    outDir: '../static/app',
    // 关键：static/ 下还有旧原生页，清空 outDir 会误删它们
    emptyOutDir: false,
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    port: 5173,
    // dev 期把 REST 与 WS 代理到本地后端，避免跨域与手改 BASE
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
})
