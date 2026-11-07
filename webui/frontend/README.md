# webui/frontend — IEC104 Tester 前端工程（T10 脚手架）

Vite + React 18 + TypeScript + Ant Design 5（暗色）工程。源码在此，`vite build` 产物输出到
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

## 目录结构

```
webui/frontend/
├── index.html            # Vite 入口
├── vite.config.ts        # base=/app/、outDir=../static/app、dev 代理、app/ 精确清理
├── vitest.config.ts      # 单测配置（jsdom）
├── tsconfig.json
├── package.json / package-lock.json
└── src/
    ├── main.tsx          # 入口：ConfigProvider(dark) + React Query + antd App + ErrorBoundary
    ├── App.tsx           # 页面切换 + 契约协商 + 全局 WS 桥
    ├── theme.ts          # antd darkAlgorithm 主题
    ├── api/
    │   ├── schema.ts     # SCHEMA_VERSION + 版本不匹配判定（与 events.py 对齐）
    │   ├── types.ts      # 契约类型（api_contract.md 的 TS 投影）
    │   ├── validate.ts   # 零依赖运行时校验（宽进严出、绝不抛异常）
    │   ├── client.ts     # fetch 封装 / buildUrl / ApiError
    │   ├── endpoints.ts  # 全部 REST 端点（74 个）
    │   └── queries.ts    # React Query：queries + 命令 mutations + 失效策略
    ├── ws/
    │   ├── client.ts     # WS 客户端：指数退避重连 + 背压感知
    │   └── useWsBridge.ts# snapshot 先行 + 写入 React Query 缓存
    ├── hooks/useSchemaHandshake.ts
    ├── store/uiStore.ts  # Zustand：**仅** UI 状态（页面 / 连接指示 / 告警）
    ├── layout/           # AppLayout / ErrorBoundary
    ├── pages/            # StatusPage / LogsPage
    ├── styles/
    └── test/
```

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
- **运行时校验**：`api/validate.ts` 以零依赖守卫函数过滤脏数据，
  不匹配的载荷直接忽略而非抛出异常。

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
- 语言存 `localStorage.iec104_locale`，头部「中 / EN」切换，并联动 antd
  `ConfigProvider locale`（日期选择器等组件文案）。
- **覆盖全部界面**：应用外壳、认证闸门、主站/子站/多站工作台、状态/日志/历史页、
  网络模拟卡片、共享点表组件（`lib/frame.ts` 的协议名双语对照表以
  `i18n-ignore-file` 标注，不计入清单）；`npm run i18n:inventory` 应为 **0 文件 / 0 行**。
  迁移约定：zh 文案逐字保持不变，既有测试即回归网。
