# 界面套件（UI Kits）：同地址共存与即时切换

> 决策：2026-11-08，用户要求「同一个地址访问，页面上可以主题切换」，并计划再接入一版
> IBM Carbon。实现为**单文档、多套件、运行时切换**：地址始终是 `/app/`，切换不刷新页面、
> 不改 URL、不断 WS/连接。三套均已实装：**Carbon（默认，2026-11-08 起）**/ PatternFly / 经典版（antd，冻结）。

## 1. 结构

```
src/
├─ main.tsx              # 根入口：数据运行时 + 套件宿主 + 样式表管理
├─ kit/
│  ├─ store.ts           # 当前套件（?kit= → localStorage → 默认 carbon；存量 pf 偏好按未设置处理）
│  ├─ useKitCss.ts       # 按套件挂载/移除全局样式表（<link data-kit-css>）
│  ├─ KitSwitcher.tsx    # 右下角 34px 圆钮 + 展开选项（原生元素，不依赖任何套件）
│  └─ empty.css          # PF 逐组件 CSS 的落点（见 §4）
├─ pf/                   # PatternFly 6 套件
├─ classic/              # 经典版（antd 6，v1.3.1 界面快照）
├─ carbon/               # Carbon 套件（IBM Carbon Design System，@carbon/react 1.120）
│  ├─ CarbonRoot.tsx     # 套件根（只挂 UI，不建 QueryClient/WS）
│  ├─ CarbonApp.tsx      # Header + SideNav + 横幅 + 页面路由 + 主题类挂 <html>
│  ├─ carbon.css         # 补充样式（颜色只引用 --cds-* token）
│  ├─ components/        # 点表/命令面板/弹窗/报文/趋势/网络模拟/子站面板/小件
│  └─ pages/             # 主站/子站/状态/日志/历史/录波/测试中心/多站
└─ api|ws|store|i18n|lib # 共享数据层（只有一份）
```

套件只负责 UI：`PfRoot` / `ClassicRoot` / `CarbonRoot` 都不创建 QueryClient、不建 WS、
不做契约协商，这些由 `src/main.tsx` 常驻，因此切套件不会重连、不会丢缓存。

## 2. 切换行为

| 项 | 行为 |
|---|---|
| 入口 | `/app/#/master`（hash 路由不变） |
| 选择优先级 | `?kit=pf|classic|carbon` → `localStorage["iec104.ui.kit"]` → `carbon`（存量 pf 偏好视为未设置） |
| 切换时机 | 点击后懒加载目标套件 chunk + 目标样式表，**旧套件保持渲染到新样式就绪**，无白屏 |
| 页面状态 | `uiStore.page` + hash 不变，切过去仍停在同一页 |
| 连接状态 | WS/React Query 在根节点常驻，连接与点表缓存不中断 |
| 主题 | 深浅色写 `html[data-theme]`；PF 额外加 `pf-v6-theme-dark`，Carbon 加 `cds--g100/g10`（卸载时移除） |
| 语言 | 共享 `uiStore.locale`，三套 UI 同步 |

## 3. 样式隔离

同一个文档里只允许**当前套件**的全局样式表存在：

| 套件 | 全局样式 | 处理 |
|---|---|---|
| PatternFly | `@patternfly/patternfly/patternfly.css`（含 base/token/全部组件） | `<link data-kit-css>`，切走即移除 |
| PatternFly（补充） | `src/pf/pf.css`（`.mono`、焦点环、紧凑表格） | 同上 |
| 经典版 | `antd/dist/reset.css` + `src/classic/styles/global.css` | 同上 |
| 经典版（组件样式） | antd 6 CSS-in-JS 运行时注入 | 类名命名空间 `.ant-*`，残留无副作用 |
| Carbon | `@carbon/styles/css/styles.css`（含全局 reset 与四套主题 token）+ `src/carbon/carbon.css` | 同上 |

`useKitCss` 的顺序是「先加载新样式，再移除旧样式」，避免切换瞬间无样式。

## 4. PatternFly 逐组件 CSS

PF 的 `*.mjs` 组件样式映射会 `import './xxx.css'`。本应用统一加载全量
`patternfly.css`（手写虚拟表格类名也依赖它），因此 `vite.config.ts` 里的
`emptyPfComponentCss` 插件把这些逐组件 CSS 解析到 `src/kit/empty.css`：

- 避免重复打包（约 −0.86 MB / −75 kB gzip）；
- 切走时 `<head>` 里不会残留 PF 组件样式。

> 若将来改用 PF 的逐组件样式（不加载全量 `patternfly.css`），删除该插件并确认
> `PfPointsTable` 的手写 `pf-v6-c-table` 类名有对应 CSS。

## 5. 经典版（antd）的边界

- 源码来自 `f26cb21`（v1.3.1）的 UI 树，放在 `src/classic/`；
- 数据层不复制：`src/classic/{api,ws,store,i18n,lib}` 都是 **re-export shim**，
  指向共享层，类型检查仍然生效（共享契约变化会在这里报错，而不是静默跑旧逻辑）；
- 已做的 3 处契约适配：`queryKeys.*` 改为函数调用、帧解码改扁平结构
  （`format`/`segments`）、`SlaveQuality` 补 `substituted`；
- **冻结承诺**：经典版不再跟进新功能/新页面，只作为「原界面」对照；
  共享数据层变更后需保持其 `tsc` 通过（单测 22 个文件随之保留）。

## 6. Carbon 套件

`@carbon/react` + `@carbon/styles` 1.119/1.120，与另两套件同等覆盖（8 页 + 全部命令）：

- **主题**：`CarbonApp` 把 `cds--g100`（深）/ `cds--g10`（浅）挂到 `<html>`——
  编译版 CSS 的主题类名是 `cds--g100` 而非 `cds--theme-g100`，且类同时落
  `background/color`；卸载时移除，避免影响其它套件。
- **表格**：与 PF 同方案的虚拟点表（TanStack Virtual + 逐行独立
  `<table class="cds--data-table">` + `measureElement` 实测行高），
  Carbon 默认密度（md）。
- **carbon.css**：只允许引用 `--cds-*` token（配色门禁例外仅 `kit/` 切换器与
  `classic/**`，`carbon/**` 与 PF 一样受门禁约束）。
- **组件替换**：Panel→Tile、Alert→InlineNotification、Label→Tag、
  ExpandableSection→AccordionItem（受控 `open`）、PF Pagination→Carbon Pagination、
  可关闭标签→DismissibleTag（`onClose` + 中文 `dismissTooltipLabel`）。
- **dev 代理**：`vite.config.ts` 的 proxy 补 `/slave/api`、`/slave/ws`
  （合并模式后端的子站前缀），`vite dev/preview` 联调不再 404。
- **字体本地化**：Carbon styles.css 的 IBM Plex 字体指向 IBM CDN；应用 CSP 是
  `font-src 'self'`，CDN 会被拦成 console error 且离线不可用。构建插件
  `carbonLocalFonts` 把产物 CSS 里的 CDN 字体改写到 `/app/fonts/...` 并从
  `@ibm/plex-*` 包复制对应文件（120 个）进 outDir；dev 无 CSP，CDN 照常可用。

## 7. 验证（2026-11-08）

| 门禁 | 结果 |
|---|---|
| 前端单测 | 32 文件 / **133 passed**（共享层 10 + 经典版 22） |
| e2e（仓库根运行） | **43 passed**（`ui-kit.spec.ts` 5 条：默认 Carbon、PF/经典/Carbon 切换、主题跟随、持久化、无残留、主站选中与趋势切页保留；本机 8765 被占用时用 `E2E_PORT_OFFSET=10` 平移端口；运行方式见仓库根：`NODE_PATH=webui/frontend/node_modules webui/frontend/node_modules/.bin/playwright test --config tests/e2e/playwright.config.ts`） |
| 类型检查 / 构建 | `tsc --noEmit` 通过；`vite build` 通过 |
| i18n 清单 | **0 文件 / 0 行**（新增 key 仅 `trend.remove`） |
| 对比度 | 文本 + 非文本（含焦点环）硬失败 0 |
| 视觉基线 | 3 张按 PF 界面重拍（win32；Carbon/经典版不进默认基线，走 e2e 断言） |
| 开发模式 | `vite dev/preview` 下三套件样式均生效，切换无 console error；子站代理已修 |
| exe | Windows onefile 重建（**15.4 MB**，venv 构建）并冒烟：PF/经典版/Carbon 切换、无 console error |
| 后端回归 | **1562 passed**（未改后端，确认无连带影响） |

## 8. 取舍

1. **切换是整棵树卸载/挂载**，不是两棵树同时挂着：页面内局部状态（未提交的表单输入、
   滚动位置）不会跨套件保留；服务端状态与选择页保留。
2. **包体**（切换时才加载对应套件）：PF 全量 CSS 1.86 MB（gzip 166 kB）+ PF chunk
   0.40 MB；经典版 `reset + global` ~4 kB + CSS-in-JS 运行时；Carbon styles.css
   1.2 MB + Carbon chunk 0.29 MB + Plex 字体 ~3.5 MB（仅 Carbon 激活时按需请求）。
   exe 合计 19.0 MB（venv 构建；系统 Python 会带入额外依赖涨到 ~32 MB）。
3. **经典版布局与 PF/Carbon 不一致**（命令面板在右侧 vs 下方）：这是 v1.3.1 的既有差异，
   冻结策略下不强行对齐；PF/Carbon 均为「点表整行 + 命令面板在下」。
4. **内置英文文案**：Carbon Pagination 等复合组件的内置字符串为英文；紧凑模式
   （isCompact 已移除后的最小形态）不出现需要翻译的关键文案，若后续启用页码选择器
   需补 `translateWithId`。
