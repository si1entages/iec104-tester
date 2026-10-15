import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// 单测配置与构建配置分离：构建走 /app/ base，测试不需要。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
    // antd 重型组件（Card/Table/InputNumber/Collapse）在 jsdom 下渲染与
    // 可访问名计算都明显更慢，默认 5s 对集成型用例过紧。
    testTimeout: 20000,
    hookTimeout: 20000,
    // 默认的 `forks` 池会把每个转换后的模块**落盘**到
    // `os.tmpdir()/<nanoid>/<web|ssr>/<sha1>`（见 vitest 内部
    // `createMethodsRPC(..., { cacheFs: true })`），而该临时目录不可配置
    // （vitest 2.x 的 `tmpDir` 是 `join(tmpdir(), nanoid())`，无 config 入口）。
    // 在禁止写系统临时目录的环境（沙箱 / 只读 %TEMP%）下，这个写会抛 EPERM，
    // 表现为**随机的测试文件收集失败**（文件数在 3~5 之间抖动）。
    // `threads` 池走 `createWorkerChannel`（cacheFs: false），不落盘 → 结果确定。
    pool: 'threads',
  },
})
