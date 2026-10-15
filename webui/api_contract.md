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

### 2.1 状态与点表

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/schema` | — | `{ok, schemaVersion, wsKinds: string[], wsSchemaKey}` |
| GET | `/api/status` | — | `Status`（见 §4.1） |
| GET | `/api/points` | — | `{points: Point[]}`（见 §4.2） |
| GET | `/api/recent` | — | `{frames: Frame[], events: EngineEvent[]}`（见 §4.3 / §4.4） |

### 2.2 主站命令

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/master/start` | `host: str="127.0.0.1"`, `port: int=2404 (0-65535)`, `addr: int=1 (≥0)`, `reconnect: bool=true`, `gi_interval: number=0 (≥0)`, `tls?: TlsOptions`（可选，见下方说明） | `{ok, error?}` |
| POST | `/api/master/stop` | — | `{ok, error?}` |
| POST | `/api/master/gi` | `qoi: int=20`（1–16 组召唤 ｜ 20 站召唤） | `{ok, error?}` |
| POST | `/api/master/clock` | — | `{ok, error?}` |
| POST | `/api/master/ci` | — | `{ok, error?}` |
| POST | `/api/master/reset` | — | `{ok, error?}` |
| POST | `/api/master/test` | — | `{ok, error?}` |
| POST | `/api/master/read` | `ioa: int (≥0)` | `{ok, error?}` |
| POST | `/api/master/yk` | `ioa: int (≥0)`, `state: 0\|1 =0`, `select: bool=false`, `double: bool=false`, `with_time: bool=false`, `deactivate: bool=false` | `{ok, error?}` |
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
| POST | `/api/slave/sim` | `enabled: bool`, `yx_interval?`, `yc_interval?`, `yx_change_rate?`, `yc_change_range?` | `{ok, error?}` |

### 2.4 点表批量与导入导出

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/points/batch` | `type: str`, `ioas: int[]`, `action: "enable"\|"disable"\|"group"`, `group: int\|null` | `{ok, error?, ...}` |
| GET | `/api/points/yaml` | — | `text/yaml` 文本 |
| POST | `/api/points/yaml` | 原始 YAML 文本（非 JSON） | `{ok, error?, ...}` |
| POST | `/api/points/import` | 原始文本；`?format=csv\|yaml\|json\|auto`（默认 `auto` 按内容嗅探） | `{ok, error?, ...}` |
| GET | `/api/export/points.csv` | — | `text/csv` 文本 |
| GET | `/api/export/session.json` | — | `{role, status: Status, frames: Frame[], events: EngineEvent[]}` |

> 说明：`/api/points/import` 的 `auto` 嗅探顺序为 —— 以 `{` 开头 → `json`；
> 首行含 `,` 且含 `type` → `csv`；否则 → `yaml`。

### 2.5 日志

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/logs` | query：`level_min: str="DEBUG"`, `category?: str`, `source?: str`, `q?: str`, `limit: int=200 (≤2000)` | `{ok: true, logs: LogRow[], stats: LogStats}`（见 §4.5） |
| GET | `/api/logs/export` | — | JSONL 文本（`Content-Disposition: attachment`） |

### 2.6 主站参数状态查询（T08）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/master/param_state` | query：`ioa: int (≥0)` | `{ok, ioa, state: ParameterStateEntry \| null}` |
| GET | `/api/master/params` | — | `{ok, params: ParameterStateEntry[]}` |

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
}
```

> `type ∈ {"YX","YC","YK","YM","STEP"}`；`STEP` 为步位置点（`value` 为档位整数）。

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
