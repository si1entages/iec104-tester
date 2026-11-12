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

> **P1-5 4xx 可诊断性**：HTTP 4xx 错误响应保留 `ok` / `error` 两键，并**纯新增**
> `code`（稳定机器可读码，如 `invalid_field` / `missing_field` / `invalid_json`）、
> `field`（出错的请求字段名，有则填）、`request_id`（12 位十六进制，用于把浏览器
> 报错与服务端日志关联）。前端 `okSchema` 用 `obj`（忽略未知字段），零回归。
> 目前为渐进式接入（先覆盖 `/api/frames/decode` 与 `/api/master/start` 的参数错误），
> 历史端点仍可能只返回短 `error` 串。

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
| POST | `/api/master/clock_offset` | `{samples?: number}`（1~20，缺省 5） | `{ok, samples: number[], count, avg_ms, min_ms, max_ms}` 或 `{ok: false, error}`（T80：连发 N 次时钟同步，按子站确认时标测偏差） |
| GET | `/api/alarms` | — | `{ok, config: {stale_seconds, comm_seconds, jump_delta, debounce, sound}, active: [{id, kind: 'limit'\|'stale'\|'jump'\|'comm', ioa: number\|null, message, ts, age_s, acked, cleared}], new_since_poll, history_total}`（T93 值守告警；前端 2s 轮询） |
| GET | `/api/alarms/history` | `?limit=`（缺省 100） | `{ok, history: [Alarm], total}` |
| POST | `/api/alarms/ack` | `{id}` | `{ok}`（无此告警返回 `{ok: false}`） |
| POST | `/api/alarms/config` | `{stale_seconds?, comm_seconds?, jump_delta?, debounce?, sound?}` | 同 `/api/alarms` 快照（运行时调阈值） |
| POST | `/api/master/doctor` | `{host, port, addr?, observe_seconds?}`（1~10，缺省 3） | `{ok, report: {ok, conclusion, duration_ms, steps: [{key: 'tcp'\|'startdt'\|'dataflow', ok, detail, evidence}]}}`（T94 连接医生：分层自检，结论随报告附存 §4.10a） |
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
| POST | `/api/master/file` | `action: "directory"\|"select"\|"request"\|"upload"`, `ioa: int=0 (≥0)`, `file_name: int=0 (≥0)`, `cot?: int (5/6/13)`, `qualifier?: int (0-7)`, `data?: str (upload 专用，hex，≤64 KiB)`, `segment_size?: int (1-255, 默认 200)` | `{ok, error?}` |

> `with_time=true` → 带时标类型（YK: `C_SC_TA_1` / `C_DC_TA_1`）。
>
> `deactivate=true`（D1，纯新增可选字段，不影响 `schemaVersion`）→ 发送
> **撤销命令**：传送原因 COT=8 (DEACT)。适用于 `/api/master/yk`
> （C_SC/C_DC 及其带时标变体）与 `/api/master/setpoint`（C_SE 三种及
> 其带时标变体；IEC 60870-5-101/104 允许设点命令停止激活）。
> 子站应答 DEACTCON (COT=9)；撤销不走选择-执行（SBO）两段式，单帧直发。
> 缺省 `false` → 行为与改动前一致（COT=6 ACT）。

> **WP3 文件传输（2026-11-12 按新口径验收：本仓真实 TCP 互测 + 多开源实现交叉证据）**
>
> - `action="upload"` 为**上传方向（主站→子站）**：主站发 `F_SC(SCQ=1)` 选文件 →
>   逐段 `F_SG` → `F_LS(LSQ=1, CHS=本节算术和 mod 256)`；子站收完校验 CHS 后
>   落盘并回 `F_AF(AFQ=1 肯定 / 2 否定)`，主站据此置 COMPLETED/ERROR。
>   `data` 非法 hex / 空 / 超长、CHS 不符均有可读业务错误；**未连接引擎时参数错误
>   也精确报出**（校验先于 `require_master()`）。
> - `cot`/`qualifier` 为目录召唤组合探测用覆盖；缺省值由**文件传输语义档位**
>   （`AppConfig.file_transfer.profile`，见下）决定。
> - **从站多节分包**：`file_transfer.section_size > 0` 时把文件切成 N 节，每节
>   `F_SR → (主站 SCQ=6) → F_SG… → F_LS(LSQ=3) → F_AF(3)`，最后节 `LSQ=1`；
>   **逐节 CHS** 按本节数据计算（非整文件）。`section_size=0`（默认）= 历史单节行为。
> - **语义档位** `configs/master_config.yaml` 的 `file_transfer` 节：
>   `{profile: "ed1"|"ed2"|"project", section_size: int=0, nof_enum?: bool}`。
>   `ed1`（默认，逐字节兼容历史：目录 COT=13/SCQ=5）、
>   `ed2`（lib60870.NET + otfabric 共识：目录 COT=5/SCQ=0、NOF 枚举校验）、
>   `project`（同 ed1，明确命名）。非法档位名**加载期即报错**。
>   依据与 5 项开放项回填见 [`docs/file_transfer_open_items.md`](../docs/file_transfer_open_items.md)。

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
| POST | `/api/points/xlsx/preview` | xlsx 原始字节（T95，无副作用解析） | `{ok, stats: Record<string,number>, errors: string[], rows: {ioa,name}[] (≤100), total}`；致命问题 `{ok:false, error}` |
| POST | `/api/points/xlsx/import` | xlsx 原始字节（T95，整表替换 + 快照为设计基准） | `{ok, points, errors: string[], stats, design: true}` |
| POST | `/api/points/design` | `{action: "set"\|"clear"}`（T95：set 把当前点表快照为设计基准） | `{ok, has_design, points?}` |
| GET | `/api/points/design-diff` | — | `{ok, has_design, summary: {missing, extra, mismatch}, missing/extra: {ioa,type,name}[], mismatch: DesignMismatch[], truncated}`（T95，未建基准时 has_design=false 且清单为空） |
| GET | `/api/points/xlsx` | — | xlsx 二进制（attachment） |
| POST | `/api/scd/preview` | SCD/CID/ICD 原始 XML 文本（IEC 61850-6 SCL）；`?common_addr=` 可选显式指定公共地址（缺省取出现最多的 casdu）、`?station=` 可选覆盖站名 | `{ok, yaml, station_name, common_addr, stats: Record<string,number>, warnings: string[]}` |
| GET | `/api/export/points.csv` | — | `text/csv` 文本 |
| GET | `/api/export/report.html` | `?title=&notes=&limit=`（limit=帧证据最大行数 1~5000） | `text/html` 自包含报告（attachment；浏览器打印即 PDF） |
| POST | `/api/export/report.html` | `{title?, notes?, conclusion?, conclusion_kind?, chart_images?: [data:image/png;base64,...]}`（T87 曲线快照，最多 4 张） | `text/html` 自包含报告（同 GET，额外嵌入曲线图片） |
| GET | `/api/export/session.json` | — | `{role, status: Status, frames: WsEnvelope<'frame', Frame>[], events: WsEnvelope<'event', EngineEvent>[]}`（`recent()` 原样导出） |

> 说明：`/api/points/import` 的 `auto` 嗅探顺序为 —— 以 `{` 开头 → `json`；
> 首行含 `,` 且含 `type` → `csv`；否则 → `yaml`。

### 2.4c 对点 / 传动验收（WP2；master/slave 角色注册，bridge 角色不注册）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/commission/sessions` | `?limit=100`（1~500） | `{ok, sessions: CommissionSessionSummary[], status: {running, session_id, cursor, total}}` |
| POST | `/api/commission/sessions` | `{name?: str, operator?: str, ioas?: int[] (空=全选), expected?: Record<ioa, value>, command_ioas?: Record<ioa, command_ioa> (现场遥控与回读遥信异址时指定)}` | `{ok, session: CommissionSession}` |
| GET | `/api/commission/sessions/{id}` | — | `{ok, session: CommissionSession}`；不存在 404 |
| POST | `/api/commission/sessions/{id}/run` | `{operator?: str}` | `{ok, running, session_id, cursor, total}` |
| POST | `/api/commission/sessions/{id}/stop` | — | `{ok, running, session_id, cursor, total}` |
| POST | `/api/commission/sessions/{id}/verdict` | `{ioa: int, verdict: "pending"\|"pass"\|"fail"\|"manual", note?: str, operator?: str}` | `{ok, item: CommissionItem}` |
| DELETE | `/api/commission/sessions/{id}` | — | `{ok}`（未找到时 `ok=false`） |
| GET | `/api/commission/sessions/{id}/export` | `?format=xlsx\|json\|html`（默认 xlsx） | 对应格式二进制（attachment）；xlsx 为签字用对点表，html 自包含可打印为 PDF |

> `CommissionItem`：`{ioa, name, kind: "YX"\|"YC"\|"YK"\|"STEP", group, command_ioa?, expected, actual,
> quality, verdict, note, operator, checked_at, tx_frame, rx_frame, tx_time, rx_time,
> reason, tolerance}`；`CommissionSession` 另含 `{id, name, created_at, operator,
> status: "idle"\|"running"\|"done"\|"stopped", items, point_table_snapshot,
> started_at, finished_at, cursor, note, summary: {total, pass, fail, manual, pending, done}}`。
> 运行进度经现有 `event` kind 广播 `type: "commission.started"|"commission.item"|
> "commission.stopping"|"commission.finished"`，前端复用 `useLiveEvents()` 即可，
> 不新增 WS kind、不递增 `schemaVersion`。
> SBO 被拒 / 超时 / 命令失败一律判 `fail`；未设期望值的点判 `manual` 并跳过自动下发。
>
### 2.4d 操作审计与多用户三角色（WP4a；master/slave 角色注册，bridge 角色不注册）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/audit/records` | `?limit=200`（1~5000）、`?operator=`、`?action=`、`?result=ok\|fail`、`?since=<unix_ts>`（均可选） | `{ok, records: AuditRecord[], stats: {total, operators, fails, last_ts}}` |
| GET | `/api/audit/verify` | — | `{ok, valid, total, broken_at: int\|null, reason: str}`；任何一条被删/改都会报出首个断点 id |
| GET | `/api/audit/export` | `?format=json\|csv`（默认 json） | 对应格式（attachment `audit_log.json/csv`）；非法 format 400 |
| GET | `/api/auth/users` | —（**admin only**，其余角色 403；未启用多用户时 404） | `{ok, users: [{name, role}]}`（不含任何 token 材料） |

> `AuditRecord`：`{id, ts, operator, role, source_ip, action, target, result: "ok"\|"fail",
> reason, tx_frame, rx_frame, prev_hash, hash}`。
> **审计覆盖范围（WP4a 口径）**：经命令汇聚点（`EngineBridge._cmd`）的主/子站命令与
> WP2 传动下发（`action = "master/yk"` 等去 `/api/` 前缀路径；传动为
> `commission/yk|yc|step`，`operator` 取会话检查人、`role="system"`）；
> 帧证据取命令开始之后的 tx/rx 首帧 hex（rx 应答晚到则留空）。
> **被 401/403 拒绝的动作不入链**（验收判据：越权动作链上无痕）。
> 防篡改：`hash = SHA256(prev_hash ‖ canonical_json)`，首条 `prev_hash` 为 64 个 `0`；
> 校验见 `/api/audit/verify`。哈希防事后删改，不防「能改库者整链重算」（威胁模型边界）。
>
> **多用户三角色（`--auth-config users.yaml`，格式 `{"users": [{name, token, role}]}`）**：
> `role ∈ {viewer, operator, admin}`。权限矩阵（可判定，`role_allowed()` 为唯一真值源）：
> - **viewer**：全部 GET（读点表/审计/状态）；一切 POST/DELETE 403；
> - **operator**：GET + 操作类 POST（master 命令族、slave 模拟置数、commission
>   会话/传动、bridge 启停、测试/压测）；**点表写入族（`/api/points/*` POST）、
>   `/api/auth/users`、一切 DELETE 403**；
> - **admin**：全部放行。
> 未配置 `--auth-config`/`--auth-token` 时整体直通（兼容模式，行为与 v1.10.0 一致，
> 无身份不入审计链）；仅配单 token 时为**匿名 admin**，前端可用 `X-Operator` 头
> 补充操作人姓名；多用户模式忽略 `X-Operator`（以 token 映射为准防冒名）。
> `/api/auth` 探测纯新增字段：`mode: "none"|"token"|"users"`、命中时 `operator`/`role`
> （schemaVersion 不递增，见 §1.3 兼容约定）。
>
### 2.4e 防误操作闭锁（WP4b；作用于 §2.2/§2.3 的命令端点，纯新增可选键）

闭锁是**独立于 SBO** 的业务安全前置条件（SBO 属协议层时序，闭锁属"当前工况是否允许"）。
点表 YK / YC / STEP 点可声明 `interlock`（AND 关系，条件引用遥信期望位置）::

    yk:
      - ioa: 2001
        name: 1号机合闸
        interlock:
          - ioa: 1001        # 引用遥信
            value: false     # 须为分位
            label: 刀闸位置   # 可选

| 端点 | 新增请求键 | 行为 |
|------|-----------|------|
| `POST /api/master/yk` / `setpoint` / `step` / `bitstring` | `force?: bool`（默认 false） | 闭锁不满足且 `force=false` → **200 `{ok: false, error, interlock}`，链路上不发任何命令帧**；`force=true` 需 admin 角色，放行并写 `"<kind>/force-unlock"` 审计（`role != admin` 时 200 `{ok:false, error}` 且不发帧） |
| `GET /api/points` | 命令行（YK/YC/STEP）新增只读 `interlock: [{ioa, value, label}]` | 前端显示「联锁」标记与条件；无配置时为空数组 |

> 拒绝响应中的 `interlock` 为 `{blocked: bool, reason: str, conditions: [{ioa, value, label}],
> observed: [{ioa, value: bool|null}]}`（`observed.value=null` 表示遥信未上送）。
> **取值失败按不满足处理**（未知工况不操作，安全取向）。
> 未配置 `interlock` 的点、以及未启用认证的兼容模式，行为与历史版本**完全一致**。
> 拒绝（`interlock-blocked`）与强制解锁（`force-unlock`）均写入 §2.4d 的同一条审计链；
> `deactivate`（撤销选择）不受闭锁限制，始终可发。
>
### 2.4f 工程配置方案（WP5；master/slave 角色注册）

一个「方案」= 一次现场调试的完整工程参数集，落 `configs/profiles/<名称>.yaml`
（**纯文本 YAML，可用 git 管理，也可直接当 `--config` 使用**）。

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/profiles` | — | `{ok, profiles: ProfileInfo[], active: str}`；无方案目录时 `profiles: []`（不是错误） |
| GET | `/api/profiles/{name}` | — | `{ok, name, config: {…}, summary: ProfileSummary}`；不存在 404 |
| POST | `/api/profiles/{name}` | `{config?: object}`（省略/空 = **快照当前生效参数**） | `{ok, name, path}`；非法名 400 |
| POST | `/api/profiles/{name}/apply` | — | `{ok, name, applied: str[]}`（逐项列出还原了什么，如 `["connection","timers.t1","asdu_address","point_table"]`）；不存在 404 |
| POST | `/api/profiles/restore` | — | 应用记录中的活动方案；无活动方案时 `{ok: false, error}`（HTTP 200，非错误） |
| POST | `/api/profiles/import` | `?name=<名称>`，body 为方案 YAML 文本 | `{ok, name, path}`；YAML 非法/名非法 400 |
| GET | `/api/profiles/{name}/export` | — | `application/x-yaml`（attachment `profile_<名称>.yaml`） |
| DELETE | `/api/profiles/{name}` | — | `{ok}`；删除同时清空活动指针 |

> `ProfileInfo`：`{name, updated_at, size, summary}`；
> `ProfileSummary`：`{mode, host, port, common_addr, ca_length, ioa_length, cot_length,
> point_table, note, timers:{t0..t3?}, flow_control:{k,w?}}`。
>
> - **方案覆盖范围**：连接（host/port/公共地址/重连）、链路参数（t0~t3、k/w）、
>   ASDU 地址长度（WP1，`apply` 时同步 `set_default`）、点表文件引用、告警阈值、
>   报告默认标题。**不含** TLS/证书路径、历史库保留期、显示偏好——避免一份方案
>   悄悄改掉安全与存储配置（`--profile` 的叠加规则相同）。
> - **活动方案与刷新恢复**：`apply` 会把方案名记入 `configs/profiles/_active.yaml`
>   （该文件被 git 忽略）；前端挂载时调用 `POST /api/profiles/restore` 还原。
>   **服务端启动时刻意不自动应用方案**，保证端口/角色只由 CLI 与 `--config` 决定；
>   需要无浏览器场景时用显式 `--profile <名称>`。
> - **权限**：方案是管理动作 → `admin` 可写；`operator`/`viewer` 只读（§2.4d 矩阵）。
> - **审计**：保存/应用/删除/导入写 §2.4d 的哈希链（`profiles/save|apply|delete`）。
> - **点表引用缺失**：`apply` 时引用的点表文件不存在 → 记日志并跳过该项，
>   其余参数照常还原（响应 `applied` 里不含 `point_table`）。
>
### 2.4g 链路参数可观测（WP6；`GET /api/status` 纯新增 `link` 键）

`link` 段是**只读快照**，不新增端点、不递增 `schemaVersion`（§1.3）。**引擎未启动时也存在**
（`state`/`sequence` 为 `null`，`transport` 给出配置目标），因为"连不上"正是最需要看它的时刻。

```jsonc
"link": {
  "role": "master" | "slave",
  "state": {                       // 连接状态机（ConnectionStateMachine.snapshot）
    "state": "Stopped" | "Connecting" | "Running",
    "since_seconds": 12.4,         // 当前状态已保持时长
    "timers": {                    // t0~t3：active=false 时 remaining=0（"没在计时"）
      "t1": {"timeout": 15.0, "active": true, "elapsed": 3.2, "remaining": 11.8}
    },
    "history": [                   // 最近 20 次变迁（旧→新），墙钟秒
      {"ts": 1794450419.31, "from": "Stopped", "to": "Connecting"}
    ]
  } | null,
  "sequence": {                    // 流控（SequenceManager.snapshot）
    "k": 12, "w": 8, "send_seq": 5, "recv_seq": 3, "last_ack_rx": 2,
    "unacked": 3,                  // 已发未确认 I 帧数 —— t1 超时的直接前因
    "window_available": true, "i_frame_count": 1
  } | null,
  "transport": {                   // TCP 传输层（TCPClient.link_stats）
    "target": "10.0.0.1:2404",
    "connected": true,
    "tls": false,
    "reconnect_count": 2,          // 已重连次数
    "max_reconnects": 0,           // 0 = 无限
    "reconnect_interval": 5.0,
    "reconnect_in_seconds": 5.0,   // 当前处于重连等待时为间隔值，否则 null
    "ever_connected": true,
    "last_error": "ConnectionRefusedError: [WinError 10061] ...",  // 最近失败原因
    "last_error_at": 1794450400.5
  } | null,
  "redundancy": {...} | null,      // 仅主站且启用冗余时（与既有 status.redundancy 同形）
  "clients": 2,                    // 仅子站：当前客户端数
  "client_id": "127.0.0.1:52344"    // 仅子站：快照取自哪条连接（首条）
}
```

> **子站口径**：子站可同时接受多个客户端，`state`/`sequence`/`transport` 取**首条**连接的视图，
> `clients` 给出总数。多连接逐条定位请用桥接观察页或历史报文。
> **主站口径**：`transport` 来自 `TCPClient`；**从未建连时也能给出 `last_error`**
> （如端口无人监听），这是排障最常遇到的情形。
> 状态机时间线是**内存环形**（20 条），进程重启即清空；不落库（观测不引入持久化副作用）。
>
### 2.4h 多格式报告导出（WP8；只新增端点，既有 `/report.html` 不变）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/export/report` | `?format=html\|xlsx\|pdf`、`?title=&notes=&conclusion=&conclusion_kind=&session=<id>&audit_limit=200` | 对应格式文件（attachment）；非法 format 400 |

> 三种格式共用同一份 `Evidence`（会话信息 + 帧统计 + **WP2 逐点证据** + WP4 审计流水 +
> 告警 + 结论 + 曲线），**逐点证据条数必然一致**（测试断言）。`?session=` 缺省取最近
> 一次传动会话。xlsx 三个 sheet：摘要 / 逐点证据 / 审计流水；PDF 为横向 A4 表。
> **PDF 需可选依赖 `reportlab`**（`pip install .[pdf]`）：未安装时返回
> `400 {ok:false, error:"...pip install iec104-tester[pdf]..."}`，**不是 500**——
> onefile 包在未装 extra 时 html/xlsx 仍可用。`/api/export/report.html` 行为不变。

### 2.4i 点表在线编辑（WP10a）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/points/upsert` | `{type: "YX"\|"YC"\|"YK"\|"YM"\|"STEP", point: {ioa: int, name?, group?, enabled?, subtype?, unit?, min_value?, max_value?, decimal_places?, sbo?, ...}}` | `{ok, created, point?: {ioa,type,name,group,enabled}}`；字段非法 400 |
| DELETE | `/api/points/delete` | `?type=YK&ioa=2001` | `{ok, deleted}`；点不存在 404 |

> `ioa` 已存在时**就地改字段**（保持对象引用），不存在则新增；类型相关字段只带该类型
> 有意义的键。**关键约定：在线增改删点不重置 `design` 设计基准**——基准是导入时的
> 设计快照，现场改点后 `GET /api/points/design-diff` 应仍能报出「多/缺」差异；
> 要更新基准须显式 `POST /api/points/design {action:"set"}`。

### 2.14b 旁路真实网卡抓包（WP9）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/sniff/status` | — | `{ok, running, capability, stats, frames, port}` |
| POST | `/api/sniff/start` | `{port?: int, iface?: str}` | `{ok, capability, port}`；**能力/权限不足时 `200 {ok:false, error, capability}`**（业务错误，不是 500） |
| POST | `/api/sniff/stop` | — | `{ok, frames, stats}` |
| GET | `/api/sniff/export` | `?raw=1` 可选 | pcap（attachment）；无数据 400 |

> `capability = {available, backend, reason, requires_root}`；`stats = {packets, apdus,
> bytes, dropped, errors, last_error}`。
> **诚实降级**：`available=false` 时 `reason` 必给具体原因（如「Windows 需安装 Npcap 与
> scapy」），绝不假装抓到包。Linux 用 `AF_PACKET`（需 root/CAP_NET_RAW），
> Windows 需 Npcap + scapy。
> 抓到的 APDU 构造成既有 `FrameEntry`，**pcap 写入 / 导入 / 回放 / diff 全链路零改动复用**。
> 只保留与 `tcp port <port>`（默认 2404）相关且以 `0x68` 开头、长度自洽的完整 APDU；
> 半帧不猜、不产出。缓冲上限 20000 帧，超出丢弃最旧并计入 `dropped`。
> 此能力受现场网络镜像/权限约束，**属增强项，不属发布门禁**。

### 2.4a 透明桥（所有角色应用均注册；非 bridge 角色调用人话业务拒绝 `{ok: false, error: 仅 bridge 角色支持该操作}`）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/bridge/start` | `{listen_host?, listen_port?, upstream_host?, upstream_port?}`（缺省回填 `0.0.0.0:2404` 与 status 的 host/port） | `{ok, error?}` |
| POST | `/api/bridge/stop` | — | `{ok, error?}` |
| POST | `/api/bridge/condition` | `NetworkCondition` 字段（loss_rate/delay_ms/duplicate_rate/corrupt_rate/reorder_rate/disconnect_rate/direction/active；空 body=清空条件） | `{ok, condition, active}`（仅 bridge 角色，未运行时业务拒绝） |
| GET | `/api/bridge/timeline` | — | `{ok, running, steps: TimelineStep[], last_result: TimelineResult\|null}`（T97） |
| POST | `/api/bridge/timeline` | `{steps: TimelineStep[]}`（T97 编排，覆盖旧序列；校验失败 `{ok:false, error}`） | `{ok, steps}` |
| POST | `/api/bridge/timeline/run` | — | `{ok, running: true, steps}`（异步启动；运行中重复调用/桥未启动 → `{ok:false, error}`）（T97） |
| POST | `/api/bridge/timeline/stop` | — | `{ok, stopping}`（T97） |

> 桥角色（T74）的 `GET /api/status` 额外携带 `bridge_stats`（frames/bytes/
> clients/resyncs/upstream_errors 计数，running 时存在）与 `bridge_cfg`
> （当前桥配置）；帧观察复用 `/ws` 的 `frame` 事件与 `/api/capture/*`。
> 桥角色 status 另携带 `injection`（注入统计累计）、`condition`（当前条件描述）、`condition_active`（T85）。
> 桥应用**不注册**引擎专属路由（master/slave/multi 启停、点表写入、网络模拟）。

### 2.4b 压测编排（端点全应用注册；未挂载编排服务的应用返回 `{ok: false, error: 压测仅支持单进程双角色（both）模式}`）

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/loadtest/start` | `{duration_s?: number, events_per_s?: number}`（1~3600s / 1~10000 eps，缺省 60/100） | `{ok, error?}`（双端引擎未运行时业务拒绝） |
| POST | `/api/loadtest/stop` | — | `{ok, summary?, error?}`（summary：events_sent/rx_frames/avg_eps/avg_fps/errors） |
| GET | `/api/loadtest/status` | — | `{ok, running, elapsed_s, duration_s, target_eps, events_sent, rx_frames, i_frames, bytes_received, fps, errors, summary?}` |

> 压测（T76）编排层不改引擎：驱动既有 `slave_set_yx/yc` 自发事件路径按目标速率
> 循环触发，主站侧以 `ConnectionStats` 差分统计吞吐（验收口径：每秒 N 条遥测
> 稳定上送不断链）。**多连接（T83）**：connections>1 时压测自建 N 条主站连接
> 同时接入子站，子站每次自发事件推送给所有已连主站（总帧数 ≈ 事件数×连接数），
> status/summary 携带 per_connection 分行统计。仅 both 模式挂载（双桥同进程）。

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
>
> **WP7 纯新增 `tree` 键（结构化解码树）**：同一响应额外返回
> `tree: {ok, error?, format, apci, asdu, objects[]} | null`，供报文查看器
> 「值域」列展开子表（`segments` 契约不变，旧消费方忽略 `tree` 即可）。
>
> - `apci`：`{length, asdu_length, frame_type, tx_seq, rx_seq, u_func, u_func_name}`；
> - `asdu`：`{type_id, type_name, sq, num, cot, cot_name, pn, test, origin_addr,
>   common_addr, object_count}`；
> - `objects[]`：`{index, ioa, sq_index?, value_display, value, quality,
>   quality_bits: {iv,nt,sb,bl,ov} | null, quality_raw, timestamp, raw_hex}`。
>   **SQ=1 时已展开为 `base + i`** 并带 `sq_index`（避免界面显示成"N 个对象同地址"）；
>   `value` 收敛为 bool/int/float/str/null；`quality_raw` 保留原始字节（IV=0x80 不截位）。
>   注意：**SIQ/DIQ 的 bit0 是值本身，不含 OV**（OV 仅 QDS 有），故单点遥信的
>   `quality_bits.ov` 恒为 false。
> - `tree` 为 `null` 表示该帧无法结构化（如 APCI 截断）；`tree.error` 非空表示
>   头部已解出但信息体解析失败（此时 `objects` 为空，不编造半截对象）。

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
> 两种请求头形态：`Authorization: Bearer <token>`、`X-Auth-Token: <token>`。
> **P1-1 起 REST 端点不再接受 `?token=`**（避免令牌落入历史/代理日志/Referer）；
> 仅 `/ws` 握手（无法自定义头）与本公开探测端点（只回布尔，保留
> `/app/?token=` 首次导入）仍接受 query。静态页 `/app/*` 不拦截，供前端弹出令牌输入框。
> 带 `Origin` 头的跨源 `/api/*` 与 `/ws` 请求返回 **403**
> `{ok:false, error:"cross-origin request rejected"}`；无 Origin 的非浏览器客户端放行。
> 认证失败/越权/跨源拒绝写 `security` 类别日志（不含令牌本身）。
> 未配置令牌时本端点返回 `required=false, valid=true`，其余行为与旧版一致。

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/api/auth` | 可带令牌（上述三种形态之一） | `{ok, required: bool, valid: bool}` |

### 2.14 报文录制/回放（E2）

> T96 增补：`POST /api/capture/diff`——两段录制的规格化多重集对比。

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/capture/diff` | `{a: string, b: string, max_entries?: number (1~500，默认 200)}`（a/b 为录制文件名） | `{ok, identical, total_a, total_b, unique_a, unique_b, diff_total, entries: {signature, count_a, count_b, delta}[], truncated, file_a, file_b}`；文件不存在/加载失败 `{ok:false, error}` |

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

### 4.14 `DesignMismatch`（T95 设计 vs 实测比对）

```ts
DesignMismatch = {
  ioa: number,
  design: { type: string, min_value?: number, max_value?: number },
  actual: { type: string, min_obs?: number, max_obs?: number },
  reason: string,   // "类型不符（设计 YC → 实测 YX）" | "实测值域越界（设计 [..], 实测 [..]）"
}
```

> 清单各段最多 200 条（`truncated=true` 表示有截断，`summary` 计数为全量）。
> 「值域」取 `data_store` 的 YC **观测极值**（`min_val`/`max_val`，未观测不参与比对），
> 与设计声明的 `min_value`/`max_value` 比较；类型不符按 IOA 归并（同 IOA 类型集不一致）。

### 4.15 `TimelineStep` / `TimelineResult`（T97 桥注入时间线）

```ts
TimelineStep = {
  label: string,                      // ≤80 字符
  duration_s: number,                 // 0.5~600
  condition: Partial<NetworkCondition>, // 仅数值字段 + direction；空对象 = 干净链路
  expect: "none"|"loss"|"k-exceed"|"t1"|"disconnect",
}
TimelineResult = {
  ok: boolean,                        // 全部非跳过步骤符合预期
  steps: {
    label: string, expect?: string, ok?: boolean, skipped?: boolean,
    condition?: string,               // describe() 文本
    detail: string,                   // 判定依据（人话）
    observed?: { dropped: number, disconnects: number, clients: number,
                 violations: {ts,kind,side,detail}[] },
    window_s?: number,
  }[],
  started_at: number, duration_s: number, stopped?: boolean,
}
```

> 判定口径（防误报，`webui/timeline.py::judge` 单测锁死）：证据按步骤时间窗归集——
> 丢包/断链看 `injection_stats` 窗口增量，合规违规按 `ts > 游标` 归窗；
> `none` 要求窗口内零丢帧/零断链/零违规。运行结束自动复位干净链路。

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
