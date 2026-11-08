# Web API 契约

本文档是**前端（`webui/frontend/`）与后端（`webui/server.py`）之间唯一的接口约定**。
后端实现与本文档的一致性由自动自检保证，见文末「契约自检」。

---

## 1. 版本策略（schemaVersion）

**当前版本：`schemaVersion = 1`**

权威常量定义在 `webui/events.py::SCHEMA_VERSION`，后端所有位置均引用该常量，不得硬编码字面量。

### 1.1 携带位置

| 位置 | 字段 | 说明 |
|------|------|------|
| WS 消息信封 | `schemaVersion`（顶层） | `snapshot` / `frame` / `event` / `log` **四类消息全部携带** |
| `GET /api/status` | `schemaVersion` | 随状态一并返回，前端启动即可协商 |
| `GET /api/schema` | `schemaVersion` | 专用探测端点，返回 WS 消息种类清单 |

信封形态：

```json
{
  "kind": "frame",
  "schemaVersion": 1,
  "ts": 1730000000.123,
  "data": { }
}
```

### 1.2 递增规则

| 变更性质 | 是否递增 | 示例 |
|----------|----------|------|
| **破坏性**：删除字段、修改字段类型、改变字段语义 | **+1（必须）** | `value` 由 `float` 改为 `string` |
| **兼容性**：新增可选字段、新增消息 `kind`、新增端点 | 不递增 | 新增 `quality` 字段 |

### 1.3 兼容约定

1. **提供方（后端）**：不得删除或改义已有字段而不递增 `SCHEMA_VERSION`；新增字段必须是可选的。
2. **消费方（前端 / 旧原生 UI）**：必须容忍**未知字段**与**可缺省字段**，不得因多出字段而报错。
   旧原生 UI（`webui/static/js/app.js`）只读取 `msg.kind` 与 `msg.data`，因此
   **在信封顶层新增 `schemaVersion` 对旧 UI 完全向后兼容**——旧 UI 忽略该键即可。
3. **版本不匹配**：前端在 `schemaVersion` 与自身期望值不一致时，**告警 + 降级渲染，绝不崩溃**
   （仅使用双方共有字段，并在界面上给出明确提示）。

---

## 2. REST 端点

通用约定：

- 成功与业务失败均返回 **HTTP 200**，JSON 形如 `{"ok": true|false, ...}`；失败含 `error: string`。
- **参数校验失败**返回 HTTP **400**，body 同样为 `{"ok": false, "error": "..."}`。
- 请求体为 JSON（`Content-Type: application/json`）；标注「原始文本」的端点除外。
- 「必填」列中未标注的字段均有默认值，可省略。
- **合并模式（单进程双角色）**：主站 API/WS 保持 `/api/*`、`/ws`；子站挂在
  `/slave/api/*`、`/slave/ws`。`GET /api/schema` 的 `roles` / `slaveApiPrefix`
  告知前端可用角色与前缀；单角色模式下子站仍直接使用 `/api/*`。

### 2.0 消费方运行时校验（2026-11-07）

前端不再只靠本文档和手写类型对齐，而是把契约变成**可执行代码**：

| 层 | 位置 | 行为 |
|----|------|------|
| schema DSL | `webui/frontend/src/api/contract.ts` | 零依赖组合子（obj/arr/optional/unionOf…），失败抛 `ApiContractError`，带 JSON 路径 |
| 响应 schema | `webui/frontend/src/api/contracts.ts` | 覆盖全部 JSON 端点的响应形状；`struct` 推断出返回类型 |
| 客户端校验 | `webui/frontend/src/api/client.ts` | `apiGet/apiPost/apiPostText` **每次响应都校验**；schema 不符即抛错，不再静默读 `undefined` |
| 编译期锁 | `contracts.ts::ContractKeyChecks` | schema 字段集与 `types.ts` 响应接口逐项比对，多/少字段直接 `tsc` 失败 |
| 真实后端 e2e | `tests/e2e/specs/api-contract.spec.ts` | 用**同一份 schema** 校验真实 aiohttp 响应（主站/子站/连接后运行态） |

约定：未知字段忽略（后端纯新增不破坏前端）；业务失败统一 `{ok:false, error:string}`；
新增/修改响应字段时必须同步 `contracts.ts` 与 `types.ts`，否则编译或 CI 失败。

### 2.1 状态与点表

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/schema` | — | `{ok, schemaVersion, wsKinds: string[], wsSchemaKey, roles: Role[], slaveApiPrefix?}`（合并模式下 `roles=[master,slave]`、`slaveApiPrefix="/slave"`） |
| GET | `/api/status` | — | `Status`（见 §4.1） |
| GET | `/api/points` | — | `{points: Point[]}`（见 §4.2） |
| GET | `/api/recent` | — | `{frames: Frame[], events: EngineEvent[]}`（见 §4.3 / §4.4） |

### 2.2 主站命令

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/master/start` | `host: str="127.0.0.1"`, `port: int=2404 (0-65535)`, `addr: int=1 (≥0)`, `reconnect: bool=true`, `gi_interval: number=0 (≥0)`, `tls?: TlsOptions`（可选，见下方说明）, `redundancy?: RedundancyOptions`（可选，见 §4.11） | `{ok, error?}` |
| POST | `/api/master/stop` | — | `{ok, error?}` |
| POST | `/api/master/gi` | `qoi: int=20`（1–16 组召唤 ｜ 20 站召唤） | `{ok, error?}` |
| POST | `/api/master/clock` | — | `{ok, error?}` |
| POST | `/api/master/ci` | — | `{ok, error?}` |
| POST | `/api/master/reset` | — | `{ok, error?}` |
| POST | `/api/master/test` | — | `{ok, error?}` |
| POST | `/api/master/read` | `ioa: int (≥0)` | `{ok, error?}` |
| POST | `/api/master/yk` | `ioa: int (≥0)`, `state: 0\|1\|2 =0`（单命令 0=分/1=合；双命令 1=分/2=合）, `select: bool=false`, `double: bool=false`, `with_time: bool=false`, `deactivate: bool=false` | `{ok, error?}` |
| POST | `/api/master/setpoint` | `ioa: int (≥0)`, `value: number`, `kind: "short_float"\|"normalized"\|"scaled" ="short_float"`, `select: bool=false`, `with_time: bool=false`, `deactivate: bool=false` | `{ok, error?}` |
| POST | `/api/master/step` | `ioa: int (≥0)`, `state: 1\|2`（1=降, 2=升）, `select: bool=false` | `{ok, error?}` |
| POST | `/api/master/bitstring` | `ioa: int (≥0)`, `value: int (≥0, 32bit)` | `{ok, error?}` |
| POST | `/api/master/delay` | `delay_ms: int (0–60000)` | `{ok, error?}` |
| POST | `/api/master/param` | `kind: "float"\|"normalized"\|"scaled"\|"activation"`, `ioa: int (≥0)`, `value: number=0`, `qualifier: int=1` | `{ok, error?}` |
| POST | `/api/master/file` | `action: "directory"\|"select"\|"request"`, `ioa: int=0 (≥0)`, `file_name: int=0 (≥0)` | `{ok, error?}` |

> `with_time=true` → 带时标类型（YK: `C_SC_TA_1` / `C_DC_TA_1`）。
>
> `deactivate=true`（D1，纯新增可选字段，不影响 `schemaVersion`）→ 发送
> **撤销命令**：传送原因 COT=8 (DEACT)。适用于 `/api/master/yk`
> （C_SC/C_DC 及其带时标变体）与 `/api/master/setpoint`（C_SE 三种及
> 其带时标变体；IEC 60870-5-101/104 允许设点命令停止激活）。
> 子站应答 DEACTCON (COT=9)；撤销不走选择-执行（SBO）两段式，单帧直发。
> 缺省 `false` → 行为与改动前一致（COT=6 ACT）。

> `TlsOptions`（T20，纯新增可选字段，不影响 `schemaVersion`）：`{enabled: bool,
> certfile?: str, keyfile?: str, cafile?: str, verify?: bool=true,
> verify_client?: bool=false, server_hostname?: str}`，形态与多站
> `StationConfig.tls` 一致。仅 `enabled=true` 时生效；证书路径无效时返回
> `{ok: false, error: "TLS 配置无效: ..."}`。主站（客户端）通常只需 `cafile`
> （+ 双向认证时 `certfile`/`keyfile`）；子站（服务端）需 `certfile`/`keyfile`。

### 2.3 子站命令

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/slave/start` | `host: str="0.0.0.0"`, `port: int=2404 (0-65535)`, `addr: int=1 (≥0)`, `tls?: TlsOptions`（可选，见 §2.2 说明） | `{ok, error?}` |
| POST | `/api/slave/stop` | — | `{ok, error?}` |
| POST | `/api/slave/yx` | `ioa: int (≥0)`, `value: bool` | `{ok, error?}` |
| POST | `/api/slave/yc` | `ioa: int (≥0)`, `value: number` | `{ok, error?}` |
| POST | `/api/slave/ym` | `ioa: int (≥0)`, `value: int` | `{ok, error?}` |
| POST | `/api/slave/ep` | `ioa: int (≥0)`, `event_value: int=1 (0–65535)`, `with_time: bool=true` | `{ok, error?}` |
| POST | `/api/slave/ps` | `ioa: int (≥0)`, `states: int[]`（长度 1–8，元素 0/1） | `{ok, error?}` |
| POST | `/api/slave/response` | `ResponseBehavior` 字典（任意键，未启动时可暂存） | `{ok, error?}` |
| GET | `/api/slave/response` | — | `{ok, response: ResponseBehavior}`（见 §4.8；未启动时返回暂存/默认值） |
| POST | `/api/slave/sim` | `enabled: bool`, `yx_enabled?: bool=true`, `yc_enabled?: bool=true`（至少一项为 true）, `yx_interval?`, `yc_interval?`, `yx_change_rate?`, `yc_change_range?`, `yx_scope?: "selected"\|"all"`, `yc_scope?: "selected"\|"all"`, `yx_ioas?: int[]`, `yc_ioas?: int[]` | `{ok, error?}` |

> 模拟改造（第二批 ⑤）：
> - `yx_change_rate` 语义为**每周期翻转概率**（0~1，每周期对范围内每个 YX 点独立判定）；
> - YC 取值为**点表量程内随机**：声明了量程（`[min,max]` ≠ 缺省 ±99999）的点在
>   `[min, max]` 内均匀随机；未声明量程/量程非法的点回落「当前值 ± `yc_change_range`
>   比例浮动」（`yc_change_range` 仅对这些点生效）；
> - `yx_scope`/`yc_scope`（YX/YC 独立，默认 `"all"`）：`"all"`=全部点；
>   `"selected"`=仅 `yx_ioas`/`yc_ioas` 列出的点，**scope=selected 时对应 ioas
>   须为非空 int 数组（≥0），否则 `{ok:false}`**；点表外的 IOA 被跳过（上送 info 日志）。
> - `yx_enabled`/`yc_enabled`（默认均 true）：可**只模拟遥信或只模拟遥测**；两者都为
>   false 时拒绝启动。被关闭的类型即使 `scope="selected"` 也不要求 `ioas`，且模拟
>   循环中不产生该类报文。`GET /api/status` 会回显 `simulation_yx`/`simulation_yc`。

### 2.4 点表批量与导入导出

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/points/batch` | `type: str`, `ioas: int[]`, `action: "enable"\|"disable"\|"group"`, `group: int\|null` | `{ok, error?, ...}` |
| GET | `/api/points/yaml` | — | `text/yaml` 文本 |
| POST | `/api/points/yaml` | 原始 YAML 文本（非 JSON） | `{ok, error?, ...}` |
| POST | `/api/points/import` | 原始文本；`?format=csv\|yaml\|json\|auto`（默认 `auto` 按内容嗅探） | `{ok, error?, ...}` |
| POST | `/api/scd/preview` | SCD/CID/ICD 原始 XML 文本（IEC 61850-6 SCL）；`?common_addr=` 可选显式指定公共地址（缺省取出现最多的 casdu）、`?station=` 可选覆盖站名 | `{ok, yaml, station_name, common_addr, stats: Record<string,number>, warnings: string[]}` |
| GET | `/api/export/points.csv` | — | `text/csv` 文本 |
| GET | `/api/export/report.html` | `?title=&notes=&limit=`（limit=帧证据最大行数 1~5000） | `text/html` 自包含报告（attachment；浏览器打印即 PDF） |
| GET | `/api/export/session.json` | — | `{role, status: Status, frames: WsEnvelope<'frame', Frame>[], events: WsEnvelope<'event', EngineEvent>[]}`（`recent()` 原样导出） |

> 说明：`/api/points/import` 的 `auto` 嗅探顺序为 —— 以 `{` 开头 → `json`；
> 首行含 `,` 且含 `type` → `csv`；否则 → `yaml`。
>
### 2.4a 透明桥（所有角色应用均注册；非 bridge 角色调用人话业务拒绝 `{ok: false, error: 仅 bridge 角色支持该操作}`）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/bridge/start` | `{listen_host?, listen_port?, upstream_host?, upstream_port?}`（缺省回填 `0.0.0.0:2404` 与 status 的 host/port） | `{ok, error?}` |
| POST | `/api/bridge/stop` | — | `{ok, error?}` |

> 桥角色（T74）的 `GET /api/status` 额外携带 `bridge_stats`（frames/bytes/
> clients/resyncs/upstream_errors 计数，running 时存在）与 `bridge_cfg`
> （当前桥配置）；帧观察复用 `/ws` 的 `frame` 事件与 `/api/capture/*`。
> 桥应用**不注册**引擎专属路由（master/slave/multi 启停、点表写入、网络模拟）。

### 2.4b 压测编排（端点全应用注册；未挂载编排服务的应用返回 `{ok: false, error: 压测仅支持单进程双角色（both）模式}`）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/loadtest/start` | `{duration_s?: number, events_per_s?: number}`（1~3600s / 1~10000 eps，缺省 60/100） | `{ok, error?}`（双端引擎未运行时业务拒绝） |
| POST | `/api/loadtest/stop` | — | `{ok, summary?, error?}`（summary：events_sent/rx_frames/avg_eps/avg_fps/errors） |
| GET | `/api/loadtest/status` | — | `{ok, running, elapsed_s, duration_s, target_eps, events_sent, rx_frames, i_frames, bytes_received, fps, errors, summary?}` |

> 压测（T76）编排层不改引擎：驱动既有 `slave_set_yx/yc` 自发事件路径按目标速率
> 循环触发，主站侧以 `ConnectionStats` 差分统计吞吐（验收口径：每秒 N 条遥测
> 稳定上送不断链）。仅 both 模式挂载（双桥同进程）。

> `/api/scd/preview`（T72）**无副作用**：不修改当前点表，返回可直接投给
> `/api/points/import?format=yaml` 的点表 YAML 文本。映射规则
> （IEC 61850-80-1 `Private/Address(casdu,ioa,ti)` 精确映射优先，
> 无映射按 DOType `cdc` 推断 + IOA 自动分配）见 `core/data/scd_import.py`。

### 2.5 日志

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/logs` | query：`level_min: str="DEBUG"`, `category?: str`, `source?: str`, `q?: str`, `limit: int=200 (≤2000)` | `{ok: true, logs: LogRow[], stats: LogStats}`（见 §4.5） |
| GET | `/api/logs/export` | — | JSONL 文本（`Content-Disposition: attachment`） |

### 2.6 主站参数状态查询（T08）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/master/param_state` | query：`ioa: int (≥0)` | `{ok: true, ioa, state: ParameterStateEntry \| null}` 或 `{ok: false, error}`（未连接） |
| GET | `/api/master/params` | — | `{ok: true, params: ParameterStateEntry[]}` 或 `{ok: false, error}`（未连接） |

> `state` 为该 IOA 的装载/激活状态**快照**；从未下发过参数命令时为 `null`。
> 结构见 §4.6。参数命令（`POST /api/master/param`）下发后即可查询其
> `PENDING → OK/REJECTED → TERMINATED`（或 `TIMEOUT`）推进过程。

### 2.7 子站步位置（T09）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/slave/step` | `ioa: int (≥0)`, `value: int (-64..63)` | `{ok, error?}` |

> 置数并自发上送步位置信息（`M_ST_TB_1`, COT=3）。点表快照（§4.2）与 CSV/YAML
> 导出会带出 `STEP` 类型点。

### 2.8 多站（T16）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/multi/start` | `stations: StationConfig[]`（非空；`station_id` 必填且唯一，`port` 0–65535，`tls` 形态见 §2.2 `TlsOptions`） | `{ok, stations?, failed?, error?}`（`failed: {station_id, ok: false, error}[]`） |
| POST | `/api/multi/stop` | — | `{ok, error?}` |
| GET | `/api/multi/status` | — | `{ok, running, stations: StationStatus[], failed}` |
| GET | `/api/multi/summary` | — | `{ok, running, station_count, total_clients, uptime, stations: StationSummary[], failed}` |

> 多站管理器与主/子站会话独立；Web 会话关停时会随 `shutdown()` 一并回收
> （见 `webui/session.py::attach_multi_station`）。结构见 §4.7。
>
> **TLS 失败语义（T20，与单站一致：不静默降级为明文）**：TLS 配置无效的站
> **不会启动**，逐站报错出现在 `failed` 数组（`{station_id, ok: false, error}`），
> 其余站正常启动；全部失败时整体 `ok=false` 且不保留管理器。因此
> `StationStatus.tls_enabled` 只有 启用(`true`)/未启用(`false`) 两种实况，
> **不存在降级态**。`failed` 为纯新增字段，不影响 `schemaVersion`。

### 2.9 报文逐段翻译（第二批体验改造 ④）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/frames/decode` | query：`hex: str`（单帧 HEX，≤4096 字符） | `{ok, error?}` 或 `{ok: true, format: "I"\|"S"\|"U"\|"?", segments: Segment[]}` |

> `Segment = {title: str, lines: str[]}`。逐段拆解：APCI（起始/长度/控制域 →
> I/U/S 帧类型与序号）→ ASDU（TypeID 含义 / VSQ 与 SQ / COT 含义 / 源发与公共
> 地址 / 逐个信息体 IOA+值+品质+时标）。解析失败段只记备注行，不抛 5xx；
> `hex` 非法/过短返回 `{ok: false, error}`。前端报文查看器悬停 HEX 单元格时调用。

### 2.10 一键诊断包

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/diagnostics/export` | — | `application/zip` 附件（`Content-Disposition`） |

> 包内固定包含 `manifest.json` / `status.json` / `config.json` / `logs.json` /
> `frames.json` / `events.json` / `points.json` / `history.json` / `README.txt`。
> `config.tls.keyfile` 脱敏为 `<redacted>`；日志/报文/点表可能含现场业务值，
> 转发前请确认接收方。前端「运行状态」卡片提供下载按钮。

### 2.11 历史库查询（历史查询页）

> 历史库按角色分库（SQLite，默认开启；`--no-history` 关闭）。未启用时
> `/api/history/stats|data|frames` 返回 `{ok: true, enabled: false, ...}`（`rows` 为空数组），
> `/api/history/export` 返回 400。时间参数均为 **epoch 秒**；查询按时间戳**新→旧**返回。

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/history/stats` | — | `{ok, enabled, stats}`（stats 字段见 `HistoryDB.get_stats()`：`data_records`/`frame_records`/`buffered_data`/`buffered_frames`/`oldest_data`/`newest_data`/`db_size_bytes`/`dropped_records`） |
| GET | `/api/history/data` | query：`point_type?: str`（yx/yc/ym，空=全部）, `ioa?: int (≥0)` , `start?: number`, `end?: number`（epoch 秒）, `limit: int=500 (≤10000)` | `{ok, enabled, rows: HistoryDataRecord[]}` |
| GET | `/api/history/frames` | query：`direction?: "rx"\|"tx"`（空=全部）, `start?: number`, `end?: number`, `limit: int=500 (≤10000)` | `{ok, enabled, rows: HistoryFrameRecord[]}` |
| GET | `/api/history/export` | query：`type: "data"\|"frames"="data"`, 其余过滤参数同上（`limit` ≤200000） | `text/csv` 附件（`Content-Disposition`） |

### 2.12 网络异常模拟（B6）

> 传输层异常注入（延迟/丢包/重复/损坏/乱序/断线/限速），包装当前引擎的收发回调。
> **可在引擎启动前预设**：`enabled=true` 时，主站/子站启动会自动安装；
> 引擎停止时自动卸载，重启后按启用状态自动重装。响应 `{ok:false, error}` 时 HTTP 状态为 400。

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/simulation` | — | `{ok, enabled, installed, active, describe, condition: NetworkCondition, stats: SimStats, presets: string[]}`（见 §4.10） |
| POST | `/api/simulation` | `enabled: bool`；可选 `preset?: string`（§4.10 预设名）、`condition?: Partial<NetworkCondition>`（字段校验：概率 0..1、其余非负；未知字段 → 400） | `{ok, status?: SimulationStatus, error?}` |
| POST | `/api/simulation/reset` | — | `{ok}`（清零统计计数） |
| POST | `/api/simulation/disconnect` | `duration?: number=5 (0<d≤600)` | `{ok, error?}`（仅已安装引擎时有效） |

### 2.13 访问认证探测（B7）

> 服务端以 `--auth-token`（或环境变量 `IEC104_AUTH_TOKEN`）启动时，**除本端点外**
> 所有 `/api/*` 与 `/ws` 均需携带令牌，缺失/错误返回 **401** `{ok:false, error:"unauthorized"}`。
> 三种携带形态：`Authorization: Bearer <token>`、`X-Auth-Token: <token>`、`?token=<token>`
> （WS 无法自定义头，浏览器必须用 query）。静态页 `/app/*` 不拦截，供前端弹出令牌输入框。
> 未配置令牌时本端点返回 `required=false, valid=true`，其余行为与旧版一致。

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/auth` | 可带令牌（上述三种形态之一） | `{ok, required: bool, valid: bool}` |

### 2.14 报文录制/回放（E2）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/capture/status` | — | `{ok, recording, paused, frames, rx, tx, dropped, elapsed, file, files: CaptureFileInfo[], playback: CapturePlayback}` |
| POST | `/api/capture/start` | 可选 `name?: str`（单层文件名，`.i104/.json/.pcap/.pcapng`；缺省自动命名） | `{ok, recording, paused, frames, rx, tx, dropped, elapsed, file}` |
| POST | `/api/capture/stop` | — | `{ok, frames, file}`（停止并落盘） |
| POST | `/api/capture/pause` | — | `{ok, error?}` |
| POST | `/api/capture/resume` | — | `{ok, error?}` |
| GET | `/api/capture/files` | — | `{ok, files: CaptureFileInfo[]}` |
| GET | `/api/capture/download/{name}` | 单层文件名 | 文件流（附件下载） |
| POST | `/api/capture/export` | `name: str`, `format: "i104"\|"json"\|"pcap"\|"pcapng"` | `{ok, file, frames}`（同目录生成新文件） |
| POST | `/api/capture/load` | `name: str` | `{ok, file, frames, loaded, state, index, total, progress, duration, current}` |
| GET | `/api/capture/frames` | `offset?: int=0`, `limit?: int=200 (1–1000)` | `{ok, total, offset, rows: CaptureFrame[]}` |
| POST | `/api/capture/play` | `speed: number=1 (0.1–100)` | `{ok, ...CapturePlayback, error?}`（后台异步回放，仅离线展示） |
| POST | `/api/capture/playback/stop` | — | `{ok, ...CapturePlayback}` |
| POST | `/api/capture/playback/pause` | — | `{ok, ...CapturePlayback, error?}` |
| POST | `/api/capture/step` | `direction: "forward"\|"backward"="forward"` | `{ok, ...CapturePlayback, error?}` |

### 2.15 自动化测试中心（E1）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/tests/scripts` | — | `{ok, scripts: TestScriptInfo[]}`（`tests/scripts/*.yaml`） |
| POST | `/api/tests/run` | `scripts: string[]`（文件名数组，非空） | `{ok, run?: TestRun, error?}`（子进程顺序执行；单 run 互斥） |
| POST | `/api/tests/stop` | — | `{ok, error?}`（终止当前子进程） |
| GET | `/api/tests/status` | — | `{ok, running, run: TestRun \| null}`（日志最多 500 行） |
| GET | `/api/tests/reports/{run_id}/{name}` | run_id / 报告文件名（`.html/.json/.txt`） | 文件流（附件下载） |

---

## 3. WebSocket `/ws`

服务端在连接建立后**立即推送 `snapshot`**（快照先行），随后推送增量。
客户端可发送纯文本 `"refresh"` 请求一次 `snapshot`（只含 `points` 与 `status`）。

所有消息共用信封：`{kind, schemaVersion, ts, data}`。

| `kind` | `data` | 触发时机 |
|--------|--------|----------|
| `snapshot` | `{schemaVersion, points: Point[], status: Status, frames?: Frame[], events?: EngineEvent[], logs?: LogRow[]}` | 连接建立、收到 `"refresh"` |
| `frame` | `Frame` | 每次收发原始报文 |
| `event` | `{type: string, data: object}` | 引擎状态/连接/命令事件 |
| `log` | `LogRow` | 结构化日志 |

> 背压：每个订阅者队列容量 256，写满时**丢最旧消息**并累加丢弃计数。
> 丢弃累计值通过 `Status.dropped` 暴露，前端据此提示。

---

## 4. 数据结构

### 4.1 `Status`

```ts
{
  role: "master" | "slave"
  started?: boolean          // 会话是否已有引擎（连接中/已连接/监听中/连接失败都算）
  running?: boolean          // 引擎是否在运行
  state?: string             // 主站连接状态机字符串
  host?: string
  port?: number
  addr?: number
  points?: number            // 点位数
  dropped?: number           // 背压丢弃累计
  tx?: number                // 已发送帧数
  rx?: number                // 已接收帧数
  vs?: number                // 发送序号
  vr?: number                // 接收序号
  window?: string            // "k/n" 形式
  clients?: number           // 子站：客户端数
  client_list?: string[]
  simulation?: boolean
  simulation_yx?: boolean  // 当前模拟是否包含遥信
  simulation_yc?: boolean  // 当前模拟是否包含遥测
  schemaVersion?: number
}
```

### 4.2 `Point`

```ts
{
  ioa: number
  type: string
  name: string
  group?: number | string
  enabled: boolean
  value?: number | boolean | string | null
  quality?: string
  /** 类型细分：YX single/double；YC short_float/normalized/scaled；YK single/double */
  subtype?: string
  /** 仅 YK：是否需要选择-执行（SBO） */
  sbo?: boolean
}
```

> `type ∈ {"YX","YC","YK","YM","STEP"}`；`STEP` 为步位置点（`value` 为档位整数）。
> `subtype` / `sbo` 由主站定义表快照补充，供前端按点类型下发对应命令
> （YK 单/双命令、YC 设点类型）；老客户端可忽略这些可选字段。

### 4.3 `Frame`

```ts
{ direction: string, len: number, hex: string, client?: string }
```

> `bridge.recent()` / WS 增量返回的元素是**信封**形态 `{kind, schemaVersion, ts, data}`，
> 其中 `data` 为上述 `Frame` / `EngineEvent`。

### 4.4 `EngineEvent`

```ts
{ type: string, data: object }
```

### 4.5 `LogRow` / `LogStats`

```ts
LogRow  = { ts: number, level: "DEBUG"|"INFO"|"WARNING"|"ERROR"|"CRITICAL"|string,
            source: string, category: string, message: string, data?: object }
LogStats = { total?: number, by_level?: Record<string, number>, source?: string, [k: string]: unknown }
```

### 4.6 `ParameterStateEntry`

```ts
{
  ioa: number
  loadResult: "unknown" | "pending" | "ok" | "terminated" | "rejected" | "timeout"
  loadCot: number | null            // 装载应答的传送原因
  loadUpdatedAt: number | null      // monotonic 秒值（用于算时长，非绝对时间）
  activationResult: "unknown" | "pending" | "ok" | "terminated" | "rejected" | "timeout"
  activationCot: number | null
  activationUpdatedAt: number | null
}
```

### 4.7 `StationConfig` / `StationStatus` / `StationSummary`

```ts
StationConfig = {               // 字段均有默认值，仅 station_id 必填
  station_id: string
  station_name?: string, host?: string, port?: number, common_addr?: number
  max_connections?: number, point_table_file?: string, auto_generate?: boolean
  yx_count?: number, yc_count?: number, yk_count?: number, ym_count?: number
  spontaneous_enabled?: boolean, simulation_enabled?: boolean
  yx_interval?: number, yc_interval?: number, yx_change_rate?: number, yc_change_range?: number
  tls?: TlsOptions             // 形态见 §2.2；配置无效 → 该站不启动（§2.8）
}
StationStatus  = { station_id, station_name, port, common_addr, running, client_count,
                   yx_count, yc_count, yk_count, ym_count, simulation_active,
                   tls_enabled }        // 该站 TLS 实况：true=启用 / false=未启用
                                         // （不存在降级态：TLS 配置无效的站不会启动，
                                         //   见 §2.8 TLS 失败语义）
StationSummary = { id, name, port, clients, tls_enabled }
```

### 4.8 `ResponseBehavior`（子站应答行为）

`GET` / `POST /api/slave/response` 共用**同一分组形态**：`GET` 返回的
`response` 可直接作为 `POST` 的请求体回填（缺失分组/键一律取后端默认值，
故两侧结构恒定、可无损往返）。

```ts
ResponseBehavior = {
  delays?:     { gi?: number, command?: number, data?: number }          // 延迟（秒）
  errors?:     { drop_frames?: boolean, drop_rate?: number (0..1),
                 corrupt?: boolean, no_response?: boolean, wrong_cot?: boolean }
  quality?:    { invalid?: boolean, blocked?: boolean,
                 not_topical?: boolean, overflow?: boolean }             // 品质描述词注入
  connection?: { reject_startdt?: boolean, auto_stopdt?: boolean,
                 send_testfr?: boolean, testfr_interval?: number }       // 连接行为（秒）
}
```

> 取值语义与后端默认值见 `core/engine/slave_response.py::ResponseBehavior.from_dict`。
> `GET` 为**纯新增端点**，按 §1.2「兼容性变更」策略**不递增** `schemaVersion`。

### 4.9 `HistoryDataRecord` / `HistoryFrameRecord` / `HistoryStats`

```ts
HistoryDataRecord   = { id: number, ts: number, point_type: "yx"|"yc"|"ym"|string,
                        ioa: number, value: string, quality: string, source: string }
HistoryFrameRecord  = { id: number, ts: number, direction: "rx"|"tx"|string,
                        frame_type: string, hex: string, parsed: string, client: string }
HistoryStats        = { data_records: number, frame_records: number,
                        buffered_data: number, buffered_frames: number,
                        oldest_data: number, newest_data: number,
                        db_size_bytes: number, dropped_records: number }
```

### 4.10 `NetworkCondition` / `SimStats`（网络异常模拟）

```ts
NetworkCondition = {
  delay_ms: number, delay_variance_ms: number,
  loss_rate: number, duplicate_rate: number,
  corrupt_rate: number, corrupt_bits: number,
  reorder_rate: number, reorder_window: number,
  disconnect_rate: number, disconnect_duration_s: number,
  bandwidth_bps: number, direction: "rx"|"tx"|"both", active: boolean
}
SimStats = { rx_total, tx_total, rx_dropped, tx_dropped, rx_corrupted, tx_corrupted,
             rx_duplicated, tx_duplicated, rx_reordered, tx_reordered, disconnects,
             [k: string]: number }
// presets: clean | poor_wifi | congested | satellite | unreliable | intermittent | slow_link | stress
```

### 4.11 `RedundancyOptions` / `RedundancyStatus`（主站冗余）

```ts
RedundancyOptions = {           // POST /api/master/start（省略时沿用 CLI/--config）
  enabled?: boolean,
  standby_host?: string,
  standby_port?: number,        // 1–65535，且不能与主用 host:port 完全相同
  switch_timeout?: number,      // >0，默认 2.0s
  dedup_window?: number         // >=0，默认 5.0s
}
RedundancyStatus = {            // Status.redundancy（仅启用时存在）
  enabled: true,
  active: "primary" | "standby" | null,
  primary_connected: boolean, standby_connected: boolean,
  standby_host: string, standby_port: number,
  switch_timeout: number, dedup_window: number,
  failovers: number
}
```

### 4.12 `CaptureFileInfo` / `CaptureFrame` / `CapturePlayback`（报文录制/回放）

```ts
CaptureFileInfo = { name: string, size: number, mtime: number }
CaptureFrame = {
  timestamp: number, absolute_time: number,
  direction: "RX"|"TX", frame_type: "I"|"S"|"U"|"?",
  length: number, hex: string, metadata: Record<string, unknown>
}
CapturePlayback = {
  loaded: boolean, file?: string, state?: "stopped"|"playing"|"paused"|"stepping",
  index?: number, total?: number, progress?: number, duration?: number,
  current?: CaptureFrame | null
}
```

### 4.13 `TestScriptInfo` / `TestRun`（自动化测试中心）

```ts
TestScriptInfo = { id: string, name: string, description: string, role: "master"|"slave"|"?",
                   steps: number, tags?: string[], timeout?: number, error?: string }
TestRun = {
  id: string, status: "running"|"passed"|"failed"|"stopped"|"error",
  scripts: string[], started_at: number, ended_at: number | null,
  returncode: number | null,
  summary: { scripts: number, passed: number, failed: number } | null,
  lines: string[], results: { script: string, returncode: number }[],
  reports: { name: string, format: "html"|"json"|"txt", size: number }[]
}
```

---

## 5. 契约自检

实现与本文档的一致性由 `webui/contract_check.py` 保证，两种运行方式等价：

```bash
python -m webui.contract_check          # 独立运行，漂移时退出码非 0
./venv/Scripts/python.exe -m pytest tests/test_api_contract.py -q
```

自检内容：

1. **常量一致**：`webui/events.py::SCHEMA_VERSION` == `webui/frontend/src/api/schema.ts` 中的 `SCHEMA_VERSION`
2. **端点不漂移**：`create_app()` 实际注册的全部 `/api/*` 路由，与本文档 §2 表格中的端点集合**双向一致**
   （文档多写 / 实现漏写 / 实现多写 都会报错）
3. **信封带版本**：`EventBus.publish()` 产出的信封含 `schemaVersion`，且 `snapshot` 消息（由 `server.py` 构造）同样含
4. **版本策略存在**：本文档含「版本策略」章节与 `schemaVersion` 字样

> 新增端点时必须**同时**更新 §2 表格，否则自检失败——这是防止契约漂移的门禁。
