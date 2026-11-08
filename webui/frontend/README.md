# webui/frontend — IEC104 Tester 前端工程

Vite 8 + React 19 + TypeScript 7 + Ant Design 6（浅/深双主题）工程。源码在此，`vite build` 产物输出到
`webui/static/app/`，由 aiohttp 在 `/app/` 路径托管（见 `webui/server.py`）。

> T10 只交付脚手架 + 构建链 + 打包/CI 接入，页面为**最小可用首版**（状态总览 / 日志骨架）；
> T11 起补齐数据层与完整页面（主站 / 子站 / 报文 / 趋势）。

## 环境

- Node.js ≥ 18（实测 v22）
- 包管理：npm（`package-lock.json` 已入库，CI 用 `npm ci`）

## 常用命令

```bash
cd webui/frontend

npm ci            # 按锁文件安装依赖（CI / 首次）
npm run dev       # 开发服务器 http://localhost:5173/app/（/api 与 /ws 代理到后端）
npm run build     # 类型检查 + 产物输出到 ../static/app/
npm run preview   # 本地预览构建产物（注意 base=/app/）
npm run typecheck # 仅 tsc --noEmit
npm test          # Vitest 单测
npm run i18n:inventory  # i18n 迁移清单（剩余硬编码中文的文件/行数）
```

### dev 代理目标

开发期把 `/api` 与 `/ws` 代理到后端，默认 `http://127.0.0.1:8765`（主站）。
连接子站（8766）时用环境变量覆盖：

```bash
IEC104_BACKEND=http://127.0.0.1:8766 npm run dev
```

## API 契约校验

后端响应不是“按文档手写类型”就算了，而是三层可执行约束（详见 `webui/api_contract.md` §2.0）：

1. **运行时**：`client.ts` 的 `apiGet/apiPost/apiPostText` 每次都用 `contracts.ts` 的 schema
   校验响应；不符抛 `ApiContractError`（含 `/segments[0].title` 这类 JSON 路径），
   不会让组件读到 `undefined` 后显示含糊失败文案。
2. **编译期**：端点返回类型由 schema 推断；`ContractKeyChecks` 把 schema 字段集与
   `types.ts` 的响应接口逐项比对——接口多/少字段直接 `tsc` 失败。
3. **CI（真实后端）**：`tests/e2e/specs/api-contract.spec.ts` 用同一份 schema 校验
   真实 aiohttp 响应（主站/子站/连接后运行态）。

新增端点或改响应字段时：改 `contracts.ts` ↔ 改 `types.ts` ↔ 跑 `npm run typecheck`
与 Playwright 契约用例，三者缺一不可。

## 主题与配色（可访问性）

> 完整设计规范见 [`../../docs/design_guidelines.md`](../../docs/design_guidelines.md)
> （颜色语义、点表、告警、IEC104 语义映射、命令安全、无障碍、评审清单）。
> 本节只保留工程约定；两者冲突时以设计规范为准。

- **颜色随套件取 token**：PatternFly 用 `--pf-t--global--*` 变量（`pf.css` 的补充样式只引用变量）；
  经典版用 `theme.ts` 的 antd token / `global.css` 的 `html[data-theme]` 变量。
  `tests/test_frontend_style_tokens.py` 会扫描组件里的 `#hex`/`rgb()`，硬编码直接失败
  （例外：`kit/` 的套件切换器与过渡屏、冻结的 `classic/**`，见 `docs/ui_kits.md`）。
- 经典版主色 `colorPrimary = #0a7575`：同时满足「主色文字在白底」与「白字在主色按钮上」
  约 5.5:1（WCAG AA）；亮青 `#13c2c2` 保留为 `colorInfo`，用于深色主题品牌字/信息色。
- **经典版 Tag 预设只用 `success` / `blue` / `default` / `warning` / `error`**：
  `gold`/`cyan`/`purple`/`green` 的预置前景色在浅/深底上只有 2.8~3.4:1，
  新增标签前先用对比度巡检确认。
- `tests/e2e/specs/ui-contrast.spec.ts` 在浅/深主题下逐文本计算对比度
  （普通 4.5:1、大字 3:1，含 `::placeholder`）；<3:1 默认失败，
  `CONTRAST_REPORT=1` 只输出报告。

## 目录结构

```
webui/frontend/
├── index.html            # Vite 入口（加载 src/main.tsx）
├── vite.config.ts        # base=/app/、outDir=../static/app、dev 代理、app/ 精确清理、PF 逐组件 CSS 置空
├── vitest.config.ts      # 单测配置（jsdom）
├── tsconfig.json
├── package.json / package-lock.json
└── src/
    ├── main.tsx          # 根入口：QueryClient + WS 桥 + 契约协商（常驻）；按套件懒加载 UI；主题
    ├── kit/              # 套件选择/切换：store.ts、useKitCss.ts（按需挂 <link>）、KitSwitcher、KitSplash
    ├── pf/               # PatternFly 6 套件：PfRoot + PfApp + components/ + pages/
    ├── classic/          # 经典版（antd 6，v1.3.1 界面冻结）：App/AppLayout/pages + 共享层 re-export shim
    ├── carbon/           # Carbon 套件（@carbon/react）：CarbonRoot/CarbonApp + components/ + pages/
    ├── api/
    │   ├── schema.ts     # SCHEMA_VERSION + 版本不匹配判定（与 events.py 对齐）
    │   ├── contract.ts   # 零依赖运行时 schema DSL + ApiContractError（JSON 路径定位）
    │   ├── contracts.ts  # 全部 REST 响应 schema + ContractKeyChecks 编译期键集比对
    │   ├── types.ts      # 契约类型（api_contract.md 的 TS 投影）
    │   ├── validate.ts   # WS/日志等宽进严出守卫（绝不抛异常）
    │   ├── client.ts     # fetch 封装 / buildUrl / ApiError / 响应 schema 校验
    │   ├── endpoints.ts  # 全部 REST 端点（每个 JSON 响应都必须传 schema）
    │   └── queries.ts    # React Query：queries + 命令 mutations + 失效策略
    ├── ws/
    │   ├── client.ts     # WS 客户端：指数退避重连 + 背压感知
    │   └── useWsBridge.ts# snapshot 先行 + 写入 React Query 缓存
    ├── hooks/useSchemaHandshake.ts
    ├── store/uiStore.ts  # Zustand：**仅** UI 状态（页面 / 连接指示 / 告警）
    ├── lib/ i18n/        # 格式化、点值/趋势、主题偏好、i18n 字典
    └── test/
```

> 多套件的架构、样式隔离与 Carbon 接入步骤见 [`../../docs/ui_kits.md`](../../docs/ui_kits.md)。

## 数据层与状态分层（T11）

- **REST**：`api/endpoints.ts` 覆盖 `api_contract.md` 全部 74 个端点；
  `api/queries.ts` 提供 `useStatusQuery` / `usePointsQuery` / `useLogsQuery` /
  `useLiveLogs` 与命令 `useCommand` / `useCommandNoArgs`（命令返回后自动失效
  `status` / `points`，断线时也能对齐）。
- **WS**：`ws/client.ts` 指数退避重连（1s→30s）+ 发送侧背压检测；
  `ws/useWsBridge.ts` 保证 **snapshot 先行**（重连后先对齐快照，期间增量入缓冲区，
  快照落地后按序回放），并把结果写入 React Query 缓存。
- **状态分层**：服务端数据（状态 / 点表 / 日志）**只存在于 React Query 缓存**；
  Zustand 仅保存 UI 状态（当前页、连接指示、契约/背压告警）。
- **契约版本**：`api/schema.ts::SCHEMA_VERSION` 必须与后端
  `webui/events.py::SCHEMA_VERSION` 一致（由 `webui/contract_check.py` 强制）；
  不一致时界面**告警 + 降级渲染，不崩溃**。
- **运行时校验**：REST 响应走 `api/contract.ts` schema（不符抛 `ApiContractError`）；
  WS/日志等非 REST 载荷走 `api/validate.ts` 的宽进严出守卫（不匹配则忽略，不抛异常）。

## 与后端的契约

所有数据只经 REST/WS 契约访问后端（方案 R7：前端零 Python 依赖），契约见
[`../api_contract.md`](../api_contract.md)。信封形如
`{kind, schemaVersion, ts, data}`（`snapshot` / `frame` / `event` / `log`）。

## 构建产物与打包

`npm run build` → `webui/static/app/`（独立子目录，`emptyOutDir: false`，
**不会覆盖**同级的旧原生页 `master.html` / `slave.html` / `js/` / `css/`）。

`build/build_all.py` 在 PyInstaller 打包前会先跑前端构建（`--skip-frontend` 可跳过），
产物随 `webui/static` 一并 `--add-data` 进包。

## i18n（中/英）

零依赖轻量实现（`src/i18n/`）：

- 词典按界面域分 key（`menu.*` / `status.*` / `logs.*` / `history.*` / `sim.*` …），
  `translate(locale, key, params)` 支持 `{name}` 占位符；en 缺 key 时回退 zh。
- 组件内用 `useT()`，非组件代码（事件回调 / 类）用 `tNow()`；列定义等需要随语言
  切换更新的结构用「工厂 hook」（如 `useLogColumns(t)`）避免模块加载期固化。
- 语言存 `localStorage.iec104_locale`，两套套件的头部都有「中 / EN」切换（共享 `uiStore`）；
  经典版额外联动 antd `ConfigProvider locale`（日期选择器等组件文案）。
- **覆盖全部界面**：应用外壳、认证闸门、主站/子站/多站工作台、状态/日志/历史页、
  网络模拟卡片、共享点表组件（`lib/frame.ts` 的协议名双语对照表以
  `i18n-ignore-file` 标注，不计入清单）；`npm run i18n:inventory` 应为 **0 文件 / 0 行**。
  迁移约定：zh 文案逐字保持不变，既有测试即回归网。
