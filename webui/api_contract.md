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
| POST | `/api/master/start` | `host: str="127.0.0.1"`, `port: int=2404 (0-65535)`, `addr: int=1 (≥0)`, `reconnect: bool=true`, `gi_interval: number=0 (≥0)` | `{ok, error?}` |
| POST | `/api/master/stop` | — | `{ok, error?}` |
| POST | `/api/master/gi` | `qoi: int=20`（1–16 组召唤 ｜ 20 站召唤） | `{ok, error?}` |
| POST | `/api/master/clock` | — | `{ok, error?}` |
| POST | `/api/master/ci` | — | `{ok, error?}` |
| POST | `/api/master/reset` | — | `{ok, error?}` |
| POST | `/api/master/test` | — | `{ok, error?}` |
| POST | `/api/master/read` | `ioa: int (≥0)` | `{ok, error?}` |
| POST | `/api/master/yk` | `ioa: int (≥0)`, `state: 0\|1 =0`, `select: bool=false`, `double: bool=false`, `with_time: bool=false` | `{ok, error?}` |
| POST | `/api/master/setpoint` | `ioa: int (≥0)`, `value: number`, `kind: "short_float"\|"normalized"\|"scaled" ="short_float"`, `select: bool=false`, `with_time: bool=false` | `{ok, error?}` |
| POST | `/api/master/step` | `ioa: int (≥0)`, `state: 1\|2`（1=降, 2=升）, `select: bool=false` | `{ok, error?}` |
| POST | `/api/master/bitstring` | `ioa: int (≥0)`, `value: int (≥0, 32bit)` | `{ok, error?}` |
| POST | `/api/master/delay` | `delay_ms: int (0–60000)` | `{ok, error?}` |
| POST | `/api/master/param` | `kind: "float"\|"normalized"\|"scaled"\|"activation"`, `ioa: int (≥0)`, `value: number=0`, `qualifier: int=1` | `{ok, error?}` |
| POST | `/api/master/file` | `action: "directory"\|"select"\|"request"`, `ioa: int=0 (≥0)`, `file_name: int=0 (≥0)` | `{ok, error?}` |

> `with_time=true` → 带时标类型（YK: `C_SC_TA_1` / `C_DC_TA_1`）。

### 2.3 子站命令

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/slave/start` | `host: str="0.0.0.0"`, `port: int=2404 (0-65535)`, `addr: int=1 (≥0)` | `{ok, error?}` |
| POST | `/api/slave/stop` | — | `{ok, error?}` |
| POST | `/api/slave/yx` | `ioa: int (≥0)`, `value: bool` | `{ok, error?}` |
| POST | `/api/slave/yc` | `ioa: int (≥0)`, `value: number` | `{ok, error?}` |
| POST | `/api/slave/ym` | `ioa: int (≥0)`, `value: int` | `{ok, error?}` |
| POST | `/api/slave/ep` | `ioa: int (≥0)`, `event_value: int=1 (0–65535)`, `with_time: bool=true` | `{ok, error?}` |
| POST | `/api/slave/ps` | `ioa: int (≥0)`, `states: int[]`（长度 1–8，元素 0/1） | `{ok, error?}` |
| POST | `/api/slave/response` | `ResponseBehavior` 字典（任意键，未启动时可暂存） | `{ok, error?}` |
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
