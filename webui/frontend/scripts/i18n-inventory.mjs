#!/usr/bin/env node
/**
 * i18n 迁移清单（C3 阶段一后剩余的硬编码中文）。
 *
 * 用法（在 webui/frontend 下）：
 *   npm run i18n:inventory
 *
 * 输出：仍含中文 UI 文案的文件与行数（升序排列），以及总数。
 * 说明：
 *  - i18n 目录自身与 *.test.* 不计入；
 *  - 注释（//、块注释、JSX {/* *\/}）不计入；
 *  - 行内标注 `i18n-ignore` 的行不计入（如语言切换的原生名称）。
 * 本脚本不失败退出——它是迁移看板，不是门禁。
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

const SRC = path.resolve(process.cwd(), 'src')
const CJK = /[\u4e00-\u9fff]/
const SKIP_DIRS = new Set(['i18n'])
const SKIP_FILE = /\.test\./

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name)
    const stat = statSync(full)
    if (stat.isDirectory()) {
      if (!SKIP_DIRS.has(name)) out.push(...walk(full))
      continue
    }
    if (/\.(ts|tsx)$/.test(name) && !SKIP_FILE.test(name)) out.push(full)
  }
  return out
}

/** 去掉该行中的注释部分（含跨行块注释状态） */
function stripComments(line, state) {
  // 统一去掉 CRLF 的 \r，否则行尾注释的 `$` 匹配不到
  let s = line.replace(/\r$/, '')
  if (state.inBlock) {
    const end = s.indexOf('*/')
    if (end === -1) return { code: '', state }
    s = s.slice(end + 2)
    state.inBlock = false
  }
  // 完整块注释
  s = s.replace(/\/\*[\s\S]*?\*\//g, '')
  // 块注释开始（跨行）
  const start = s.indexOf('/*')
  if (start !== -1) {
    state.inBlock = true
    s = s.slice(0, start)
  }
  // JSX 注释 {/* ... */}
  s = s.replace(/\{\/\*.*$/g, '')
  // 行注释
  s = s.replace(/\/\/.*$/g, '')
  return { code: s, state }
}

const rows = []
let total = 0
for (const file of walk(SRC)) {
  const lines = readFileSync(file, 'utf8').split('\n')
  const state = { inBlock: false }
  let count = 0
  for (const line of lines) {
    if (line.includes('i18n-ignore')) continue
    const { code } = stripComments(line, state)
    if (!CJK.test(code)) continue
    count += 1
  }
  if (count > 0) {
    rows.push([count, path.relative(SRC, file)])
    total += count
  }
}

rows.sort((a, b) => b[0] - a[0])
console.log('i18n inventory — 仍有硬编码中文 UI 文案的文件：\n')
for (const [count, file] of rows) {
  console.log(`${String(count).padStart(4)}  ${file}`)
}
console.log(`\n合计 ${rows.length} 个文件 / ${total} 行`)
console.log('（阶段一已覆盖：外壳、认证、状态/日志/历史页、网络模拟卡片、共享列宽组件/运行时告警）')
