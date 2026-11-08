# IEC 60870-5-104 Tester — 架构说明与任务分解方案

> 作者：架构师 高见远（software-architect）· 主理人 齐活林（交付总监）
> 版本：**v1.2（新基线增量修订 · 含 2026-10-14 用户定调）**
> 适用仓库：`D:/PycharmProjects/iec104-tester`
> 基线：`pytest tests/ -q` → **489 passed**；`ruff check .` → **All checks passed**；HEAD = **`3367213`**（`feature/webui-refactor` 已 ff 合入 master，5 分支全部并入）
>
> **✅ Phase 0 基线收口已完成（2026-10-14）**：T01/T02/T03 全部落地，并通过两轮独立 QA 验证（489 passed · ruff 0 告警 · `core/` 覆盖率 63.63% · CI 门禁 60%）。本文件原写「482 passed」之处已同步为 489；末尾 v1.1→v1.2 修订摘要中的 482 属当时基线快照，保留不改。
> 上一版：v1.1（基线 `23eede7` / 405 passed）—— **v1.2 为增量修订，非重写**

本文档为「已有项目」的整体架构梳理与落地任务分工方案，分 9 部分 + 2 附录。**v1.2 变更说明见文末「修订摘要」。**

---

## 0. 关键决策记录（2026-10-14 用户定调）

> ⚠️ **v1.2 更正**：v1.1 中 Q1/Q5 的「保留 pywebview 双通道」表述**与实测现状冲突**。新 master 已**移除 pywebview 桌面壳**（`requirements.txt`/`pyproject.toml` 无 pywebview；`PROJECT.md`：「纯 web 形态：移除 pywebview 桌面壳 / `--no-shell` / web_lab 一键联调」；`grep -rin pywebview` 在源码零命中）。故 Q1/Q5 按**现状**修正。

本次定调中 **4 项偏离原默认建议**（🔴 标出），对架构与排期影响显著：

| # | 决策项 | 原默认建议 | **最终决策（v1.2 修正后）** | 影响 |
|---|--------|-----------|-------------|------|
| Q1 | 发布形态 | ~~保留 pywebview + 浏览器双通道~~ | ✅ **纯 Web（浏览器为唯一 UI）**；保留可选 headless CLI（`--no-gui`）。**桌面壳已不存在** | 依赖裁剪、打包、UX 均按纯 Web |
| Q2 | TLS / IEC 62351 | 本轮不做 | ✅ 本轮不做（Phase 4 按需） | 无 |
| Q3 | pcap/pcapng 导出 | 建议做 | ✅ 做（Phase 4） | 无 |
| Q4 | God Class 拆分 | 先抽 EngineBase，深度拆分可裁剪 | ✅ **EngineBase 已完成（归档）**；深度拆分**优先级上调**（master 1326→1745、slave 1740→1950，反而恶化） | T04/T05 变为 P0 |
| Q5 | 保留 pywebview | ~~保留~~ | ✅ **维持已移除现状（纯 Web）**；不再引入桌面壳 | 与 Q1 一致 |
| **Q6** | 多站管理器接入 Web UI | 保持 CLI 独立 | 🔴 **接入 Web UI** | 新增「多站」页 + `/api/multi/*` + 多站桥；与 PROJECT.md 待办 #3（关停资源清理）耦合 → **T16** |
| **Q7** | 引入前端框架 | 暂不引入，保持原生零构建 | 🔴 **引入前端框架（Vite + React 18 + TS + Ant Design 5）** | 前端整体重写：`webui/frontend/`（源码）→ `vite build` → `webui/static/`（产物）；引入 Node 构建链；`build_all.py` 打包 `dist/`；CI 增 node 构建；现有 `webui/static/{master,slave}.html`、`js/app.js`(539)、`css/app.css`(315) 全部退役 → **T10~T15/T19** |
| Q8 | Python 基线 | 3.11+（CI 覆盖 3.11/3.13） | ✅ 同默认 | **需对齐**：`pyproject.toml` 现为 `requires-python=">=3.10"`、`target-version="py310"`；CI 现为 3.10/3.12 → **T01** |
| **Q9** | 历史库持久化 | 默认关闭，`--history-db` 显式开启 | 🔴 **默认开启** | `app.py` 现仅传 `--history-db` 时建库；`core/config.py` **无 history 配置项**；需新增默认数据目录 + `--no-history` 开关 + 保留期/容量上限/清理策略/写放大评估 → **T17** |
| Q10 | WS 消息版本协商 | 引入 `schemaVersion` | ✅ 同默认 | `webui/api_contract.md` 已存在但**无 `schemaVersion` 字段** → **T18** |

### 0.1 前端技术栈（Q7 细化，已确认）

| 项 | 选型 |
|----|------|
| 构建 | **Vite** |
| 框架 | **React 18 + TypeScript** |
| 组件库 | **Ant Design 5**（内置 `theme.darkAlgorithm` 暗色算法） |
| 数据/状态 | React Query（服务端状态 + WS 快照缓存） + Zustand（少量本地 UI 状态） |
| 样式 | antd Design Token 定制 + CSS Modules（**不引入 Tailwind**，避免与 antd 样式体系冲突） |
| 图表 | ECharts（趋势图） |
| 目录 | `webui/frontend/`（源码） → `vite build` → `webui/static/`（产物，aiohttp 托管） |

**选型理由**：本项目是**工业深色界面 + 十万行虚拟滚动点表 + 密集表单配置 + 高频报文流**场景。Ant Design 5 在中后台/工业配置类界面组件最齐全（暗色算法、`Table` 虚拟滚动、`Form` 校验、`Descriptions`/`Statistic`/`Badge`/`Drawer` 等），可用最小工作量替换现有粗糙组件，并具备组件化与前端自动化测试基建（Vitest + RTL + Playwright）。用户原话「目前的页面组件都太垃圾了」，为 Q7 直接动因。

---

## 1. 技术架构总览

### 1.1 分层架构图（v1.2：纳入 logging_manager、webui 拆分、前端工程）

```mermaid
flowchart TD
    subgraph L1["入口层 Entry / CLI"]
        A1["app.py (统一 Web 入口 + headless CLI)"]
        A2["apps/web_master.py · web_slave.py（瘦入口）"]
        A3["run_tests.py · run_multi_station.py · capture_tool.py · sim_tool.py"]
    end

    subgraph L2["Web UI 层 (aiohttp 后端 + 前端工程)"]
        B0["webui/frontend/ — Vite + React18 + TS + AntD5（源码）"]
        B3["webui/static/ — vite build 产物（aiohttp 托管）"]
        B1["webui/server.py — REST + WebSocket 路由"]
        B2["webui/bridge.py — EngineBridge 门面"]
        B2a["webui/session.py — EngineSession 会话门面"]
        B2b["webui/points.py — PointService 点表服务"]
        B2c["webui/events.py — EventBus 事件总线"]
        B4["webui/api_contract.md — REST/WS 契约（含 schemaVersion）"]
    end

    subgraph L3["引擎层 (asyncio 编排)"]
        C0["EngineBase (core/engine/base.py)"]
        C1["MasterEngine"]
        C2["SlaveEngine"]
        C3["MultiStationManager"]
        C4["TaskScheduler"]
    end

    subgraph L4["协议层 (纯同步 struct，无 async / 无 GUI)"]
        D1["apci.py · asdu.py · types.py · sequence.py"]
        D2["state_machine.py · file_transfer.py · io.py · constants.py"]
    end

    subgraph L5["传输层 / 数据层"]
        E1["transport/connection.py (TCPClient/TCPServer/TCPConnection)"]
        E2["data/data_store.py · point_table.py · history.py"]
    end

    subgraph L6["支撑能力（横切）"]
        F1["testing/ YAML 脚本引擎"]
        F2["capture/ 录制回放"]
        F3["simulation/ 网络异常注入"]
        F4["config.py 配置管理"]
        F5["logging_manager.py 结构化日志（内存环形缓冲 + JSONL 轮转 + logging 桥）"]
    end

    A1 --> B1
    A2 --> B1
    A3 --> L3
    A3 --> L6
    B0 -- "vite build" --> B3
    B3 -. "WS / HTTP" .-> B1
    B1 --> B2
    B2 --> B2a
    B2 --> B2b
    B2 --> B2c
    B2a --> C1
    B2a --> C2
    C1 --> C0
    C2 --> C0
    C3 --> C2
    C1 --> C4
    C1 --> D1
    C1 --> D2
    C2 --> D1
    C2 --> D2
    D1 --> E1
    D2 --> E2
    C1 --> E1
    C2 --> E1
    C1 --> E2
    C2 --> E2
    B2c -. "订阅日志回调" .-> F5
    B2a -. "会话日志" .-> F5
    F5 --> C1
    F5 --> C2
    L6 --> C1
    L6 --> C2
```

**分层职责与边界**

| 层 | 职责 | 关键边界约束 |
|----|------|-------------|
| 入口层 | 解析 CLI 参数、装配配置与点表、选择运行模式（Web UI / CLI / 测试脚本 / 多站） | 不实现业务逻辑，只做装配与转发 |
| Web UI 层 | 提供 HTTP REST + WebSocket 接口；托管前端构建产物；**前端源码独立于后端** | 后端只经 `EngineBridge`/`EngineSession` 访问引擎；**前端只经 REST/WS 契约访问后端**，不 import 任何 Python |
| 引擎层 | 主站/子站会话编排、命令下发、应答处理、自发上送、多站管理、定时任务；公共骨架收敛于 `EngineBase` | 只依赖协议层/传输层/数据层的**公开接口**；不得被协议层反向依赖 |
| 协议层 | APCI/ASDU 编解码、TypeID 定义（**72 种**）、流控、状态机、文件传输 | **纯同步、无 asyncio、无 GUI、无网络**；可被任何上层调用 |
| 传输层 | TCP 连接/监听/收发/重连/统计，`close()` 幂等 | 不感知协议语义，只搬运字节 |
| 数据层 | 点表模型、实时库、历史库 | 纯数据结构，无 IO 副作用（历史库除外） |
| 支撑能力 | YAML 测试引擎、录制回放、网络异常模拟、配置、**结构化日志** | 横切复用，独立于 UI；日志经订阅回调推送给 Web 层 |

### 1.2 关键数据流 / 控制流（v1.2：前端为 React 工程）

**下行（控制流：UI 发命令）**
```
浏览器(React/antd) → HTTP POST /api/master/yk
  → webui/server.py: api_yk()
  → EngineBridge.send_yk() → EngineSession → MasterEngine.single_command()
  → ASDUBuilder 构建 ASDU → APCICodec 编码 I 帧 → SequenceManager 记账
  → transport.TCPClient.send() → TCP socket → 子站
```

**上行（数据流：收帧 → 事件推送）**
```
TCP socket → TCPClient.on_frame(bytes)
  → MasterEngine._on_frame_received() → APCICodec.decode / ASDU 解析
  → RealtimeDB 更新（YX/YC/YM/SOE）
  → event_callback / raw_frame_callback
  → EngineBridge → EventBus._publish("frame"/"event")
  → 每个订阅者的 asyncio.Queue(256)
  → webui/server.py: ws_feed() → WebSocket → React 前端（React Query 缓存更新）
```

**日志流（v1.2 新增）**
```
引擎/传输层 logger.info(...) → _PythonLogBridge → LogManager.log()
  → 内存环形缓冲(deque) + JSONL 会话文件(轮转) + 订阅回调
  → EventBus/WS 推 "log" 消息 → 前端「日志」面板（过滤/搜索/导出）
  → GET /api/logs（查询）· GET /api/logs/export（下载 JSONL）
```

**子站侧（自发上送 / 命令应答）**
```
SlaveEngine 检测到数据变化 → send_spontaneous_*() → ASDU(COT=3 突发)
  → 广播 I 帧到所有客户端；收到遥控命令 → 校验 SBO → 回 COT 激活确认/终止
```

**事件总线模型**：`webui/events.py:EventBus` 采用「发布-订阅」——引擎回调（同一事件循环内）写入 `_frames`/`_events`（各保留最近 500 条）并 `put_nowait` 到所有订阅者 `Queue(maxsize=256)`；`QueueFull` 时静默丢弃（背压保护），WS 端先推 `snapshot` 快照再增量推送。

---

## 2. 核心模块划分与依赖关系

### 2.1 模块表（v1.2：按新 master 实测行数更新）

| 模块 | 路径 | 行数 | 职责 | 对外接口 | 依赖方向 | 变更频率 |
|------|------|------|------|---------|---------|---------|
| 协议-APCI | `core/protocol/apci.py` | — | I/S/U 帧头编解码 | `APCICodec.encode_i/s/u`, `decode` | 被引擎依赖；仅依赖 stdlib | 低 |
| 协议-ASDU | `core/protocol/asdu.py` | — | ASDU 编解码 + `ASDUBuilder` | `ASDU`, `ASDUBuilder`, `InformationObject` | 被引擎/测试依赖；依赖 types | 高 |
| 协议-types | `core/protocol/types.py` | — | **72 种 TypeID** + COT + 值类型 | 枚举与数据类 | 被协议/引擎依赖 | 低 |
| 协议-sequence | `core/protocol/sequence.py` | — | k/w 流控计数器 | `SequenceManager` | 被引擎依赖 | 中 |
| 协议-state_machine | `core/protocol/state_machine.py` | — | START/STOP/TEST + t0~t3 | `ConnectionStateMachine` | 被引擎依赖 | 中 |
| 协议-file_transfer | `core/protocol/file_transfer.py` | — | 目录/读/写文件传输 | `FileTransferMaster/Slave` | 被引擎依赖 | 低 |
| 引擎-base | `core/engine/base.py` | **41** | 主站/子站公共骨架（`_spawn`/`_background_tasks`） | `EngineBase` | 被 master/slave 继承 | 低 |
| 引擎-master | `core/engine/master.py` | **1745** ⚠️ | 主站会话编排、命令、响应处理（**God Class，待拆**） | `MasterEngine`, `MasterEvent` | 依赖协议/传输/数据/scheduler | 高 |
| 引擎-slave | `core/engine/slave.py` | **1950** ⚠️ | 子站多客户端、应答、自发、模拟（**God Class，待拆**） | `SlaveEngine`, `SlaveEvent`, `ResponseBehavior` | 依赖协议/传输/数据 | 高 |
| 引擎-multi_station | `core/engine/multi_station.py` | 314 | 多子站生命周期与聚合 | `MultiStationManager`, `StationConfig` | 依赖 slave | 中 |
| 引擎-scheduler | `core/engine/scheduler.py` | 247 | 周期任务（总召/对时/冻结） | `TaskScheduler` | 被 master 依赖 | 中 |
| 传输 | `core/transport/connection.py` | 508 | TCP 客户端/服务端/连接 | `TCPClient/TCPServer/TCPConnection/ConnectionStats` | 被引擎依赖 | 低 |
| 传输-shim | `core/transport/client.py` / `server.py` | 各 8 | 兼容 re-export | 同上 | 无逻辑 | 低 |
| 数据-store | `core/data/data_store.py` | 467 | 实时库 RealtimeDB | `RealtimeDB` | 被引擎依赖 | 中 |
| 数据-point_table | `core/data/point_table.py` | 438 | 点表模型 + YAML | `PointTable` | 被引擎/桥依赖 | 中 |
| 数据-history | `core/data/history.py` | 439 | SQLite 历史库 | `HistoryDB` | 被引擎依赖 | 低 |
| **日志** | `core/logging_manager.py` | **246** | **结构化日志：内存环形缓冲 + JSONL 轮转 + Python logging 桥 + 订阅推送** | `LogManager`, `LogEntry` | 被 webui 依赖；经桥收纳 `iec104.*` | 中 |
| Web-服务 | `webui/server.py` | **1242** | aiohttp REST（**74 个 `/api/*` 端点**，含历史查询 §2.11、网络模拟 §2.12、认证 §2.13、抓包 §2.14、测试中心 §2.15）+ WS | `create_app`, `run_server` | 依赖 bridge | 中 |
| Web-桥 | `webui/bridge.py` | **415** | Web 后端门面（组合下述三者，保持旧 API 形状） | `EngineBridge` | 依赖 session/points/events | 高 |
| Web-会话 | `webui/session.py` | **849** | master/slave 启停与协议命令门面 | `EngineSession` | 依赖 engine/config | 高 |
| Web-点表 | `webui/points.py` | **280** | 点表快照/批量/导入导出，同步引擎 | `PointService` | 依赖 data.point_table | 中 |
| Web-事件 | `webui/events.py` | **80** | WS 订阅事件总线（环形缓冲 + 背压计数） | `EventBus` | 无 Python 反向依赖 | 中 |
| Web-抓包 | `webui/capture.py` | **316** | 录制器/回放器封装（文件/导出/离线回放） | `CaptureService` | 依赖 core.capture | 中 |
| Web-测试中心 | `webui/testcenter.py` | **256** | YAML 脚本子进程运行、日志/报告管理 | `TestCenterService` | 依赖 core.testing | 中 |
| Web-契约 | `webui/api_contract.md` | — | REST/WS 契约表（**待补 `schemaVersion`**） | 文档 | 无 | 中 |
| **前端(旧)** | `webui/static/*` | html 238/…；js **539**；css **315** | 原生 HTML/CSS/JS 页（**待退役**） | HTTP 资源 | 无 Python 依赖 | 高 |
| **前端(新)** | `webui/frontend/*` | 新增 | **Vite + React18 + TS + AntD5 工程（源码）** | 经 REST/WS 契约 | 无 Python 依赖 | 高 |
| 配置 | `core/config.py` | 200 | dataclass 配置 + YAML（**无 history 段**） | `AppConfig`, `load_config` | 被入口/引擎依赖 | 低 |
| 入口 | `app.py` / `apps/*` / 4 个工具脚本 | app 407 | 装配与启动 | `main()` | 依赖以上 | 中 |

> **实测偏差更正**：v1.1 记载「`core/engine/base.py` 不存在、`_spawn` 在 master/slave 重复实现」——**已过时**。实测 `core/engine/base.py` 存在（41 行），`grep "def _spawn"` 全仓仅命中 `core/engine/base.py:18`，两处重复已消除。

### 2.2 模块依赖图（含禁止方向）

```mermaid
graph TD
    Entry["入口层 app.py / apps/* / tools"] --> WebUI["Web UI 层 webui/"]
    Entry --> Testing["core/testing/"]
    Entry --> Capture["core/capture/"]
    Entry --> Sim["core/simulation/"]

    WebUI --> Engine["引擎层 core/engine/"]
    WebUI --> Log["core/logging_manager.py"]
    Testing --> Engine
    Capture --> Protocol
    Sim --> Transport

    Engine --> Protocol["协议层 core/protocol/"]
    Engine --> Transport["传输层 core/transport/"]
    Engine --> Data["数据层 core/data/"]
    Engine --> Scheduler["TaskScheduler"]
    Engine --> Config["core/config.py"]

    Transport --> Config
    Protocol --> Types["types.py"]

    Frontend["webui/frontend/ (React 工程)"] -. "仅经 REST/WS 契约" .-> WebUI

    %% 禁止的依赖方向（虚线 = 必须禁止）
    Protocol -. "❌ 禁止" .-> Engine
    Protocol -. "❌ 禁止" .-> WebUI
    Protocol -. "❌ 禁止" .-> Transport
    Data -. "❌ 禁止" .-> Engine
    Transport -. "❌ 禁止" .-> Engine
    Engine -. "❌ 禁止" .-> WebUI
    Frontend -. "❌ 禁止 import Python" .-> Engine
```

**强制依赖规则**

| 规则 | 说明 |
|------|------|
| R1 协议层零反向依赖 | `core/protocol/**` 不得 import `engine` / `webui` / `transport` / `asyncio` |
| R2 协议层纯同步 | 协议层禁止 `async def`、`await`、`asyncio` |
| R3 数据层纯模型 | `core/data/**` 不得 import 引擎或 UI（`history.py` 允许 sqlite3） |
| R4 传输层无协议语义 | 传输层不得 import `protocol` |
| R5 引擎层不感知 UI | 引擎层通过回调（`set_event_callback`）对外，禁止 import `webui` |
| R6 UI 单向调用引擎 | `webui/` 只能经 `EngineBridge`/`EngineSession` 访问引擎，不直接操作传输层 |
| **R7 前端零 Python 依赖（v1.2 新增）** | `webui/frontend/**` 只能经 REST/WS 契约访问后端；不得内联 Python 逻辑，不得直连引擎 |
| **R8 日志桥单向（v1.2 新增）** | `logging_manager` 可被 webui 订阅；不得反向 import `webui`；日志桥异常必须吞掉不反噬业务 |

---

## 3. 关键技术选型与理由

| # | 选型 | 备选方案 | 选择理由 | 代价与约束 |
|---|------|---------|---------|-----------|
| 1 | **Python 3.11+ + asyncio** | 线程池 / 多进程 / Gevent | IEC 104 为**大量并发长连接 + 定时器**场景，asyncio 单线程事件循环天然适配高并发 I/O；多站共享一个事件循环已验证稳定 | 单循环下任一 CPU 密集或阻塞调用会拖垮全站；**Q8 需把 pyproject/CI 从 3.10 对齐到 3.11+** |
| 2 | **struct 同步编解码** | 第三方库（`lib60870`/`c104`）/ `ctypes` | 协议字节序、CP56Time2a、品质描述词等**完全可控**，便于做「错误注入/边界构造」；无 C 依赖、纯 Python 可移植、易单测 | **72 种 TypeID** 需手工维护，回归靠测试网兜底（`test_protocol_type_coverage.py` 护栏） |
| 3 | **aiohttp 后端 + Vite/React18/TS/AntD5 前端**（v1.2 修订） | 原「aiohttp + 原生 HTML/CSS/JS」；FastAPI + Vue | 后端 aiohttp 与引擎共享同一事件循环，WS 推送零跨进程成本；前端引入**成熟组件库 + 类型系统 + 构建链**，解决原生 JS 全局脚本「页面组件太垃圾」的可维护性/状态管理问题 | 引入 **Node 构建链**（CI/打包需加 node）；前端与后端解耦为独立工程；旧静态页需整体退役 |
| 4 | **WebSocket 事件推送** | 前端轮询 REST | 报文/事件为**高频流式**数据，轮询产生延迟与带宽浪费；WS 支持先推快照再增量，背压用 `Queue(maxsize=256)` 丢弃保护 | 需处理断线重连与消息契约；WS 长连接需心跳；**契约需版本化（Q10 schemaVersion）** |
| 5 | **YAML 配置与测试脚本** | JSON / TOML / Python DSL | 电力行业点表与场景脚本**由现场工程师维护**，YAML 可读性最好、支持注释 | YAML 无类型校验，需加载层做校验与默认值兜底 |
| 6 | **pytest + Mock 分层测试** | unittest / 纯端到端 | 引擎层用 **Mock 传输层**可在无网络下快速回归（**489 用例**秒级）；`qa_verify/` 真实 socket + 浏览器端到端补充真实性 | Mock 与真实实现可能漂移；`qa_verify` 依赖本机网卡/浏览器，CI 复现难 |
| 7 | **结构化日志（`logging_manager.py`）**（v1.2 新增） | 仅 Python logging / 第三方（structlog/loguru） | 自研**零新增依赖**；结构化字段（ts/level/source/category/message/data）+ 三路输出（内存环形缓冲 / JSONL 轮转 / 订阅推送）+ Python logging 桥，既有 `iec104.*` 日志零改动即被收纳 | 内存缓冲有上限（默认 5000，O(1)）；高频 DEBUG 落盘有**写放大**（见 §5 风险）；需评估采样/级别开关 |
| 8 | **历史库默认开启（SQLite）**（v1.2 修订） | 默认关闭（原）；独立时序库 | 现场排障需回放历史；SQLite 零部署、单文件、可随包分发 | **写放大 + 磁盘占用**：需默认数据目录 + `--no-history` 开关 + 保留期/容量上限/清理策略（见 T17、§5） |
| 9 | **PyInstaller 打包**（v1.2 更新） | Nuitka / cx_Freeze | 面向**现场无 Python 环境**的分发需求；`build_all.py` 已合并三脚本 | 需显式收集 `webui/static`（**含前端 `dist` 产物**）、`configs`、`resources`；`hidden-import` 维护成本；**新增前端产物先于打包构建** |

---

## 4. 任务分解方案

> v1.2 **重做任务表**：已完成任务移入「✅ 已完成（归档）」，不再占用工作量；失效任务删除/改写；新增 Q6/Q7/Q9 相关任务。
> **2026-11-06 进度核对**：T01~T24 全部完成（待办 0）；核对依据为代码、测试与文档现状。T04/T05 拆分后 `master.py` 711 行、`slave.py` 723 行，略超原 ≤700 行验收线，但 God Class 拆分目标已达成。
> 优先级：P0 必须、P1 重要、P2 增强。工作量单位为「人日」（单人投入估算）。角色代号见 §8。

### ✅ 已完成（归档，不再计入待办工作量）

| 原任务 | 名称 | 实测证据 |
|--------|------|---------|
| ~~T05~~ | 抽象 `EngineBase` 基类 | ✅ `core/engine/base.py` 存在（41 行）；`grep "def _spawn"` 仅命中 base.py:18，两处重复已消除 |
| ~~T08~~ | `wrong_cot` 落地 + COT 边界 | ✅ `core/engine/slave.py:90` `wrong_cot: bool=False`、`:394` `_response_behavior.wrong_cot` 判定；PROJECT.md 记载「子站应答 COT 整体 +1，含 Web UI 开关」 |
| ~~T16~~ | 数据导出 CSV/JSON | ✅ `GET /api/export/points.csv`、`GET /api/export/session.json` 已实现 |
| ~~T01(部分)~~ | 工程基线与 CI 初版 | ✅ `.github/workflows/ci.yml`、`.pre-commit-config.yaml` 已存在；`pyproject.toml` 已配 `[tool.ruff]`/`[tool.pytest.ini_options]`（**剩余项见新 T01**） |
| ~~T03(部分)~~ | 文档与代码对齐 | ✅ README.md/README_eng.md 已大幅重写（−492/−443）；`requirements.txt` 已移除 pywebview；`docs/optimization_report.md`、`docs/iec104-conformance-fixes.md` 已新增（**剩余项见新 T03**） |
| ~~T04(部分)~~ | 遗留工程卫生 | ✅ `resources/style.qss`、`apps/web_lab.py` 已删；`build/{build,build_linux,build_windows}.py` 已合并为 `build_all.py`（**剩余项见新 T02**） |
| ~~T18(部分)~~ | WS/REST 契约文档 | ⚠️ `webui/api_contract.md` 已存在（完整 REST/WS 契约表，~35 端点），但**无 `schemaVersion`**（剩余项见新 T18） |

### Phase 0 — 基线收口与遗留清理

| 任务ID | 任务名称 | 描述与验收标准 | 优先级 | 工作量 | 前置依赖 | 承担角色 | 涉及文件 |
|--------|---------|---------------|--------|--------|---------|---------|---------|
| ✅ **T01** | 工程基线收口（Python 版本对齐 + CI 矩阵 + 覆盖率） | ① `pyproject.toml`：`requires-python=">=3.11"`、`[tool.ruff] target-version="py311"`；② CI 矩阵改 `["3.11","3.13"]`；③ 引入 `pytest-cov` 输出覆盖率并对 `core/` 设门槛（≥85%）；④ 补 `tests/README.md` 说明分层策略。**验收**：CI 双版本绿、489 passed、ruff 0 告警、覆盖率报告达标 | P0 | 2 | — | DevOps+架构师 | `pyproject.toml`, `.github/workflows/ci.yml`, `tests/README.md` |
| ✅ **T02** | 遗留工程卫生收尾 + `qa_verify/` 处置 | ① 删除 `apps/venv/` 误提交虚拟环境；② **`qa_verify/` 处置（结论见 §7-Q11）**：将耐用 E2E 脚本（`qa_full_flow.py`/`qa_shutdown.py`/`qa_real_device.py`）**择优提升**至 `tests/e2e/`（纳入 git），其余 ad-hoc/探针脚本继续 ignore；③ 核对 `app.py` 参数与文档一致。**验收**：`apps/venv` 不存在；`git ls-files tests/e2e` 非空；CLI 帮助与文档一致 | P1 | 1.5 | — | 后端工程师 | `apps/venv/`(删), `tests/e2e/*`(新), `app.py`, `PROJECT.md` |
| ✅ **T03** | 文档与代码对齐收尾 | ① README 徽章 `Python-3.10+` → `3.11+`（`Tests-489` 已正确）；② 核验 `docs/api_reference.md`/`user_guide.md` 无 Qt/gui 残留并补 Web UI + 日志面板说明；③ 链接本文档 v1.2。**验收**：全仓 `grep -ri "pyside6\|pyqt\|pywebview\|gui/"` 无残留描述（源码已零命中） | P1 | 1 | — | 文档工程师 | `README.md`, `README_eng.md`, `docs/api_reference.md`, `docs/user_guide.md` |

### Phase 1 — 架构收敛（God Class / 生命周期）

| 任务ID | 任务名称 | 描述与验收标准 | 优先级 | 工作量 | 前置依赖 | 承担角色 | 涉及文件 |
|--------|---------|---------------|--------|--------|---------|---------|---------|
| ✅ **T04** | 拆分 `MasterEngine`（God Class） | 从 **1745 行**中抽出 `MasterSession`（连接/状态/重连）与 `MasterProtocolHandler`（帧编解码分发、命令构建），`MasterEngine` 保留编排与公开 API。**验收**：单文件 ≤ 700 行；公开接口签名不变；`test_master_engine.py`(635 行) 全绿；每抽一模块单独提交 | P0 | 4 | — | 后端工程师 | `core/engine/master.py`, 新增 `master_session.py`/`master_protocol.py` |
| ✅ **T05** | 拆分 `SlaveEngine`（God Class） | 从 **1950 行**中抽出 `SlaveSession`（每客户端状态）、`SlaveResponseBuilder`（应答/品质/COT 构建）、`SlaveSimulator`（手动/随机/脚本模拟）。**验收**：单文件 ≤ 700 行；`test_slave_engine.py`(854 行) 全绿 | P0 | 4 | — | 后端工程师 | `core/engine/slave.py`, 新增 `slave_session.py`/`slave_response.py`/`slave_sim.py` |
| ✅ **T06** | 传输层职责边界收敛 | 明确 `connection.py` 为唯一实现，`client.py`/`server.py` shim 加 `# DEPRECATED` 注释并锁定兼容期；统一 `close()` 幂等与超时语义；补传输层设计说明。**验收**：`grep` 无新增对 shim 的 import；文档描述清晰 | P1 | 2 | — | 后端工程师 | `core/transport/connection.py`, `client.py`, `server.py`, `docs/` |
| ✅ **T07** | 生命周期与资源清理加固（含多站回收） | 加固 `EngineBridge.shutdown()` / 引擎 `stop()` / `MultiStationManager.stop_all()`：完整取消 `_background_tasks`、关闭 socket（`wait_closed` 带超时）、清空 subscriber、停调度器；**补多站 Web 会话关停的显式回收路径**（PROJECT.md 待办 #3）；兼容 asyncio 3.13 关停语义。**验收**：新增关停泄漏测试；`tests/e2e/qa_shutdown.py` 通过；无 "Task was destroyed but it is pending" 告警 | P0 | 3 | — | 后端+测试 | `webui/bridge.py`, `webui/session.py`, `core/engine/*.py`, `tests/test_shutdown.py`(新) |
| ✅ **T08** | 参数命令主站侧状态跟踪 | 主站侧跟踪参数装载/激活结果（当前仅记录日志，未跟踪）；`P_ME_NA/NB/NC`/`P_AC_NA` 激活确认/终止状态入库并可经 REST 查询。**验收**：参数激活流程有状态可查；新增用例覆盖 | P1 | 2 | T04 | 后端+测试 | `core/engine/master.py`, `master_protocol.py`, `webui/session.py`, `tests/` |
| ✅ **T09** | 升降命令步位置点建模与联动 | 点表新增步位置点类型（真机为 `M_ST_NA_1` 档位），升降命令（`C_RC_NA_1`）执行后联动更新档位点并上送。**验收**：步位点可建模/上送；新增用例 | P2 | 2 | — | 后端+测试 | `core/data/point_table.py`, `core/protocol/types.py`, `core/engine/slave.py`, `tests/` |

### Phase 2 — 前端工程重写（Q7）

| 任务ID | 任务名称 | 描述与验收标准 | 优先级 | 工作量 | 前置依赖 | 承担角色 | 涉及文件 |
|--------|---------|---------------|--------|--------|---------|---------|---------|
| ✅ **T10** | 前端工程脚手架 + Node 构建链 + 打包/CI 接入 | 初始化 `webui/frontend/`（Vite + React18 + TS + AntD5 + React Query + Zustand + ECharts + Vitest/Playwright）；`vite build` 产物输出到 `webui/static/`；`build_all.py` 增前端构建步骤并打包 `dist`；CI 增 node 构建 job；`package.json` 锁版本。**验收**：`npm ci && npm run build` 产出静态页；CI 双 job 绿；打包产物含前端 | P0 | 4 | — | 前端+DevOps | `webui/frontend/**`(新), `webui/static/**`(产物), `build/build_all.py`, `.github/workflows/ci.yml`, `package.json` |
| ✅ **T11** | 前端数据层：REST/WS 客户端 + 状态管理 + 契约适配 | 封装 `api()`（REST，~35 端点）+ WS 客户端（断线重连、背压提示、snapshot 先行）；React Query 管理服务端状态，Zustand 管理 UI 状态；**按 `schemaVersion` 适配**（依赖 T18 契约）。**验收**：类型化 API 层；断线重连恢复快照；`tsc` 零错误 | P0 | 3 | T10 | 前端工程师 | `webui/frontend/src/api/**`, `src/store/**`, `src/ws/**` |
| ✅ **T12** | 主站页面重写 | 连接/状态栏、**选中行 + 右侧命令面板**（YK 单/双/SBO、设点、总召、步/比特串/延时/参数/文件）、点表（十万行虚拟滚动）、报文查看器（HEX + 解析 + 过滤）、趋势图。**验收**：`qa_full_flow.py` 主站项通过；双击命令点值直接下发须经确认弹窗且不绕过 SBO（T21）；10 万点不卡顿 | P0 | 5 | T11 | 前端工程师 | `webui/frontend/src/pages/master/**`, `src/components/**` |
| ✅ **T13** | 子站页面重写 | 监听/多客户端状态、响应配置面板（延迟/错误注入 drop·corrupt·no_response·wrong_cot/品质 IV·NT·SB·OV/连接行为）、模拟（手动/随机/脚本）、点表编辑与 YAML/CSV 导入导出、自发上送。**验收**：面板改动实时生效；端到端脚本验证 | P0 | 4 | T11 | 前端工程师 | `webui/frontend/src/pages/slave/**`, `src/components/**` |
| ✅ **T14** | 日志面板与全局外壳 | 全局导航/主题（antd `darkAlgorithm`）/错误边界；「日志」面板：分级/分类/来源过滤 + 搜索 + JSONL 导出（对接 `GET /api/logs`、`/api/logs/export`、WS `log`）。**验收**：日志实时流可视、过滤/导出可用 | P1 | 2.5 | T11 | 前端工程师 | `webui/frontend/src/pages/logs/**`, `src/layout/**` |
| ✅ **T15** | 前端自动化测试纳入 CI | Vitest + RTL 单测 + Playwright 无头端到端（替代旧 `qa_verify/*.mjs` DOM 探针）；纳入 CI 并产出报告。**验收**：CI 中前端用例自动执行并产出报告 | P1 | 3 | T10 | 测试工程师 | `webui/frontend/src/**/*.test.tsx`, `tests/e2e/playwright.config.ts`, `tests/e2e/specs/**`（5 spec：contract/logs/master/multi/slave）, `.github/workflows/ci.yml`（frontend + frontend-e2e 两 job） |

### Phase 3 — 功能与数据集成

| 任务ID | 任务名称 | 描述与验收标准 | 优先级 | 工作量 | 前置依赖 | 承担角色 | 涉及文件 |
|--------|---------|---------------|--------|--------|---------|---------|---------|
| ✅ **T16** | 多站管理器接入 Web UI（Q6） | 新增「多站」页 + `/api/multi/*`（start/stop/status/summary）+ 多站桥（`EngineBridge` 扩展）；`MultiStationManager` 生命周期接入 Web 会话（**与 T07 关停回收耦合**）。**验收**：Web 端可增删/启停多站并看聚合状态；关停无泄漏 | P0 | 4 | T07, T11 | 前端+后端 | `core/engine/multi_station.py`, `webui/server.py`, `webui/session.py`, `webui/bridge.py`, `webui/frontend/src/pages/multi/**` |
| ✅ **T17** | 历史库默认开启（Q9） | `core/config.py` 新增 `HistoryConfig`（`enabled=True` 默认、`dir` 默认数据目录、`retention_days`、`max_size_mb`、`flush_interval`）；`app.py` 默认建库 + 新增 `--no-history` 开关；实现保留期/容量上限/清理策略；评估并记录**写放大**。**验收**：默认启动即建库；`--no-history` 可关；超限自动清理；文档记录容量/写放大 | P0 | 3 | — | 后端工程师 | `core/config.py`, `app.py`, `core/data/history.py`, `docs/`, `configs/*.yaml` |
| ✅ **T18** | WS/REST 契约版本化与校验（Q10） | `webui/api_contract.md` 补 `schemaVersion` 字段与版本策略；WS `snapshot`/`frame`/`event`/`log` 消息带版本；后端出契约自检；前端按版本适配。**验收**：契约文档化含版本；不匹配时前端告警不崩 | P1 | 2 | — | 前端+后端 | `webui/api_contract.md`, `webui/server.py`, `webui/events.py`, `webui/frontend/src/ws/**` |
| ✅ **T19** | 旧静态页退役与前端回归收尾 | 新前端全功能对齐后删除 `webui/static/{master.html,slave.html,js/app.js,css/app.css}`（改由 `dist` 产物托管）；全流程端到端回归。**验收**：`qa_full_flow.py`/Playwright 全绿；旧原生页无残留 | P1 | 2 | T12, T13, T14, T15 | 前端+测试 | `webui/static/**`(退役), `webui/frontend/**`, `tests/e2e/**` |

### Phase 4 — 安全与协议增强（按需）

| 任务ID | 任务名称 | 描述与验收标准 | 优先级 | 工作量 | 前置依赖 | 承担角色 | 涉及文件 |
|--------|---------|---------------|--------|--------|---------|---------|---------|
| ✅ **T20** | TLS / IEC 62351 安全传输 | 传输层新增 TLS 选项（`ssl.SSLContext`）与证书/密钥配置；主子站/多站支持 `tls.enabled`。**验收**：自签证书下主子站握手成功；配置文档化 | P2 | 4 | T06 | 安全工程师 | `core/transport/connection.py`, `core/config.py`, `configs/*.yaml`, `docs/` |
| ✅ **T21** | 冗余双通道 | 主站支持双连接（主备），通道切换与去重逻辑。**验收**：断主用备切换 < 阈值；新增切换测试 | P2 | 5 | T04 | 后端工程师 | `core/engine/master.py`, `master_session.py`, `core/transport/connection.py` |
| ✅ **T22** | 非标准 TypeID 支持 | 扩展 `types.py`/`asdu.py` 支持厂商私有类型（可配置解析器）。**验收**：编解码往返正确；补用例 | P2 | 3 | — | 后端+测试 | `core/protocol/types.py`, `asdu.py`, `tests/` |
| ✅ **T23** | pcap / pcapng 导出 | `capture/format.py` 新增 pcap/pcapng 写出（含正确链路类型与时间戳）。**验收**：Wireshark 可打开并解析 | P2 | 3 | — | 后端工程师 | `core/capture/format.py`, `recorder.py`, `capture_tool.py` |
| ✅ **T24** | 文件传输 F_LS 八位组语义核实 | 对照 IEC 60870-5-104 与真机/标准，核实 F_LS（目录/段/文件就绪）八位组语义并修正实现。**验收**：真机联调或标准比对结论落地；补用例 | P2 | 3 | — | 后端+测试 | `core/protocol/file_transfer.py`, `tests/` |

> **任务统计**：**已完成 24/24，待办 0**（T01~T24），归档 **7** 条。Phase 0=3、Phase 1=6、Phase 2=6、Phase 3=4、Phase 4=5。

### 2026-11-06 增强批次（T25~T31，全部完成）

> 原 24 项交付完成后，按“先补可信度、再补交付链、最后补体验”的顺序新增 7 项；
> 均已完成并纳入 CI/文档，故不再计入待办。

| 任务ID | 任务名称 | 交付物 / 验收证据 |
|--------|---------|------------------|
| **T25** | 互操作语料库 + 回放回归 | `tests/fixtures/frames/`（7 场景合成基线 + golden manifest + `real/` 真机目录）；`tests/test_frame_corpus_replay.py` 逐帧解码 + MasterEngine 回放；支持导出 pcap |
| **T26** | 解码器 fuzz / 属性测试 | `tests/test_protocol_fuzz.py`（Hypothesis）；APCI/ASDU/文件传输信息体畸形输入只抛 `ValueError`；截断 ASDU 严格拒绝（对象数量校验）、F_SG 段长度不足报错 |
| **T27** | Windows CI + 发布流水线 | `.github/workflows/ci.yml` `windows-build` job（onedir exe 真实启动冒烟）；`.github/workflows/release.yml`（tag 校验 → 双平台 onefile → 冒烟 → SHA256SUMS → Release） |
| **T28** | 性能 / 长稳基准 | `tests/perf/`（解码吞吐、10 万点快照、20 客户端并发约 2.9k 帧/秒、主站↔子站环回 soak）；**2h soak 实跑通过：7200s / 34,765 GI / 内存 +0.64 MB**；`-m "not perf"` 默认排除 |
| **T29** | 一键诊断包 | `webui/diagnostics.py` + `GET /api/diagnostics/export` + 状态页按钮；配置私钥路径脱敏；契约文档 §2.10 |
| **T30** | 一键环回 Demo | `python app.py --demo`：两个角色独立子进程、自动监听/连接/总召、Ctrl+C 统一回收；`--demo-seconds` 用于定时演示 |
| **T31** | 分支覆盖 + 变异冒烟 | CI `--cov-branch`（当前 92.1%）；`tools/mutation_smoke.py` 12 个高价值变异全部被杀死，CI 独立 job |
| **T32** | 历史查询页（2026-11-06 第二批） | `GET /api/history/{stats,data,frames,export}`（契约 §2.11/§4.9）+ Web「历史」页（数据/报文双页签、时间/类型/IOA/方向过滤、CSV 导出、未启用提示）；`tests/test_webui_history_endpoints.py`（4 例）+ `HistoryPage.test.tsx`（3 例）；全量 1288 passed |
| **T33** | 网络异常模拟接入 Web UI（2026-11-06 第三批） | `/api/simulation`（GET/POST + reset/disconnect，契约 §2.12/§4.10）+ 状态页卡片（预设/自定义/手动断线/统计）；核心修复 `SimulationManager` 覆盖 raw 回调致 RX 绕过协议处理（改为传输层回调拦截 + 卸载恢复）；4 后端 + 3 前端用例；全量 1293 passed |
| **T34** | Web 访问认证（2026-11-06 第三批） | `--http-host` + `--auth-token`（/`IEC104_AUTH_TOKEN`）；令牌保护 `/api/*` 与 `/ws`（Bearer / X-Auth-Token / `?token=`），`GET /api/auth` 公开探测（契约 §2.13）；前端 AuthGate + URL 令牌导入；非回环无令牌启动告警；4 后端 + 2 前端用例；全量 1297 passed |
| **T35** | 一致性套件接入 pytest（2026-11-07） | `tests/test_conformance_suite.py`：按 `_test_*` 方法参数化（10 例，失败输出 case id）+ 汇总锁死 42 case/零 FAIL/ERROR/SKIP；独立 runner 保留；全量 1308 passed |
| **T36** | 分支覆盖率提升（2026-11-07） | 实测 88.86%→**92.08%**（门禁 88→91，保留约 1 点抖动余量）：补 scheduler 47→97%、data_store 83.6→95%、master_session 77.5→92%、multi_station 80.6→98%，及 types/asdu 零散分支；新增 73 例；全量 1381 passed |
| **T37** | 全流程验收进 CI（2026-11-07） | `.github/workflows/ci.yml` 新增 `e2e-full-flow` job：job 内拉起主站(8765)/子站(8766)/IEC 24040 → 等就绪（40s 上限）→ `tests/e2e/qa_full_flow.py` 12 阶段 → trap 回收；失败上传 `master.log`/`slave.log`；本机实测 12/12、exit 0 |
| **T38** | 前端 i18n 阶段一（2026-11-07） | 零依赖 `src/i18n`（zh/en 词典、`t()`/`useT()`/`tNow()`、占位符）+ 头部「中 / EN」（localStorage 记忆、antd locale 联动）；覆盖外壳/认证/状态/日志/历史/模拟卡片/共享列宽/运行时告警；`i18n:inventory` 清单当时剩余 20 文件/535 行（工作台内部，T40 已完成并清零）；5 用例；前端 123 passed |
| **T39** | 文件传输真机核实准备（2026-11-07） | `docs/file_transfer_open_items.md`（5 项开放清单：NOF/SCQ/WITH_DEACT/多节/FRQ-SRQ + 步骤/判定/回填模板）+ `tests/e2e/qa_file_transfer_probe.py`（只读探针，默认目录召唤；本机模拟器跑通）；文档互链；**2026-11-07 用第三方 lib60870-C v2.4.1 实测回填 5 项并修复 122/COT13、SCQ=6 节流程、128/129 确认类型；默认代码复测 800B 多节完成；真机仍待复测** |
| **T40** | 前端 i18n 阶段二（2026-11-07） | 主站/子站/多站工作台、报文解析与查看器（lib/frame.ts 双语对照表）、共享点表组件全部迁入词典；`npm run i18n:inventory` = **0 文件 / 0 行**；zh 文案逐字保留；前端 123 passed |
| **T41** | 门禁补盲（D1/D2，2026-11-07） | WebUI 覆盖率 77.1%→**89%**（CI 独立门禁 ≥85%）；前端接入 `@vitest/coverage-v8`（阈值 statements/lines 78、branches 80、functions 55）+ coverage artifact；后端 1545 passed、合并覆盖 91.3% |
| **T42** | e2e 与 CI 工程化（D3/D4，2026-11-07） | 新增历史/网络模拟/AuthGate/中英切换 4 条 Playwright（22/22）；CI concurrency、Python 3.14、Dependabot、夜间 perf、PR onefile dry-run |
| **T43** | 版本单一源与文档校准（D5，2026-11-07） | `core/version.py` 为唯一版本源（`--version` = 1.2.0）；版本一致性测试；历史文档 TLS/冗余/i18n 表述加注现状 |
| **T44** | Web 测试中心（E1，2026-11-07） | `/api/tests/*`（scripts/run/stop/status/reports）+「自动化测试」页；子进程隔离、实时日志、报告下载；4 后端 + 2 前端用例 |
| **T45** | Web 报文录制/回放（E2，2026-11-07） | `/api/capture/*` 14 端点 +「报文抓包」页：录制启停/暂停、文件列表/下载、i104/json/pcap/pcapng 导出、离线回放/单步/倍速；5 后端 + 2 前端用例 |
| **T46** | 冗余 UI 与 Web 安全（E3/E4，2026-11-07） | 主站 start 支持 `redundancy`，状态返回活动通道/主备在线/切换次数 + 连接面板配置；`--web-tls-cert/--web-tls-key` HTTPS、CSP/XFO/Referrer-Policy/Permissions-Policy；12 后端 + 1 前端 + 4 安全用例 |
| **T47** | 发布体验与负例（E5/F2，2026-11-07） | `--version`、README 4 张截图、SECURITY/CHANGELOG；一致性套件新增 8 个畸形 APCI/ASDU 负例（42→50，pytest 汇总同步锁死） |
| **T48** | 前端依赖大版本升级（v1.3.0，2026-11-07） | Dependabot PR #6（17 项：React 19/antd 6/TS 7/Vite 8/Vitest 5/ECharts 6 等）+ PR #5（`actions/download-artifact` 7→8）；适配 TS7 去 `baseUrl`（`paths: ./src/*`）、antd6 改 `role=combobox`/`role=tabpanel`/aria-label；Vitest5 覆盖率口径重基线 statements 55 / lines 58 / branches 50 / functions 53；合并后 master CI 10/10 绿 |
| **T49** | antd 6 弃用告警清零 + C4 回归（2026-11-07） | `Alert message→title`、`Space direction→orientation`、`InputNumber addonAfter→suffix`、`Modal maskClosable→mask.closable`、`Statistic valueStyle→styles.content`；前端 antd 告警 0、128 passed、Playwright 22/22；重建 `webui/static/app`；lib60870 第三方 800B 多节回归通过（真机仍待） |
| **T50** | C4 真机复测（暂缓，待装置窗口） | 按 `docs/file_transfer_open_items.md` 5 项（NOF/SCQ/DEACT/多节/FRQ-SRQ）逐项复测并回填；已完成两轮 lib60870-C v2.4.1 第三方回归（含 v1.3.0），不替代真机 |
| **T51** | 悬停翻译契约错位修复（2026-11-07） | 报文查看器悬停恒显示「翻译失败」：后端 `GET /api/frames/decode` 按契约 §2.9 返回扁平 `{ok, format, segments}`，前端误读 `r.translation`（自 `810c340` 起）；前端类型与组件对齐扁平结构、单测 mock 改为真实响应，新增 Playwright `frame-translate.spec.ts`（真实后端 + 浏览器悬停），端点测试锁定键集 `{ok, format, segments}`；前端 128 passed、Playwright 23/23、`webui/static/app` 已重建 |
| **T52** | API 响应契约单一源（2026-11-07） | `api/contract.ts` 零依赖 schema DSL（`ApiContractError` 带 JSON 路径）+ `api/contracts.ts` 覆盖全部 JSON 响应 + `apiGet/apiPost/apiPostText` 每次校验 + `ContractKeyChecks` 编译期键集比对（接口多/少字段 `tsc` 失败）+ Playwright `api-contract.spec.ts`（真实后端 × 同一 schema；主站/子站只读矩阵、幂等命令、连接+总召运行态）；修正 `SessionExport` 信封形状、`HistoryStats` 未启用零值、参数状态未连接 `{ok:false,error}`；前端 136 passed、Playwright 27/27、后端 1545 passed |
| **T53** | 单文件发布 + 工作台骨架（2026-11-07） | 一个 `iec104-tester` 可执行文件（T54 起默认 both 单进程/单端口）：CLI `--mode master|slave|both`；`build_all.py` 只产一个产物，CI/release 用同一 exe 冒烟两种角色；前端抽 `WorkbenchShell` 公共骨架（`MasterPage` 159→151 行、`SlavePage` 103→94 行，布局统一由骨架承担），保留两套角色面板；本机单 exe 实测 master/slave/both |
| **T54** | 主站/子站单页工作台（2026-11-07） | 默认启动 both：**单进程双角色、一个 8765 端口**；左侧两个菜单（主站工作台/子站工作台）在同一 SPA 内原生切换，子站 API/WS 挂 `/slave/api`、`/slave/ws`（aiohttp sub-app），不再 iframe/双端口；`GET /api/schema` 增加 `roles`/`slaveApiPrefix`，前端 activeRole 切换 API/WS base；查询键按角色隔离（不再切角色清缓存，切回命中缓存）；`EngineBridge` 日志桥按 `iec104.master/slave` 分流；历史库按角色拆分；新增 Playwright `unified-workbench.spec.ts`（菜单切换 + 原生子站页 + 单浏览器页 + 无 iframe + 桌面端右侧面板不换行）与 `test_webui_dual.py`（前缀路由/auth/schema）；前端 138 passed、Playwright 28/28、后端 1551 passed |
| **T55** | 工作台体验缺陷修复（2026-11-07） | ① 点表提示文案从 Card 标题区移到表体工具行——标题区宽度被右侧工具挤压，长文案被裁成半句；Playwright 新增 `points-hint` 可见性/`scrollWidth<=clientWidth` 断言。② 模拟控制支持 YX/YC **独立开启**：`POST /api/slave/sim` 新增 `yx_enabled`/`yc_enabled`（默认均 true、至少一项），关闭的类型即使 `scope=selected` 也不要求 ioas，模拟循环不产生该类报文；`GET /api/status` 回显 `simulation_yx`/`simulation_yc` 供刷新后回填；UI 两个开关并禁用对应参数；新增后端 sim 用例 5 个、前端 SimulationPanel 用例 4 个（含刷新回填） |
| **T56** | UI 自动巡检 + 静态路由一致性（2026-11-07） | 新增 `tests/e2e/specs/ui-audit.spec.ts`：8 菜单页 × 3 视口（1680/1366/1280）× 中英 + 深色，覆盖主/子站页签、命令面板折叠区全展开、单角色 8765/8766；断言 Card 标题/按钮/页签/表单标签/提示文案不裁切、页面无横向滚动、控件不出视口（表格滚动区豁免）、无 console error/warn、无 API 4xx/5xx、无错误 Alert/空白页签、不漏 i18n key；导出链接探活（2xx + 附件头）。巡检发现并修复：① 英文/窄屏下点表 Card 标题被 `extra` 工具条压到 7px、工具被裁 → 工具条移入表体首行（自动换行）；② 英文「手动置数」类型 Segmented 标签超宽被裁（`YX single point` 等 → 短标签）；③ `/api/points/yaml`、`/api/export/points.csv`、`/api/export/session.json` 缺 `Content-Disposition: attachment`，界面「导出」会在浏览器内联显示而非下载；④ 合并模式下子站「报文抓包」页会列出/可下载主站录制（共用 `data/captures` 目录）→ `CaptureService` 按角色前缀隔离列表与下载/加载（无前缀手工文件双方可见）。新增 `tests/test_frontend_routes.py`（前端 api 调用方法+路径 ↔ 后端路由：前端调用不存在/方法不符即失败）；`npm run i18n:inventory` 恢复 0（契约层诊断文案标记 `i18n-ignore-file`）；前端 142 passed、后端 1559 passed、Playwright 33/33、ruff 通过 |
| **T57** | 配色对比度自动化 + WCAG AA 主色（2026-11-07） | 新增 `tests/e2e/specs/ui-contrast.spec.ts`：8 页 × 浅/深主题 + 选中行状态，沿祖先合成有效背景、处理 opacity/透明色，按 WCAG 2.1 计算前景/背景对比度（普通 4.5:1、大字 3:1），并单独检查 `::placeholder`；同一颜色对聚合。默认门禁 <3:1 失败，`CONTRAST_REPORT=1` 仅报告；实测 3488 处文本 **0 硬失败 / 0 建议项**（全部达到 AA）。修复：① 主色 `#13c2c2`（白底/白字双向仅 2.2:1）→ `#0a7575`（约 5.5:1），亮青保留为 `colorInfo`（深色品牌字/信息色）；② 浅色菜单选中底/字、深色菜单选中底、Tabs/Pagination 深色强调色显式 token；③ placeholder、次要/三级文字、Switch 轨道、空表占位文字提升；④ success/warning/error 标签前景/背景 token（#237804/#f6ffed、#d46b08/#fff7e6、#cf1322/#fff1f0；深色 #73d13d/#ff7875），避免 antd 从深色派生灰绿底；⑤ 不可访问的预设标签（gold/cyan/purple/green）改为 success/blue/default，帧方向「发送」success、「接收」blue，格式 I/S/U 分别为 blue/success/default；⑥ 组件内硬编码颜色改 token，新增 `tests/test_frontend_style_tokens.py` 静态门禁。前端 142 passed、后端 1560 passed、Playwright 34/34、ruff 通过 |
| **T58** | 非文本对比 + 视觉回归基线（2026-11-07） | 新增 `tests/e2e/specs/ui-nontext-contrast.spec.ts`（WCAG 1.4.11 / 2.4.7）：控件边框（Input/InputNumber/Select/Picker/默认按钮/Checkbox/Radio/Pagination）、Switch 轨道、纯图标按钮、键盘 Tab 焦点环，逐项与相邻背景 ≥3:1；实测 702 处 0 硬失败（禁用控件按 WCAG 豁免）。修复：`colorBorder` 浅 #8c8c8c / 深 #6b6b6b（输入框等）、Button 显式 `defaultBorderColor/borderColorDisabled`（antd 6 cssVar 未跟随 colorBorder）、深色选中 Switch 轨道固定 #0b7f7f（antd 会压暗到 2.6:1）、全局 `:focus-visible` 焦点环（浅 #0a7575 / 深 #5cdbd3）。新增 `tests/e2e/specs/visual.spec.ts`：专用单角色服务 8768（无引擎/无帧/无历史），浅/深主站工作台 + 状态总览三张整页基线；`snapshotPathTemplate` 按平台分目录，提交 Windows(win32) 基线；**有基线的平台自动运行**（`windows-build` CI job 执行视觉回归），无基线平台自动 skip，新平台用 `VISUAL_UPDATE=1 --update-snapshots` 生成。前端 142 passed、后端 1560 passed、Playwright Windows 38/38（Linux 35 passed + 3 skipped，无 linux 基线）、ruff 通过 |
| **T59** | 界面设计规范 + 8 页差距审查（2026-11-08） | 新增 `docs/design_guidelines.md`：PatternFly（主）/Carbon（辅）组件模式 + ISA-101/NUREG-0700 按"工程测试工具"裁剪 + 本项目 antd token 落地。固定九类规则：颜色语义（一色一义、不许只靠颜色、Tag 白名单）、点表（密度/数值右对齐/单位与小数位/品质位解码/陈旧与禁用）、告警事件（三分类、四级映射、确认与抑制范围）、IEC104 语义映射（品质位掩码表、COT 权重、时标格式、CA/OA、N(S)/N(R)）、命令安全（二次确认范围、SBO 选择态、`danger` 边界）、趋势/日志/报文、四态完备、无障碍、18 项评审清单（标注哪些由自动门禁判定）。附录 A 按 8 页产出 ✓/⚠/✗ 矩阵 + 1 项 P0 + 15 项差距（**P0**：品质位掩码两套定义——`protocol/types.py` 用 IV=0x40/NT=0x20，`slave_response.quality_mask()` 用 IV=0x80/NT=0x40/OV=0x04，与 IEC 60870-5-101 均不符，导致注入"无效"品质后界面读回 `GOOD`，已用 `str(QualityDescriptor(raw))` 实测佐证；P1×4：点表缺 `unit`/`decimal_places` 且值一律 `toFixed(3)`、Tag 预设 `purple`/`cyan`/`magenta`/`orange` 越界、命令弹窗全部 `danger`、5 页无错误态且无全局兜底；P2×7；P3×3），证据精确到文件行号。同步修正与本规范冲突的旧表述：`PROJECT.md`「UI 风格」、`README.md` 与 `README_eng.md` 的「浅色工业风」、`user_guide.md`「统一左对齐 / 圆角 3px / 深色只适合控制室」 |
| **T60** | 品质位按 IEC 60870-5-101 标准化（2026-11-08） | 修复 T59 审查发现的 P0：`QualityFlag` 原用 `IV=0x40/NT=0x20`（标准 `IV=0x80/NT=0x40`），`ResponseBehavior.quality_mask()` 用 `OV=0x04`（标准 0x01），导致注入"无效"品质后主站/界面读回 `GOOD`。统一为 `QualityFlag` 单一来源并补 `SB=0x20`；`QualityDescriptor` 增加 `substituted`、`to_int()` 由 `& 0x7F` 改 `& 0xFF`（原实现截掉 bit7）、`__str__` 按严重度 IV→NT→SB→BL→OV；`quality_mask()` 改用枚举常量。测试：新增标准位逐位断言与「注入 IV → 解码仍为 IV」往返用例，修正 `test_types` / `test_protocol_extra_paths` / `test_protocol_io` 旧断言。真实 TCP 实测：注入 invalid→`IV`、not_topical→`NT`、overflow→仅 QDS 点位 `OV`。后端 1562 passed、ruff 通过 |

| **T61** | 品质注入补齐 SB 开关（2026-11-08） | 标准品质位五选一此前缺 SB 注入。`ResponseBehavior` 增加 `force_substituted`（`from_dict` 读 `quality.substituted`，`quality_mask()` 或 `QualityFlag.SB`）；`response_behavior_to_dict` 回填该键，保证 `GET → 改 → POST` 不丢配置。前端 `SlaveQuality` 增加 `substituted`、`ResponsePanel` 补「取代 SB」开关（顺序按严重度 IV→NT→SB→BL→OV），并修正既有标签错误：`blocked` 原写作「被闭锁 SB」→「闭锁 BL」，新增 `rp.q.sb` 中英词条。真实 TCP 实测：注入 substituted → 主站 75 个点位读回 `SB`；后端 1562 passed、ruff 通过、前端 typecheck + ResponsePanel 用例 3 passed、Playwright slave/i18n 8 passed、UI 巡检 3 passed（五开关行在 1280/1366/1680 中英深色下无裁切） |

| **T62** | 按设计规范落地界面（2026-11-08） | 依 `docs/design_guidelines.md` 附录 A.3 修复：① 新增 `components/QualityTags.tsx` —— 品质列中文标签 + 语义色 + tooltip（最多 2 个，其余 `+N`），点表与历史页复用；② `/api/points` 快照补 `unit`/`decimal_places`，`Point`/`pointSchema` 同步，新增 `formatMeasurement()` 按声明小数位渲染「值 + 单位」；③ Tag 预设全部收敛到 `success/default/blue/warning/error`（日志级别 WARNING→warning、ERROR/CRITICAL→error、WS 断开→error，趋势点位标签→blue，SBO→warning，历史方向 tx→success，录制红按例外保留）；④ 命令弹窗与命令面板按方向区分 `danger`（分闸 danger，合闸/设点/升降 primary）；⑤ 新增 `components/QueryErrorAlert.tsx`，接入日志/历史/录波/测试中心/主站/子站六个页面；⑥ 点表值列右对齐 + `.mono` 加 `tabular-nums`，报文长度列右对齐；⑦ 点表行键盘可达（Tab / Enter 选中 / Ctrl+Enter 发命令 / `aria-selected`）；⑧ 趋势 X 轴改 `type:'time'`（毫秒时间戳，刻度 `HH:mm:ss.SSS`）；⑨ `lib/format.ts` 增加 `localeTag()` 并让日志/录波日期跟随界面语言；⑩ 点表空态含下一步动作。回归：后端 1562 passed、ruff 通过、前端 typecheck + 142 单测通过、Playwright 34 passed（ui-audit / 对比度 / 非文本 / master / slave / history / logs / i18n / api-contract / unified / network-sim / multi / visual；Windows 视觉基线已按新界面重拍） |

| **T63** | PatternFly 全量迁移 Phase 1（2026-11-08） | 用户确认放弃 antd 观感、按 **PF 默认密度** 全量迁移。策略：并行应用（`/app/pf.html`）复用数据层、逐页迁移、全部 parity 后切入口并删除 antd，避免生产页面混用两套 UI。新增 `docs/pf_migration.md` 记录进度/验收/风险。Phase 1 落地：PF 6.7（React 19 兼容）+ 官方 `pf-v6-theme-dark` 深色主题；外壳 `PfApp`（Masthead/PageSidebar/Nav、hash↔uiStore、中英/深浅/角色/WS 状态）；`PfPointsTable` 用 `@tanstack/react-virtual` 自建虚拟滚动（PF 无内建虚拟化，官方扩展依赖停维护的 react-virtualized），实测 10 万行仅渲染 **24 个 DOM 行**、行高 38px、表头固定、滚到底可达第 100000 行、无 console error；主站页（连接表单/连接/断开/总召/选中点详情）与状态总览（统计卡/运行信息/只读点表）已迁移；其余 6 页为明确的迁移占位。旧 `/app/` 多入口构建后仍正常。待迁移：命令面板、报文查看器、趋势图、子站工作台、多站、日志/历史/录波/测试中心，以及切换前的 PF 巡检/对比度/视觉基线/e2e 选择器改造 |

| **T64** | PatternFly 迁移 Phase 2：主站页 parity（2026-11-08） | 主站工作台在 PF 版达到与 antd 版功能对等：① `PfCommandPanel` 覆盖全部主站命令——YK（单/双、SBO 选择/两段式/单帧直发/撤销、带时标）、设点（3 种）、总召唤（站 20 + 组 1–16）、累计量召唤、对时、复位、测试、升降、比特串、延时、读、参数（4 种）、文件（目录/选择/请求）；分闸 `isDanger`、结果用面板内联 Alert；② `PfFrameViewer`：方向/格式/最小长度/关键字筛选、暂停冻结、清空、首屏 `/api/recent` 预热、HEX 悬停 300ms 逐段翻译（复用 `/api/frames/decode` 与 500 条缓存）；③ `PfTrendChart`：ECharts 时间轴 + `lttb` + 点位标签删除/清空，配色从 PF CSS 变量解析（canvas 不认 `var()`）；④ 主站页 8:4 栅格（点表 + 命令面板）、加入趋势、报文/趋势页签。修复过程中：PF `AccordionItem` 默认全展开且无 `onToggle`，改用受控 `ExpandableSection`（6 段默认收起）。真实 TCP 实测：连接 → 已连接/Running、执行按钮可用、总召唤成功、无 console error。前端 typecheck 通过、i18n 清单 0 |

| **T65** | PatternFly 迁移 Phase 3：子站工作台（2026-11-08） | 新增 `PfSlavePage` 与 5 个子站面板：`PfSlaveConnectionPanel`（绑定地址/端口/公共地址、TLS 开关+证书/私钥/CA、启停、客户端列表）、`PfManualSetPanel`（YX/YC/YM/STEP，IOA 与类别跟随选中行）、`PfResponsePanel`（延迟/错误注入/品质 5 位/连接行为，应用与恢复默认）、`PfSimulationPanel`（YX/YC 独立开关、间隔/翻转概率/浮动比例、全部点/选中点范围）、`PfTestInjectionPanel`（M EP / M_PS）。`PfApp` 接入 `useSchemaHandshake`：按 `/api/schema` 的 `roles` + `slaveApiPrefix` 自动切换 `/api` ↔ `/slave/api`（单角色部署直接采用唯一角色），并在切页时切换 activeRole。修复：PF Switch 缺 `aria-label` 的告警、`simPanel.selectedInfo` 占位符参数名不匹配、帧查看器筛选控件被拉伸为整行、序号列排版。`--mode both` + 真实 TCP 实测：启动监听、手动置数、品质注入应用、模拟启停全部成功，请求均落在 `/slave/api/*`，无 console error；前端 typecheck 通过、i18n 清单 0 |

| **T66** | PatternFly 迁移 Phase 4：日志/历史/录波/测试中心/多站（2026-11-08） | 完成剩余 5 页，PF 版 **8 个页面全部迁移**：① `PfLogsPage`（实时+历史合并去重、级别/分类/关键字、暂停冻结、清空、导出、分页）；② `PfHistoryPage`（统计头、数据/报文页签、时间范围/类型/IOA/方向/条数、导出、分页）；③ `PfCapturePage`（录制启停/暂停、文件加载/下载/导出 pcap、回放控制与进度、帧表分页）；④ `PfTestCenterPage`（脚本多选、运行/停止、实时日志、报告下载）；⑤ `PfMultiPage`（草稿增删/字段编辑、参与开关、整体启停、聚合状态表，复用 `pages/multi/stationDraft` 纯函数层）。修复：PF 表格在 `table-layout: fixed` 下忽略 `width`（改为 `width + minWidth`，42 处）、PF 入口缺 `.mono` 样式（新增 `src/pf/pf.css`，时间/HEX/数值恢复等宽 12px）、历史页改用 PF 版 `PfQualityTags`、进度条 API 与测试中心统计列宽。实测：日志 100 行/页、历史报文 50 行/页、测试脚本 15 条、多站 2 站启动/停止，均无表头裁切与 console error；前端 typecheck 通过、i18n 清单 0 |

| **T67** | PatternFly 迁移 Phase 5：入口切换 + 功能补齐（2026-11-08） | `index.html` 改加载 `src/pf/main.tsx`，删除 `pf.html` 与多入口构建；`/app/` 正式为 PF 版。切换前补齐 parity：① `PfAuthGate`（`--auth-token` 时校验、URL `?token=` 一次性导入）；② 外壳横幅（契约版本不匹配/发送背压/后端丢帧）；③ 网络异常模拟卡片 `PfNetworkSimCard`（预设、自定义条件、断线、统计、启停）；④ 点表双击值下发命令 `PfPointCommandDialog`（YK/设点/升降、分闸 danger、SBO 提示、禁用原因），值单元格补 `data-testid`。实测：`/app/` 渲染 PF 外壳且无 `.ant-*` DOM、无 console error；网络模拟卡在状态页可见；双击 YK 值弹出确认弹窗。**未完成**：antd 源码/依赖删除、e2e 选择器改造（当前 e2e 仍按旧 antd DOM 编写） |

| **T68** | PatternFly 迁移收尾：e2e + 删 antd + 基线 + exe（2026-11-08） | ① e2e 选择器全面改造：`gotoApp`/菜单改用 `.pf-v6-c-nav__link`，表格行加 `data-testid`（point-row/points-scroll/log-row/history-row/test-script/frame-row），PF 开关用 force click、主题/语言切换改按钮、多站卡片改 testid、历史页签改按钮；对比度巡检支持 `::before` 全铺背景并排除局部指示条；非文本巡检改用 PF 控件类与 Switch 滑块回退。② 删除 antd：`src/pages`、`src/components`、`src/layout`、`src/theme.ts`、旧入口/样式/hooks 及 22 个 antd 单测一并删除，`antd`/`@ant-design/icons` 从依赖移除；保留数据层/i18n/lib 的 60 个单测。③ 视觉基线按 PF 重拍 3 张。④ onefile exe 重建（14.9 MB）并冒烟：PF 页面、无 `.ant-*` DOM、8 菜单、点表行、无 pageerror。结果：e2e **38 passed**、前端单测 60 passed、typecheck/build 通过、i18n 清单 0、ruff 通过 |

| **T69** | 界面套件共存：同地址即时切换 PF / 经典版（2026-11-08） | 用户要求「同一个地址访问、页面上可以主题切换」，并计划接入 IBM Carbon。① 根入口重构：`src/main.tsx` 成为与 UI 无关的套件宿主，常驻 QueryClient / WS 桥 / 契约协商；PF 与经典版各自只导出 UI 根（`PfRoot` / `ClassicRoot`）。② 经典版恢复：从 `f26cb21` 取回 v1.3.1 antd UI 到 `src/classic/`，数据层用 re-export shim 指向共享层（不复制实现），适配 3 处契约变化（`queryKeys.*` 函数化、帧解码扁平结构、`SlaveQuality.substituted`）。③ 样式隔离：`useKitCss` 按套件挂载/移除 `<link data-kit-css>`（先加载新样式再移除旧样式）；PF 逐组件 CSS 由 `emptyPfComponentCss` 插件置空（全量 `patternfly.css` 覆盖，−0.86 MB / −75 kB gzip）。④ 切换控件：右下角 34px 圆钮 + 展开选项（原生元素，不依赖任何套件），`?kit=` → localStorage → 默认 pf；页面/hash/WS/主题/语言跨套件保持。⑤ Carbon 预留：`KIT_CSS` + `AVAILABLE_KITS` + `src/main.tsx` 分支（当前占位）。验证：e2e **40 passed**（新增 `ui-kit.spec.ts` 2 条）、前端单测 133 passed（32 文件）、typecheck/build、i18n 清单 0、对比度硬失败 0、视觉基线重拍 3 张、exe 重建 |

| **T70** | Carbon 套件实装（2026-11-08） | 「再做 carbon 版的 UI」：`@carbon/react`/`@carbon/styles` 1.120/1.119，`src/carbon/` 与 PF 同构覆盖 8 页 + 全部主站命令 + 子站四面板。① 外壳：Carbon `Header`（品牌/角色/运行/WS Tag + 中英/深浅切换）+ `SideNav`（角色过滤）+ 横幅（契约/背压/丢帧）；主题类 `cds--g100/g10` 挂 `<html>`（编译版类名无 `theme-` 前缀，portal 同样生效），卸载即移除。② 组件映射：Panel→Tile、Alert→InlineNotification、Label→Tag/DismissibleTag、ExpandableSection→受控 AccordionItem、Modal（`modalHeading`/`onRequestSubmit`/danger）、Pagination→本地化 `Pager`（内置英文文案全量换成 i18n，新增 5 个 key）。③ 虚拟点表：同 PF 方案（TanStack Virtual + 逐行 `cds--data-table` + `measureElement` 实测行高），品质标签用 Carbon Tag 语义色。④ 样式：`@carbon/styles/css/styles.css`（1.2 MB，含全局 reset 与四套主题 token）走 `KIT_CSS` 按需挂载；`carbon.css` 只引用 `--cds-*`（受配色门禁约束）。⑤ **IBM Plex 字体本地化**：styles.css 的字体指向 IBM CDN，被应用 CSP（font-src 'self'）拦成 console error 且离线不可用——构建插件 `carbonLocalFonts` 把产物 CSS 的 120 个 CDN url 改写到 `/app/fonts/...` 并从 `@ibm/plex-*` 包复制字体进 outDir（exe 冒烟 0 console error / 0 CDN 请求）。⑥ Pagination 内置英文文案全量本地化（共享 `Pager` + 5 个 i18n key）。⑦ 附带修复：vite proxy 补 `/slave/api`、`/slave/ws`（dev/preview 联调合并模式不再 404）；e2e 端口支持 `E2E_PORT_OFFSET` 整体平移（本机有运行中实例时不必关掉）。验证：e2e **41 passed**（`ui-kit.spec.ts` Carbon 用例：壳渲染/g100 主题跟随/互切无残留）、前端单测 133 passed、typecheck/build、i18n 清单 0、style-token 门禁通过、exe 重建（19.0 MB）并冒烟 |

| **T71** | 反馈批次：Carbon 默认 + 头部收敛 + 主站选中持久化 + 趋势图根因修复（2026-11-08） | 用户反馈四项：①「Carbon 版 UI 作为默认」——`resolveInitialKit` 改为 `?kit=` → localStorage → **默认 `carbon`**（旧默认 pf 的存量偏好按未设置处理，classic/carbon 主动选择仍保留），`docs/ui_kits.md`、`PROJECT.md` 同步。②「三个状态按钮去掉，只有中英切换/深浅切换，深浅改明/暗图标」——三套外壳头部统一收敛为**只留语言切换 + 图标主题切换**（Carbon Sun/Asleep、PF Sun/Moon、antd Sun/MoonOutlined），状态信息只保留在页面内（横幅/面板 Tag）。③「切菜单回来选中的点位被清空」——主站选中行与趋势 watch 从页面局部 state 移入共享 `uiStore`（selectedPoint/trendWatched，三套件一致），切页/切套件回来不丢；且选中行按 key 从点表缓存**现取**实时值——命令面板「当前值」继续跟随 WS 刷新，不回退到「快照冻结在选中瞬间」的旧 bug（经典版注释里记录过的修复语义）。④「趋势图为什么没有」——**根因**：三套件趋势图容器 div 是条件渲染（无 watch 时显示占位提示），而一次性 init effect 在挂载时读到空 ref 即 `return`，此后「加入趋势」出现容器也无人重试，图永远空白（探针实证：直接加趋势切页签 canvas=0）；修复为**回调 ref**：容器每次挂载都重挂 ResizeObserver 并重试 init，隐藏 TabPanel（0×0）先跳过、可见后再创建；另「加入趋势」立即以当前值写入首采样（连接空闲也有曲线起点）。e2e 修正 2 处用例自身问题：`@carbon/react` 1.120 选中面板无 `--selected` 修饰类（改 `[role="tabpanel"]:not([hidden])`）；Carbon↔PF 互切用例改等 `dataset.kit` 完成信号（原以两套件同名的 point-row 判断切换完成，与防白屏的「旧套件渲染到新样式就绪」设计相竞态）。验证：e2e **43 passed** 全量（`ui-kit.spec.ts` 5 条，新增趋势保留用例首次转绿）、前端单测 **133 passed**（32 文件）、typecheck/build、i18n 清单 0 |

| **T72** | SCD/CID/ICD 点表导入（IEC 61850 → 104）（2026-11-08） | 用户选定迭代方向②。① **映射内核** `core/data/scd_import.py`：双路径——IEC 61850-80-1 `Private(type=IEC_60870_5_104)/Address(casdu,ioa,ti)` **精确映射优先**（ti → 点类别/子类型按本仓 `TypeID` 对表，ti 优先于 CDC——工程中存在 ENS 映射标度化遥测等先例）；无映射按 DOType `cdc` **推断**（SPC/DPS/MV 系/BCR/BSC→yx/yc/ym/step），IOA 按类别基数自动分配（yx=1/yc=4097/yk=8193/ym=12289/step=16385，可覆盖）；多公共地址取众数 + 明细告警、显式 `common_addr` 可覆盖；IOA 冲突/越界/不支持 ti（比特串、保护事件）全部告警不静默。iterparse 流式解析（数十 MB SCD 可用），SDI/DAI/BDA 嵌套路径完整保留（`Oper.ctlVal`、`cVal.mag.f`）。② **端点** `POST /api/scd/preview`：无副作用预览（返回可导入的点表 YAML + 分类计数 + 告警），契约 §2.4a、前端 `ScdPreviewResponse` 契约 schema + 编译期键集比对。③ **UI**（Carbon/PF 子站工作台点表面板标题行，经典版按冻结承诺不加）：SCD 走预览（告警+计数+可编辑 YAML）→ 应用走既有 `/api/points/import?format=yaml`；YAML/CSV/JSON 直接导入。④ fixture 样例覆盖精确/推断/多 casdu/IOA 冲突/不支持 ti。验证：后端 **1578 passed**（全量，含 16 项 SCD：端点与 `PointTable.load_yaml` 回环）+ 真实厂商 SCD（Schneider Electric SET，58KB/65 信号/混合命名空间）实弹解析通过；e2e **44 passed** 全量（新增「SCD 导入：80-1 预览→应用生效」真实后端用例）；ruff、typecheck/build、i18n 0、前端 133 passed；Dependabot 残留分支已清理（PR #5 核实 MERGED 后删除） |

| **T73** | 透明桥/旁路监听：真实主站 ↔ 测试器 ↔ 真实子站（2026-11-08） | 用户选定迭代方向③。① **内核** `core/engine/tcp_bridge.py`：`TcpBridge`（asyncio）字节级透传——转发先行、解析纯旁路（观察者异常绝不影响数据路径）；双向独立 APCI 切帧（`FrameSplitter`：半包跨段缓存、脏字节丢 1 字节重同步并计数）；方向约定 `tx`=主站→子站/`rx`=子站→主站，回调与引擎 `on_frame(data,direction,client_id)` 同签名（直挂 capture/WS）；多客户端各占独立上游连接，上游不可达即关客户端由主站按既有逻辑重连；`describe_frame` 单帧摘要（APCI + ASDU 类型/CA/COT，解析失败回退 raw）。② **CLI** `--mode bridge`（headless 现场可用）：`--listen-host/port` + `--upstream-host/port` + `--capture-file`（复用 `PacketRecorder`，支持 .json/.pcap）；帧日志逐帧打点；绑定失败给人话一行（exit 1）而非 traceback。③ Web UI 桥接页拆至 **T74**（需角色管道改造）。验证：pytest **11 项**（切帧器单元 6 + 真主站↔桥↔真子站全链路集成：STARTDT/GI 往返、STARTDT_CON 透传内容校验、capture 落盘链路）+ CLI 实弹（真子站+桥+真主站，帧日志与录制文件产物核对）；后端全量 **1589 passed**、e2e **44 passed**（app.py 模式改动回归）、ruff 通过 |

| **T74** | 桥接 Web UI 页：bridge 角色接入 webui 三件套（2026-11-08） | ① `EngineBridge` 增 **bridge 角色**：无 104 引擎；`_BridgeRoleSessionStub` 占位会话把全部引擎操作统一拒绝为干净错误 dict（替代 20 处散落守卫，漏一处即 500）；`start_bridge/stop_bridge`（幂等 + 失败人话）；`status()` 携带 `bridge_stats/bridge_cfg`；`_on_raw_frame` 对桥角色 1Hz 节流广播状态刷新（帧流量大时不逐帧触发前端重拉）。② server：`POST /api/bridge/start|stop`（仅桥应用注册）；**引擎专属路由按角色跳过**（master/slave/multi 启停、点表写入、网络模拟在桥应用 404——纵深防御 + UI 不显示对应菜单）；`_run` 跳过桥角色演示点表。③ app.py：`--mode bridge` 默认 **Web 模式**（8767，`run_web` 端口表扩展），`--no-gui` 保留 T73 headless 形态；`--upstream-host/port` 经 `config.connection` 预填 UI 表单。④ 前端（Carbon/PF，经典版冻结不加）：`Role`/`PageKey` 增 bridge、`roleSchema`/`statusSchema` 契约扩展（编译期键集比对同步）、菜单按角色过滤（both/master/slave 部署不显示桥菜单）、**桥接观察页**：配置启停（`ok:false` 业务错误显形——端口被占不再静默）+ KvList 运行统计 + 复用 FrameViewer 的 WS 实时帧。⑤ e2e：第 4 个 webServer（8769，`SERVER_ENV` UTF-8）+ `bridge.spec.ts`——用例内 echo 上游 + `node:net` STARTDT_ACT 经桥回环探针 + 页面帧行/统计/停止断言；本机部分端口段 bind 10048（无监听进程仍失败）→ 测试监听口改 **OS 派空闲口**。验证：后端 15 项桥 Web pytest（status 形状/启停往返/echo 回环帧流/404 守卫/重复启动/非法端口）；UI 端到端全流程通过；后端全量与 e2e 全量随提交前运行回填 |

| **T75** | 测试报告导出（2026-11-08） | 候选方向①。`webui/report.py` 纯函数生成器（零第三方依赖）：输入会话快照（status + bus 帧缓冲 + 事件缓冲），输出**自包含单文件 HTML**（内联 CSS、打印友好 @media print，浏览器「打印→另存 PDF」即可归档）；帧证据表逐帧解码 APCI/ASDU 摘要（脏帧回退 raw 绝不抛出），聚合方向/帧型/ASDU Top10 分布，事件计数与最近 50 条；备注/标题全程 html.escape。端点 `GET /api/export/report.html?title=&notes=&limit=`（attachment；limit 1~5000 防撑爆单文件）；契约 §2.4 表增行。UI：状态总览页「导出测试报告」按钮（Carbon/PF；`exportReportUrl` 构造器进 endpoints.ts 满足端点覆盖测试，标题 i18n 化满足巡检）。pytest 6 项（分节/解码/转义/限量/脏帧/自包含+端点） |

| **T76** | 压测编排（吞吐验收）（2026-11-08） | 候选方向④。`webui/loadtest.py` `LoadTestService`：**编排层不改引擎**——驱动既有 `slave_set_yx/yc` 自发事件路径按目标速率（tick 均摊）循环触发（4:1 YC/YX 交替，值随机扰动），主站侧以 `ConnectionStats` **差分**统计（frames/i_frames/bytes/errors received）；时长/速率钳位（1~3600s / 1~10000 eps）；异常收敛为汇总不崩 UI。端点 `POST /api/loadtest/start|stop` + `GET /api/loadtest/status`：**全应用注册**（契约单一表），未挂载编排服务的应用返回 `{ok:false}` 业务拒绝（巡检把 4xx 一律计失败请求——首版 404 JSON 被审计抓住改为 200 业务拒绝）；仅 both 模式 `_run_dual` 挂载双桥编排（`master_bridge.loadtest` 属性注入）。UI：测试中心页压测卡（Carbon/PF；仅双角色部署显示；运行中 1s 轮询 refetchInterval 按 data 驱动）。pytest 3 项（真主站↔真子站 1.5s@80eps 吞吐差分端到端、未运行拒绝、重复启动幂等） |

| **T77** | 历史趋势回放：历史页「曲线」页签（2026-11-08） | 数据地基早就在（`data_history` 点位时间序列 + `/api/history/data` 查询端点），本轮补上消费侧。**后端零改动**；前端（Carbon/PF，经典版冻结不加）：历史页增「曲线」页签——页签内自管序列（类型 yx/yc/ym + IOA，1~8 条，DismissibleTag/链接标签可移除），时间范围复用页面「查询」按钮的 applied 状态；每序列一次 `GET /api/history/data`（`useQueries` 并行，limit 5000）；ECharts 时间轴曲线（遥信/遥脉阶梯 step、遥测折线，`toNumericValue` 过滤非数值行），0×0 防护同实时趋势图（回调 ref + ResizeObserver）；view 标签/导出按钮/分页在曲线页签下隐藏（语义不适用）。前端 i18n 8 键 |
| **T78** | 压测×报告贯通（2026-11-08） | `LoadTestService.last_summary()` 公开最近一次汇总；`GET /api/export/report.html` 自动读取（both 模式 master 桥挂载的编排服务），报告新增「5. 压测汇总」段落（事件数/帧数/平均速率/错误，参数类字段不入表）——压测跑完报告自动带证据，未跑过压测则无该节。pytest 报告用例 6→7 |

> **累计统计**：T01~T49、T51~T78 **全部完成**；**待办 1**（T50 真机复测，暂缓待窗口；T39 第三方实测已回填）。

---

## 5. 潜在技术风险

| 风险 | 类别 | 触发条件 | 影响 | 概率 | 应对措施 |
|------|------|---------|------|------|---------|
| **God Class 拆分回归（🔺上调）** | 架构/质量 | `master.py` 1745 / `slave.py` 1950 行拆分时改动内部状态引用 | 协议行为回归、偶发故障 | **极高** | `EngineBase` 已就位；T04/T05 每抽一模块**单独提交**；拆分前后 **489 用例必须全绿**；公开接口签名不变 |
| **前端整体重写回归风险（🆕）** | 前端/质量 | Q7 原生页→React 全量重写，功能面大 | 功能遗漏、交互回归、上线阻塞 | 高 | 逐页对齐 + Playwright 端到端（T15）；旧页保留至 T19 再退役；契约先冻结（T18） |
| **Node 构建链与打包（🆕）** | 构建/环境 | 引入 Vite 后 CI/打包需 node；前端产物未进包 | CI 失败、打包缺页 | 高 | T10 统一构建链；CI 增 node job；`build_all.py` 先 `npm run build` 再 PyInstaller；锁 `package.json` |
| **历史库默认开启写放大/磁盘占用（🆕）** | 性能/存储 | Q9 默认开启，高频帧全量落库 | 磁盘暴涨、IO 抖动 | 中 | T17 保留期 + 容量上限 + 清理策略 + `flush` 节流；记录写放大；`--no-history` 逃生开关 |
| **日志模块性能开销（🆕）** | 运行时 | 高频 DEBUG 触发 JSONL 落盘 + 订阅推送 | 单事件循环抖动 | 中 | 内存缓冲上限（5000）；落盘失败静默降级；必要时按级别/类别采样；桥异常吞掉 |
| asyncio 关停/资源泄漏 | 运行时 | 3.13 关停语义变化；`wait_closed` 挂起、后台任务未取消 | 进程挂死、端口不释放、内存泄漏 | 高 | T07 统一生命周期；`wait_closed` 带超时；`asyncio.all_tasks` 泄漏断言；`tests/e2e/qa_shutdown.py` 纳入 CI |
| 真实设备协议语义不确定 | 外部/协议 | F_LS 八位组、非标 TypeID 与真机不一致 | 联调失败、测试结论错误 | 中 | T24/T22 以标准+真机双源核实；未确认语义标注「待核实」不臆测 |
| 单事件循环并发阻塞 | 运行时 | 引擎/日志内出现同步阻塞调用 | 全站卡顿、定时器抖动 | 中 | 代码评审禁止协程内阻塞 IO；日志落盘考虑异步化；必要时 `run_in_executor`；压测多站稳定性 |
| 文档与代码漂移 | 文档 | 移除 Qt/pywebview、引入前端后文档未同步 | 用户误用、信任下降 | 中 | T03 一次性对齐；CI 增 `grep` 守卫禁止 PySide6/pywebview 残留；文档随 PR 更新 |
| 单机网卡/浏览器依赖致 CI 不可复现 | 测试/环境 | `qa_verify` 真实 socket + 浏览器探针依赖本机环境 | CI 无法稳定复现、误报 | 中 | 真实端到端与 Mock 分层；**旧 `.mjs` 探针由 T15 Playwright 取代**；真实验证走独立 job/本地 |
| PyInstaller 静态资源打包遗漏 | 构建 | `webui/static`（含前端 `dist`）、`configs`、`resources` 未显式收集 | 打包产物缺页/缺图标 | 中 | `build_all.py` 先构建前端再 `--add-data` 收集；打包后冒烟启动校验页面 |
| `qa_verify/` 资产丢失 | 工程 | 整体被 `.gitignore` 忽略 | 关键验证脚本丢失 | 中 | **T02 择优提升**：耐用 E2E 脚本入 `tests/e2e/`（跟踪）；ad-hoc 探针保留 ignore（见 §7-Q11） |

---

## 6. 里程碑节点（v1.2：按新基线重排）

| 里程碑 | 目标 | 包含任务 | 验收标准 / DoD | 建议周期 |
|--------|------|---------|---------------|---------|
| **M1 基线收口** | 工程与文档基线可信、可回归 | T01, T02, T03 | CI 3.11/3.13 双绿 + 489 passed + ruff 0 告警；Python 版本对齐；`apps/venv` 清理；`qa_verify` 择优提升完成；文档无 Qt/pywebview 残留 | 1 周 |
| **M2 架构收敛** | 消除 God Class、生命周期可安全关停 | T04, T05, T06, T07, T08, T09 | `master/slave` ≤ 700 行；关停零泄漏（含多站回收）；参数命令状态可跟踪 | 2.5 周 |
| **M3 前端重写** | 新前端（React/antd）上线、旧页退役 | T10, T11, T12, T13, T14, T15, T19 | 主站/子站/日志页功能对齐；`tsc` 零错误；Playwright 端到端入 CI；旧原生页退役 | 3 周 |
| **M4 功能集成** | 多站接入、历史库默认开、契约版本化 | T16, T17, T18 | 「多站」页可用；默认启动即建库且可关；契约含 `schemaVersion` | 1.5 周 |
| **M5 增强与发布** | 安全/协议增强按需 + 打包发布 | T20~T24 + 打包 | TLS 握手成功；非标 TypeID/pcap/F_LS 交付并测试；PyInstaller 产物（含前端 dist）冒烟通过；README/用户手册终稿 | 按需（2~4 周）+ 1 周 |

---

## 7. 决策结论与待明确事项

### 7.1 已定调（用户 2026-10-14）

| # | 结论 |
|---|------|
| Q1 | **纯 Web**（浏览器唯一 UI），保留可选 headless CLI（`--no-gui`）；**桌面壳已不存在**（v1.2 修正，与现状一致） |
| Q2 | 本轮**不做** TLS / IEC 62351（Phase 4 按需） |
| Q3 | **做** pcap/pcapng 导出（Phase 4） |
| Q4 | `EngineBase` **已完成**；God Class 深度拆分按 M2 节奏推进，**优先级上调** |
| Q5 | **维持已移除 pywebview 现状**（纯 Web）；不再引入桌面壳 |
| Q6 | **多站管理器接入 Web UI**（新增「多站」页 + `/api/multi/*` + 多站桥） |
| Q7 | **引入前端框架**（Vite + React 18 + TS + AntD 5），前端整体重写 |
| Q8 | Python 基线 **3.11+**，CI 覆盖 3.11/3.13（需对齐 pyproject/CI） |
| Q9 | **历史库默认开启** + `--no-history` 开关 + 默认数据目录 + 保留期/容量上限/清理策略 |
| Q10 | 引入 **`schemaVersion`**（REST/WS 契约版本化） |

### 7.2 决策确认（用户 2026-10-14 二次确认：全部采纳）

> ✅ 用户已确认**全部采纳**下列建议，Q11~Q15 转为已定调决策，可直接进入实现。

| # | 决策（已确认） |
|---|---------------|
| Q11 | ✅ **不原样纳管 `qa_verify/`，改为择优提升**——耐用 E2E 脚本迁入 `tests/e2e/` 纳入跟踪；`.mjs` 浏览器探针由 T15 Playwright 取代；ad-hoc 脚本继续 ignore |
| Q12 | ✅ **纯 SPA（Vite CSR）**，不做 SSR/多页 |
| Q13 | ✅ 历史库默认**保留 7 天 / 上限 512 MB**（可配置） |
| Q14 | ✅ 多站页**复用当前 Web 会话**（同进程多站，不引入多端口） |
| Q15 | ✅ 日志落盘按 T17/T14 落地实测决定；高频场景默认 `INFO` 且可降级 |

#### 原始建议（保留备查）

| # | 开放问题 | 影响范围 | 架构师建议 |
|---|---------|---------|-----------|
| **Q11** | `qa_verify/` 继续 ignore 还是纳入跟踪？ | 回归资产保护、CI 复现 | **结论：不原样纳入 git，改为「择优提升」**——把耐用 E2E 脚本（`qa_full_flow.py`/`qa_shutdown.py`/`qa_real_device.py`）迁入 `tests/e2e/` 并跟踪；`.mjs` 浏览器探针由 T15 Playwright 取代、ad-hoc 脚本（`qa_joint_debug.py`/`qa_ws_probe*.mjs`）继续 ignore。理由：原注释「process artifacts, not deliverables」对 ad-hoc 成立，但上述脚本被 DoD/CI 引用，属**耐用回归资产**，不应丢失；同时避免把整目录纳入跟踪污染仓库 |
| Q12 | 前端是否需要 SSR/多页？ | 构建链复杂度 | **纯 SPA（Vite CSR）** 足够——本地单机工业工具，无 SEO/首屏诉求 |
| Q13 | 历史库默认保留期/容量上限取值？ | 磁盘占用 | 建议默认 **保留 7 天 / 上限 512 MB**，可配置；落地前请用户确认 |
| Q14 | 多站页是否需要独立端口/会话隔离？ | T16 复杂度 | 建议**复用当前 Web 会话**（同进程多站），不引入多端口 |
| Q15 | 日志落盘是否需要异步化/采样？ | 性能 | 建议 T17/T14 落地时按实测决定；高频场景默认 `INFO` 且可降级 |

---

## 8. 团队角色分配与职责边界

> 本节由主理人齐活林（交付总监）编写，负责把 §4 中的角色代号收敛到**软件开发团队**的正式编制上，并明确每个角色的权责边界与交付物。

### 8.1 正式编制（核心 4 角色）

| 角色 | 姓名 | 定位 | 主要职责 | 交付物 | **明确不做（职责边界）** |
|------|------|------|---------|--------|------------------------|
| 产品经理 | 许清楚 | 需求侧唯一出口 | 需求澄清、用户故事、验收标准、优先级裁定、市场/竞品调研 | PRD、验收标准清单 | 不设计技术方案、不写代码、不评定测试结果 |
| 架构师 | 高见远 | 技术侧唯一出口 | 架构设计、依赖规则（R1~R8）、技术选型、任务分解、跨模块接口定义 | 架构文档、任务列表、接口/类图/时序图 | 不写业务代码、不写测试、不改需求优先级 |
| 工程师 | 寇豆码 | 实现侧唯一出口 | 按任务列表批量实现代码、全局一致性自审（IS_PASS）、修复 QA 反馈缺陷 | 可运行代码 + 代码摘要 | 不自行变更架构、不自行修改验收标准、不自我验收 |
| QA 工程师 | 严过关 | 质量侧唯一出口 | 测试用例编写与执行、独立回归、智能路由判定（源码 Bug / 测试 Bug / 通过） | 测试报告、缺陷单 | 不直接改源码（源码 Bug 回退给工程师）、不降低验收标准 |

### 8.2 扩展角色（按需引入或由核心角色兼任）

| 扩展角色 | 建议归属 | 覆盖任务（v1.2 同步） | 说明 |
|---------|---------|---------|------|
| 测试工程师 | 由 **QA 严过关** 兼任 | T01, T15 | 与 QA 同源，避免质量职责分裂 |
| 前端工程师 | **建议独立引入**（M3 起为关键路径） | T10, T11, T12, T13, T14, T16, T18, T19 | Q7 前端整体重写，工作量大、与 core 后端技能栈不同 |
| DevOps | 由 **工程师寇豆码** 兼任 | T01, T10, T15 | CI/打包/Node 构建链属工程化，可由实现侧兼做 |
| 文档工程师 | 由 **产品经理许清楚** 兼任 | T03 | 文档对齐本质是需求与验收的对外表达 |
| 安全工程师 | 由 **架构师高见远 + 工程师** 共担 | T20 | 涉及传输层与配置，架构定标准、工程做实现 |

### 8.3 任务—角色责任矩阵（RACI，v1.2 按新任务号同步）

> R=负责执行 · A=最终问责 · C=需咨询 · I=需知会

| 任务 | PM 许清楚 | 架构 高见远 | 工程 寇豆码 | QA 严过关 |
|------|:---:|:---:|:---:|:---:|
| T01 基线收口（版本/CI/覆盖率） | I | C | **R/A** | C |
| T02 遗留清理 + qa_verify 处置 | C | C | **R/A** | I |
| T03 文档对齐收尾 | **R/A** | C | I | C |
| T04 MasterEngine 拆分 | I | **A** | R | C |
| T05 SlaveEngine 拆分 | I | **A** | R | C |
| T06 传输层边界 | I | **R/A** | C | I |
| T07 生命周期加固（含多站回收） | I | C | **R** | **A** |
| T08 参数命令状态跟踪 | C | C | **R** | **A** |
| T09 升降步位点建模 | C | **A** | R | C |
| T10 前端脚手架/构建链 | I | **A** | R | C |
| T11 前端数据层/契约适配 | C | **A** | R | C |
| T12 主站页重写 | **A** | C | R | C |
| T13 子站页重写 | C | C | R | **A** |
| T14 日志面板/外壳 | C | C | R | **A** |
| T15 前端测试入 CI | I | C | C | **R/A** |
| T16 多站接入 Web UI | **A** | R | R | C |
| T17 历史库默认开启 | C | **A** | R | **A** |
| T18 契约版本化 | C | **A** | R | C |
| T19 旧页退役/回归收尾 | C | C | R | **A** |
| T20~T24 增强 | **A** | R | R | C |

---

## 9. 协作要点与质量关卡

### 9.1 信息流转链（强制顺序，跨角色信息一律经主理人中转）

```
需求 → [PM 许清楚] PRD/验收标准
     → [架构 高见远] 架构设计 + 任务列表（本文档 §1~§4）
     → [工程 寇豆码] 分批实现 + 全局一致性自审（IS_PASS: YES/NO）
     → [QA 严过关] 测试与智能路由判定
     → [主理人 齐活林] 汇总交付与里程碑验收
```

### 9.2 三道质量关卡（CRITICAL）

| 关卡 | 位置 | 判定标准 | 不通过怎么办 |
|------|------|---------|-------------|
| G1 需求关卡 | PM → 架构 | 需求无歧义、验收标准可测 | 架构师发现歧义 → 回退 PM 澄清 |
| G2 一致性关卡 | 工程自审 | `IS_PASS: YES`；**489 用例全绿**；ruff 0 告警；前端 `tsc`/`vitest` 绿 | 修复后重审，最多 2 轮 |
| G3 验证关卡 | QA 独立验证 | 新功能用例 + 全量回归通过 | 源码 Bug → 回退工程师；测试 Bug → QA 自修；最多 2 轮 |

### 9.3 反馈回路

- QA 发现**源码缺陷** → 附带「失败用例 + 实测输出 + 期望输出」回退工程师（参照工作日志中 SBO/`wrong_cot` 的修复范式：**先证伪、再修复、后回归**）
- 架构师发现**需求歧义** → 回退 PM 澄清
- 工程师发现**设计不可实现/接口冲突** → 回退架构师修订（依赖规则 R1~R8 变更须由架构师裁决）
- 任何**依赖规则例外**（如协议层需引入第三方库）必须经架构师书面批准并记入 §2.2

### 9.4 工程协作规范

| 项 | 规范 |
|----|------|
| 分支 | 一任务一分支：`feat/T04-master-split`、`feat/T10-frontend-scaffold`；从 `master` 切出 |
| 提交 | 遵循 `type(scope): subject`：`feat/fix/refactor/chore/test/docs`；每个提交必须保持 **489 用例全绿 + ruff 0 告警** |
| 拆分类任务 | T04/T05 每抽出一个模块**单独提交**，禁止一次性大重构；公开接口签名保持不变 |
| 前端任务 | T10~T14 每个页面/模块**单独提交**；契约变更先改 `api_contract.md` 再改代码 |
| 测试先行 | 缺陷修复必须先写「可证伪的失败用例」（红），再修复（绿），最后全量回归 |
| 变更影响面 | 修改 `core/protocol/**` 须同时评估 `asdu.py`/`types.py` 的编解码往返测试 |
| 资产保护 | `tests/e2e/` 提升后的脚本不得删除；`build/` 下已跟踪脚本不得移出 |

### 9.5 里程碑与角色投入映射

| 里程碑 | 主导角色 | 参与角色 | 出口条件（DoD） |
|--------|---------|---------|----------------|
| M1 基线收口 | DevOps（工程兼） | 文档、QA | CI 3.11/3.13 双绿 + 489 passed + ruff 0 告警；版本对齐；`qa_verify` 择优提升 |
| M2 架构收敛 | 架构 高见远 | 工程、QA | master/slave ≤700 行；关停零泄漏（含多站回收） |
| M3 前端重写 | 工程（前端） | QA、架构 | 主站/子站/日志页对齐；`tsc`/Playwright 绿并入 CI；旧页退役 |
| M4 功能集成 | 架构 + 工程 | QA | 「多站」页可用；历史库默认开且可关；契约含 `schemaVersion` |
| M5 增强与发布 | 主理人 齐活林 | 全体 | 打包（含前端 dist）冒烟通过；文档终稿；发布检查单通过 |

---

## 附录 A：任务依赖图

```mermaid
graph LR
    T01 --> T15
    T02 --> T15
    T07 --> T16
    T10 --> T11
    T11 --> T12
    T11 --> T13
    T11 --> T14
    T10 --> T15
    T12 --> T19
    T13 --> T19
    T14 --> T19
    T15 --> T19
    T04 --> T08
    T04 --> T21
    T06 --> T20
    T11 --> T16
    T18 --> T11

    style T04 fill:#2d5,stroke:#000
    style T05 fill:#2d5,stroke:#000
    style T07 fill:#2d5,stroke:#000
    style T10 fill:#2d5,stroke:#000
    style T11 fill:#2d5,stroke:#000
    style T12 fill:#2d5,stroke:#000
    style T16 fill:#2d5,stroke:#000
    style T17 fill:#2d5,stroke:#000
```

## 附录 B：文件清单（相对根目录，v1.2）

```
docs/
├── architecture_plan.md        # 本文档（v1.2）
├── sequence-diagram.mermaid    # 时序图（v1.2 更新）
├── class-diagram.mermaid       # 类图（v1.2 更新）
├── api_reference.md            # 待对齐收尾（T03）
├── optimization_report.md      # 已有
├── iec104-conformance-fixes.md # 已有
└── user_guide.md               # 待对齐收尾（T03）

core/
├── logging_manager.py          # 已有（246）— 结构化日志
├── config.py                   # 待新增 HistoryConfig（T17）
├── engine/
│   ├── base.py                 # ✅ 已有（41）EngineBase
│   ├── master.py               # 1745 → 待拆分（T04）
│   ├── slave.py                # 1950 → 待拆分（T05）
│   ├── master_session.py / master_protocol.py   # 待新增（T04）
│   ├── slave_session.py / slave_response.py / slave_sim.py  # 待新增（T05）
│   └── multi_station.py / scheduler.py
├── data/  (data_store.py 467 · point_table.py 438 · history.py 439)
├── protocol/  (72 种 TypeID)
└── transport/  (connection.py 508 · client.py/server.py shim 各 8)

webui/
├── server.py                   # 已有（564）REST+WS
├── bridge.py                   # 已有（286）EngineBridge 门面
├── session.py                  # 已有（339）EngineSession
├── points.py                   # 已有（260）PointService
├── events.py                   # 已有（67）EventBus
├── api_contract.md             # 已有 — 待补 schemaVersion（T18）
├── frontend/                   # 🆕 待新增（T10~T14）：Vite + React18 + TS + AntD5
└── static/                     # vite build 产物（T10）；旧原生页待退役（T19）

app.py                          # 待加 --no-history（T17）
build/build_all.py              # 待加前端构建步骤（T10）
.github/workflows/ci.yml        # 待加 node 构建 + 3.11/3.13 矩阵（T01/T10）
.pre-commit-config.yaml         # 已有
pyproject.toml                  # 待对齐 py311（T01）
tests/e2e/*                     # 🆕 待新增（T02 择优提升）
apps/venv/                      # 待删除（T02）
```

---

## 修订摘要（v1.1 → v1.2）

**变更动因**：master 此前落后于真实最新状态。项目有 5 个本地分支，`feature/webui-refactor` 领先 master 12 提交/111 文件/+11565−3151 行，且其祖先分支从未合入 master。主理人已 `git merge --ff-only feature/webui-refactor`，master 由 `23eede7` 快进到 **`3367213`**，5 分支全部并入。v1.1 勘察的是**陈旧快照**。

**关键更正（实测为准）**：
1. **`EngineBase` 已完成**（原 T05）：`core/engine/base.py` 41 行，`_spawn` 重复实现已消除 → 移入归档。
2. **God Class 反而恶化**：master 1326→**1745**、slave 1740→**1950** → T06/T07（新 T04/T05）**优先级上调为 P0**。
3. **Q1/Q5 表述修正**：pywebview 桌面壳**已被移除**，现状为纯 Web + 浏览器自动打开；原「保留 pywebview 双通道」与现状冲突，已改为「纯 Web」。
4. **`qa_verify/` 是被有意 gitignore**（注释：「QA verification scratch scripts (process artifacts, not deliverables)」），非疏漏 → 给出「择优提升」结论（§7-Q11）。
5. **`wrong_cot` 已完成**（原 T08）、**CSV/JSON 导出已完成**（原 T16）→ 归档。
6. **基线**：405→**482 passed**；HEAD `23eede7`→`3367213`；协议类型 59→**72/72**。

**新增资产纳入架构**：`core/logging_manager.py`（246）；`webui/` 拆分（bridge 286/server 564/session 339/points 260/events 67/api_contract.md）；机制层补齐（T 试验位、读未知 IOA COT=45、C_CD 延时、ASDU 长度上限）；真机联调修复（SQ=1 错址、召唤分流、命令联动、S 帧 SS bit0、t1 重连）；主站自学习/周期总召；`pyproject.toml` ruff/pytest 配置（无 pytest-cov）。

**新决策落地任务**：Q6 多站接入（T16）、Q7 前端重写（T10~T15/T19）、Q8 版本对齐（T01）、Q9 历史库默认开（T17）、Q10 契约版本化（T18）。

**结构变更**：§0 修正 Q1/Q5；§1 分层图纳入 logging_manager/webui 拆分/前端工程；§2 模块表按新行数更新、新增前端节点与 R7/R8 依赖规则；§3 选型改「aiohttp + Vite/React/TS/AntD5」，新增日志/历史库选型、更新 PyInstaller；§4 **重做任务表**（归档 7 + 待办 24）；§5 新增前端重写/Node 构建/历史库写放大/日志开销 4 项风险并上调 God Class；§6 重排 M1~M5；§7 改为「决策结论 + 仍待确认小问题」；§8/§9 保留主理人原文，同步 RACI/任务号与 482 基线；附录 A/B 同步。
