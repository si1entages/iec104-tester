import { rmSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import type { Plugin } from 'vite'

/**
 * 后端地址（dev 代理目标）。可用 IEC104_BACKEND 覆盖，例如：
 *   IEC104_BACKEND=http://127.0.0.1:8766 npm run dev   # 子站
 */
const BACKEND = process.env.IEC104_BACKEND || 'http://127.0.0.1:8765'

/** 产物目录：webui/static/app（aiohttp 在 /app/ 路径托管） */
const OUT_DIR = fileURLToPath(new URL('../static/app', import.meta.url))

/**
 * 只清空「我们自己的」产物子目录 webui/static/app。
 *
 * `build.emptyOutDir` 保持 `false`，是为了在任何情况下都绝不触碰同级的旧原生页
 * （master.html / slave.html / js/ / css/）。但这样一来 Vite 不会清理旧产物，
 * 每次构建都会残留历史 hash 资源；因此自带一个**精确到 app/** 的预构建清理，
 * 既拿到确定性产物，又把删除范围钉死在 app/ 之内。
 */
function cleanOwnOutDir(): Plugin {
  return {
    name: 'iec104-clean-own-outdir',
    apply: 'build',
    buildStart() {
      rmSync(OUT_DIR, { recursive: true, force: true })
    },
  }
}

export default defineConfig({
  // aiohttp 在 /app/ 路径下托管构建产物，base 必须与之匹配，
  // 否则产物会去请求 /assets/... 导致 404。
  base: '/app/',
  plugins: [react(), cleanOwnOutDir()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    // 独立子目录，绝不覆盖同级的旧原生页（master.html/slave.html/js/css）
    outDir: '../static/app',
    // 关键：static/ 下还有旧原生页，清空 outDir 会误删它们（清理交给 cleanOwnOutDir）
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
