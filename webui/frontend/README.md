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
├── vite.config.ts        # base=/app/、outDir=../static/app、dev 代理
├── vitest.config.ts      # 单测配置（jsdom）
├── tsconfig.json
├── package.json / package-lock.json
└── src/
    ├── main.tsx          # 入口：ConfigProvider(dark) + React Query + ErrorBoundary
    ├── App.tsx           # 页面切换 + 全局 WS 桥
    ├── theme.ts          # antd darkAlgorithm 主题
    ├── api/              # REST 客户端 / 类型 / React Query hooks
    ├── ws/               # WS 客户端（断线重连）+ 桥接 hook
    ├── store/            # Zustand（UI 状态 + live 日志缓冲）
    ├── layout/           # AppLayout / ErrorBoundary
    ├── pages/            # StatusPage / LogsPage
    ├── styles/
    └── test/
```

## 与后端的契约

所有数据只经 REST/WS 契约访问后端（方案 R7：前端零 Python 依赖），契约见
[`../api_contract.md`](../api_contract.md)。首版消费：

- `GET /api/status`、`GET /api/points`（状态总览）
- `GET /api/logs`、`GET /api/logs/export`（日志面板）
- `WS /ws`：`snapshot` / `log` 消息

## 构建产物与打包

`npm run build` → `webui/static/app/`（独立子目录，`emptyOutDir: false`，
**不会覆盖**同级的旧原生页 `master.html` / `slave.html` / `js/` / `css/`）。

`build/build_all.py` 在 PyInstaller 打包前会先跑前端构建（`--skip-frontend` 可跳过），
产物随 `webui/static` 一并 `--add-data` 进包。
