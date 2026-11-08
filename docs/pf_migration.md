# PatternFly 迁移进度

> 决策：2026-11-08，按 **全量迁移 + PF 默认密度** 推进（用户确认）。
> 现状：**迁移完成** —— `/app/` 默认 PatternFly；e2e 全量 40 passed；视觉基线已按 PF 重拍；
> Windows onefile exe 已重建（含新前端）。
>
> **后续变更（同日晚）**：用户要求「同一个地址、页面上切换界面」，并计划接入 IBM Carbon。
> antd 版已作为**经典版套件**恢复（`src/classic/`，v1.3.1 UI 冻结），Carbon 套件也已实装
> （`src/carbon/`），三套 UI 在同一文档内即时切换；架构与隔离方式见 `docs/ui_kits.md`。
> 本节以下「删除 antd」的描述仅代表当时的迁移收尾状态。

## 1. 策略

不做「适配层」，也不在生产页面上混用两套 UI。采用**并行应用**：

1. PF 应用复用现有数据层（`api/`、`ws/`、`store/`、`i18n/`、`lib/`），只重写 UI；
2. 独立入口 `pf.html` → `/app/pf.html`，与 antd 版互不影响（PF 的全局 CSS 不会污染旧页面）；
3. 页面逐页迁移、逐页验收；
4. 全部页面达到 parity 后，把 `/app/` 的入口切到 PF，删除 antd 依赖与旧组件；
5. 最后改 e2e（`.ant-*` 选择器）与视觉基线。

## 2. 技术选型与实测

| 项 | 结论 |
|---|---|
| 版本 | `@patternfly/react-core` / `react-table` / `react-icons` / `patternfly` **6.7.0** |
| React 19 | ✅ peer 支持 `^19` |
| 深色主题 | ✅ 官方 `html.pf-v6-theme-dark`，与 `uiStore.theme` 双向同步 |
| 表格密度 | PF `variant="compact"` 实测 **行高 38px / 字号 14px / 内边距 8×16**（按用户选择，不做紧凑覆盖） |
| 虚拟滚动 | PF 无内建虚拟化；官方 `react-virtualized-extension` 依赖停维护的 `react-virtualized` → 改用 **`@tanstack/react-virtual` 3.14**，固定列宽 + 绝对定位行 + 表头独立于滚动容器 |
| 10 万行实测 | DOM 仅 **24 行**，`scrollHeight ≈ 3.8M px`，滚到底渲染第 100000 行，无 console error |
| 中文 | 组件内置文案（分页/空态）未使用；自建标签全部走 `i18n` |
| 旧应用影响 | 多入口构建后 `/app/` 仍正常（无 console error，表格/菜单渲染正常） |

## 3. 已完成（Phase 1）

| 模块 | 文件 | 说明 |
|---|---|---|
| 入口 | `pf.html`、`src/pf/main.tsx` | 独立 HTML；`QueryClientProvider` + `useWsBridge()`（复用 WS 快照/增量逻辑） |
| 外壳 | `src/pf/PfApp.tsx` | PF `Masthead` + `PageSidebar` + `Nav`；hash 路由与 `uiStore.page` 同步；中/英切换、深浅主题、角色/运行/WS 状态标签 |
| 点表 | `src/pf/components/PfPointsTable.tsx` | 10 万行虚拟滚动；搜索、类型页签、启用标签、数值右对齐 + 单位、品质中文标签（最多 2 个）、行键盘可达（Enter） |
| 主站工作台 | `src/pf/pages/PfMasterPage.tsx` | 连接表单、连接/断开/总召、点表 + 命令面板（8:4 栅格）、加入趋势、报文/趋势页签 |
| 命令面板 | `src/pf/components/PfCommandPanel.tsx` | YK（单/双、SBO 选择/两段式/单帧/撤销、带时标）、设点（3 种）、系统召唤（站 20 + 组 1–16）、累计量召唤、对时、复位、测试、升降、比特串、延时、读、参数（4 种）、文件（目录/选择/请求）；结果用面板内联 Alert |
| 报文查看器 | `src/pf/components/PfFrameViewer.tsx` | 方向/格式/最小长度/关键字筛选、暂停冻结、清空、首屏 `/api/recent` 预热；HEX 悬停 300ms 逐段翻译（复用 `/api/frames/decode` 与缓存） |
| 趋势图 | `src/pf/components/PfTrendChart.tsx` | ECharts 时间轴、`lttb` 降采样、点位标签删除/清空；配色从 PF CSS 变量解析（canvas 不认 `var()`） |
| 状态总览 | `src/pf/pages/PfStatusPage.tsx` | 四张统计卡 + 运行信息 `DescriptionList` + 只读点表 |
| 子站工作台 | `src/pf/pages/PfSlavePage.tsx` + `PfSlaveConnectionPanel` / `PfManualSetPanel` / `PfResponsePanel` / `PfSimulationPanel` / `PfTestInjectionPanel` | 四页签；角色切换按 `/api/schema` 的 `roles` + `slaveApiPrefix` 自动走 `/slave/api` |
| 日志 | `src/pf/pages/PfLogsPage.tsx` | 实时 + 历史合并去重、级别/分类/关键字过滤、暂停冻结、清空、导出、客户端分页 |
| 历史 | `src/pf/pages/PfHistoryPage.tsx` | 统计头、数据/报文页签、时间范围/类型/IOA/方向/条数、查询/重置/导出、客户端分页 |
| 录波 | `src/pf/pages/PfCapturePage.tsx` | 录制启停/暂停、文件列表（加载/下载/导出 pcap）、回放控制与进度、帧表分页、筛选项 |
| 测试中心 | `src/pf/pages/PfTestCenterPage.tsx` | 脚本多选、运行/停止、实时日志、报告下载 |
| 多站 | `src/pf/pages/PfMultiPage.tsx` | 草稿增删与字段编辑、参与开关、整体启动/停止、聚合状态表 |
| 占位页 | `src/pf/pages/PfPlaceholder.tsx` | 未迁移页面明确标注，不留空白 |

子站页功能实测（`--mode both`，真实 TCP）：启动监听 → 监听中；点表选中 → 手动置数 IOA 跟随并下发成功；
应答行为（品质注入 IV）应用成功；模拟控制启动/停止成功；请求全部落在 `/slave/api/*`；无 console error。

## 4. 待迁移

全部完成：

- e2e：`.ant-*` 选择器改为 `data-testid` / PF 类名（`point-row`、`points-scroll`、`log-row`、`history-row`、`multi-card`、`test-script`、`frame-row`、`.pf-v6-c-nav__link` 等），视觉/对比度/非文本/巡检全部跑通；
- antd：`src/pages`、`src/components`、`src/layout`、`src/theme.ts`、旧入口与对应单测已删除，`antd` / `@ant-design/icons` 从依赖移除；
- 单测：保留数据层/i18n/lib 等与 UI 库无关的 60 个用例；
- 视觉基线：`__screenshots__/win32` 三张按 PF 重拍；
- 打包：Windows onefile 重建并冒烟（PF 页面、无 `.ant-*` DOM、8 个菜单、点表行渲染、无 pageerror）。
- 迁移期补齐：`PfAuthGate`、外壳横幅、`PfNetworkSimCard`、`PfPointCommandDialog`、角色菜单过滤、`pf.css` 焦点环。

## 5. 切换前的验收门禁

- PF 应用补一套 `pf-audit`：布局裁切 / 横向溢出 / console error / 失败请求（可复用现有 `ui-audit` 的断言逻辑，只换选择器）；
- 对比度：PF 组件在浅/深主题下跑一遍 WCAG AA（PF token 通常达标，但自建 Label 组合需实测）；
- 点表 10 万行性能与滚动流畅度（当前只验证了 DOM 行数与可达性）；
- 视觉基线：切换后用 PF 版重拍 `__screenshots__`；
- e2e：66 处 `.ant-*` 选择器改为 PF 类名或 `data-testid`（建议优先加 `data-testid`，降低对实现类的耦合）。

## 6. 风险

1. **密度**：38px 行高比原 32px 少约 4 行/屏；若后续觉得太松，可在 PF token 层做紧凑覆盖（`--pf-t--global--spacer--*` + 表格 padding），不需要改组件。
2. **虚拟化自建**：TanStack Virtual 方案需自己维护列宽/表头/键盘；已用 10 万行验证可行，但没有 PF 官方的无障碍表格语义（`role="grid"` 等需补）。
3. **i18n**：PF 内置文案是英文且不接 `ConfigProvider`，凡使用其分页/空态等复合组件的页面都要自己包一层。
4. **双份代码期**：迁移完成前两套 UI 并存，任何数据层/契约变更都要双方可用（当前共享数据层已满足）。
