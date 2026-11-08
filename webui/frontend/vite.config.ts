import { copyFileSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import path from 'node:path'

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
/**
 * Carbon 的 styles.css 里 IBM Plex 字体指向 IBM CDN（1.www.s81c.com）：
 *  - 应用 CSP 是 `font-src 'self' data:`，CDN 字体每次渲染都被拦成 console error；
 *  - 离线/内网部署拿不到外网字体，IBM Plex 会整体回退。
 *
 * `@ibm/plex-*` 包已作为 @carbon/styles 的依赖装在本地，且目录结构与 CDN 完全一致
 * （fonts/split/woff2、fonts/complete/woff2、fonts/complete/woff）。构建时把产物 CSS
 * 里的 CDN 字体改写到 `/app/fonts/...`，并把对应文件复制进 outDir（Vite 8 对 `?url`
 * CSS 的 url() 不做包内解析，所以不走 transform 而是在产物层改写）。
 * dev 模式没有 CSP，CDN 字体照常可用，无需处理。
 */
function carbonLocalFonts(): Plugin {
  const needed = new Set<string>()
  const CDN = 'https://1.www.s81c.com/common/carbon/plex/fonts/'
  const RE = new RegExp(`(["']?)${CDN.replace(/\./g, '\\.')}([^"')]+)\\1`, 'g')

  return {
    name: 'iec104-carbon-local-fonts',
    apply: 'build',
    generateBundle(_options, bundle) {
      let hits = 0
      for (const item of Object.values(bundle)) {
        if (item.type !== 'asset' || !item.fileName.endsWith('.css')) continue
        const source = typeof item.source === 'string' ? item.source : item.source.toString()
        if (!source.includes('1.www.s81c.com')) continue
        const rewritten = source.replace(RE, (_m, _q, rest) => {
          hits += 1
          needed.add(rest)
          return `/app/fonts/${rest}`
        })
        item.source = rewritten
      }
      if (hits > 0) console.log(`[carbon-local-fonts] rewrote ${hits} font urls, ${needed.size} files`)
    },
    writeBundle() {
      if (needed.size === 0) return
      const root = fileURLToPath(new URL('.', import.meta.url))
      let copied = 0
      for (const rest of needed) {
        const family = rest.split('/')[0]
        const pkg = { 'IBM-Plex-Sans': 'plex-sans', 'IBM-Plex-Mono': 'plex-mono', 'IBM-Plex-Serif': 'plex-serif', 'IBM-Plex-Sans-Arabic': 'plex-sans-arabic', 'IBM-Plex-Sans-Devanagari': 'plex-sans-devanagari', 'IBM-Plex-Sans-Hebrew': 'plex-sans-hebrew', 'IBM-Plex-Sans-Thai': 'plex-sans-thai', 'IBM-Plex-Sans-Thai-Looped': 'plex-sans-thai-looped' }[family]
        if (!pkg) continue
        // rest = "IBM-Plex-Mono/fonts/split/woff2/x.woff2"；包内是 @ibm/<pkg>/fonts/split/...（无 family 目录）
        const src = path.join(root, 'node_modules', '@ibm', pkg, rest.slice(family.length + 1))
        const dest = path.join(OUT_DIR, 'fonts', rest)
        if (existsSync(dest)) continue
        mkdirSync(path.dirname(dest), { recursive: true })
        copyFileSync(src, dest)
        copied += 1
      }
      console.log(`[carbon-local-fonts] copied ${copied} font files into outDir/fonts`)
    },
  }
}

function cleanOwnOutDir(): Plugin {
  return {
    name: 'iec104-clean-own-outdir',
    apply: 'build',
    buildStart() {
      rmSync(OUT_DIR, { recursive: true, force: true })
    },
  }
}

/**
 * PatternFly 的组件样式映射（`*.mjs`）会逐个 `import './xxx.css'`。
 *
 * 本应用统一加载全量 `patternfly.css`（已包含全部组件、base 与 token，
 * 手写表格类名也依赖它），因此把这些逐组件 CSS 解析到空文件：
 *  - 不重复打包（省约 0.86 MB / 75 kB gzip）；
 *  - 切到经典版时 `<head>` 里不会残留 PF 组件样式。
 *
 * 注意：`.mjs` 内部是**相对路径**导入，所以必须拦 resolveId 而不是 alias。
 */
function emptyPfComponentCss(): Plugin {
  const empty = fileURLToPath(new URL('./src/kit/empty.css', import.meta.url))
  return {
    name: 'iec104-pf-empty-component-css',
    enforce: 'pre',
    resolveId(id, importer) {
      if (!id.endsWith('.css')) return null
      const inPfStyles =
        id.includes('@patternfly/react-styles/css/') ||
        (importer?.includes('@patternfly/react-styles/css/') ?? false)
      return inPfStyles ? empty : null
    },
  }
}

export default defineConfig({
  // aiohttp 在 /app/ 路径下托管构建产物，base 必须与之匹配，
  // 否则产物会去请求 /assets/... 导致 404。
  base: '/app/',
  plugins: [react(), carbonLocalFonts(), emptyPfComponentCss(), cleanOwnOutDir()],
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
    rollupOptions: {
      output: {
        // 只显式隔离 ECharts：它体积最大且只被「趋势图」动态引入，
        // 单独成 chunk 后首屏与主站页都不会下载它。
        // 其余依赖交给 Rollup 按引用关系自动分包（手工分桶易产生循环 chunk）。
        manualChunks(id: string) {
          if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) {
            return 'vendor-echarts'
          }
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    // dev 期把 REST 与 WS 代理到本地后端，避免跨域与手改 BASE
    // （合并模式后端的子站在 /slave 前缀，也要一并代理）
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, ws: true, changeOrigin: true },
      '/slave/api': { target: BACKEND, changeOrigin: true },
      '/slave/ws': { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
})
