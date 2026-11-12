# 从「协议联调工作台」到「现场工程可用调试软件」优化方案（v1.11 提案）

> 状态：**11 个 WP 全部按新口径收口（WP1~WP10 已实现，WP11 于 2026-11-12 拆 11a/11b 结案）**。发布阈值已达成，可对外宣称「现场工程可用」；11b 为增强项不设门禁。
>
> **⚠ 口径变更（2026-11-12，用户明确指令）**：「找不到真机测试。服务端客户端互测+其他开源软件测试能过就行，不用纠结真机」。
> 因此 **T50 不再要求真机装置窗口**；本仓 master↔slave 真实 TCP 互测 + 多个独立开源实现
> （lib60870-C / lib60870.NET / otfabric 5 栈矩阵）交叉证据通过即为合格验收证据。
> 旧文中「必须真机回填」「第三方推断不算数」「真机背书」等表述全部按此口径作废。基线：v1.10.0 `951d5c9` 及之后至 `52691a2` 的互操作文档批次。
> 本文给出可判定的验收判据与成本模型；成本用**可核查的结构量**表达（文件数/调用点数/端点数/用例数），不编人日。
> **WP1 实施结果**：见 [asdu_address_config.md](asdu_address_config.md) 与 [PROJECT.md](../PROJECT.md) v1.11 段；默认零回归、1770 后端用例 / 91.25% 覆盖率 / 133 前端单测 / 61 e2e 全绿。
> **WP2 实施结果**：见 [PROJECT.md](../PROJECT.md) v1.11 段与 `webui/api_contract.md` §2.4c；1817 后端用例 / 91.09% 覆盖率 / 137 前端单测 / 62 e2e 全绿。
> **WP4a 实施结果**：见 [PROJECT.md](../PROJECT.md) v1.11 段与 `webui/api_contract.md` §2.4d；兼容模式零回归、1849 后端用例 / 91.05% 覆盖率 / 137 前端单测 / 63 e2e 全绿。
> **WP4b 实施结果**：见 [interlock.md](interlock.md) 与 `webui/api_contract.md` §2.4e；1880 后端用例 / 91.06% 覆盖率 / 137 前端单测 / 63 e2e 全绿。
> **WP5 实施结果**：见 [profiles.md](profiles.md) 与 `webui/api_contract.md` §2.4f；1926 后端用例 / 91.05% 覆盖率 / 137 前端单测 / 63 e2e 全绿。
> **WP6 实施结果**：见 `webui/api_contract.md` §2.4g；1947 后端用例 / 91.10% 覆盖率 / 149 前端单测 / 63 e2e 全绿。
> **WP7 实施结果**：见 `webui/api_contract.md` §2.9 的 `tree` 键；1970 后端用例 / 91.08% 覆盖率 / 154 前端单测 / 63 e2e 全绿。
> **WP8/9/10 实施结果**：见 [`deploy.md`](deploy.md) 与 `webui/api_contract.md` §2.4h/§2.4i/§2.14b；**2073 后端用例 / 91.11% 覆盖率 / 162 前端单测 / 63 e2e** 全绿。
> 配套差距分析见本仓对话记录；既有路线图见 [architecture_plan.md](architecture_plan.md)，历史快照见 [optimization_report.md](optimization_report.md)。

---

## 0. 结论先行

本仓**已经**是一个功能完整的协议联调/排障工作台（主/子站双角色、全 TypeID/COT/品质/SQ/CP24+CP56、SBO 两段式、t0~t3/k/w 可配、TLS+mTLS、透明桥+合规监视+弱网注入、SCD/Excel 点表比对、pcap 录制回放与 diff、WebSocket 推送、免安装 exe、1711 后端用例 / 91.11% 覆盖率 / 61 e2e）。

**它缺的不是「能不能收发帧」，而是现场工程的三件交付物：对点传动记录、非标装置互联、可追溯的操作证据链。**

按对「工作中可用」的阻断程度分为三档，共 **11 个工作包（WP）**：

| 档 | WP | 名称 | 一句话目标 | 外部阻塞 | 阻断发布 |
|---|---|---|---|---|---|
| P0 | WP1 ✅ 已实现 | ASDU 地址长度可配 | 1B CA / 2B IOA 装置能正确互联 | 无 | **是** |
| P0 | WP2 ✅ 已实现 | 对点/传动验收闭环 | 产出可签字归档的逐点记录 | 无 | **是** |
| P0 | WP3 ✅ 已实现 | 文件传输完工 + T50 按新口径验收 | 双向/多节文件业务闭环 | 无（互测 + 开源多实现已自证） | **是** |
| P0 | WP4 ✅ 已实现 | 操作安全与审计流水 | 每条遥控可归因、可举证 | 无 | **是** |
| P1 | WP5 ✅ 已实现 | 工程配置方案管理 | 连接/点表/阈值命名保存与恢复 | 无 | 否 |
| P1 | WP6 ✅ 已实现 | 链路参数可观测面板 | k/w/t0~t3/未确认 I 帧/重连原因可见 | 无 | 否 |
| P1 | WP7 ✅ 已实现 | 报文值域解码树 | 展开一帧看到每个信息对象的值/品质/时标 | 无 | 否 |
| P1 | WP8 ✅ 已实现 | 原生 Excel/PDF 报告 | 一键出可归档交付物 | 无 | 否 |
| P1 | WP9 ✅ 已实现 | 旁路真实网卡抓包 | 抓第三方主站↔装置原始报文 | 网卡权限 | 否 |
| P1 | WP10 ✅ 已实现 | 点表在线编辑 + 服务化/容器交付 | 现场临时改点；一条命令起服务 | 无 | 否 |
| P2 | WP11 | 标准合规收口（62351 / 冗余组 / 自动对时 / SCD 私有映射 / 真机语料） | 补边界 | **标准原文 + 厂商样本** | 否 |

**发布阈值（可判定，2026-11-12 修订）**：WP1~WP4 全部验收通过 + **WP3 按新口径（本仓真实 TCP 互测 + 多独立开源实现交叉证据）通过** → 可对外宣称「现场工程可用」。**2026-11-12 已全部达成**（见 §WP3 实施结果）。

**开工顺序**：WP1 → WP2 → WP4 → WP5~WP10 已交付；**WP3 按新口径当前收尾**（纯代码 + 互测矩阵，无外部阻塞）；WP11 仍等标准原文/厂商样本。

---

## 1. 基线与成本模型

### 1.1 可核查的基线分母

| 指标 | 数值 | 证据 |
|---|---|---|
| 后端 pytest 文件 | 116 | `find tests -name "test_*.py"` |
| 后端用例 / 覆盖率 | 1711 passed / 91.11% | `README.md:275`、`ci.yml:49` 门禁 `--cov-fail-under=91` |
| 前端单测文件 / 用例 | 32 / 133 | `webui/frontend/src/**/*.test.ts*` |
| Carbon 组件文件 | 33 | `webui/frontend/src/carbon/**/*.tsx` |
| Playwright e2e | 61 spec / 9 个手工脚本 | `README.md:275`、`tests/e2e/*.py` |
| Web API 端点（约） | 106 处路由注册 | `webui/server.py:1533-1645` |
| ASDU 解码调用点 | **9 个文件** | `grep -rln 'ASDU.decode\|APDU.decode' core webui` |
| 其中 `ca_length` 显式固定为 2 | 3 处 | `tcp_bridge.py:156`、`webui/report.py:36`、`webui/frame_diff.py:33` |
| 配置文件顶层 dataclass | 12 个 | `core/config.py:11-160` |
| 主站命令公开方法 | 30+ | `core/engine/master_commands.py:50-714` |
| docs 文档 | 22 篇 | `ls docs` |
| 最新 tag | v1.10.0 | `git tag` |

### 1.2 成本口径（为什么不用「人日」）

用户要求过「成本/收益要数字、有候选对比表、有可判定阈值」，但跨栈改造的人日估算不可核查、也无法验收。因此本文统一用 **结构量** 表达成本，评审时可直接 `grep` 复核：

- **F** = 需新增/修改的源码文件数（不含测试与文档）
- **C** = 需改动/新增的调用点或端点数
- **T** = 需新增的测试（后端 + 前端 + e2e）下限
- **R** = 回归风险面（受影响的既有能力，用「层级」计：协议核心 / 引擎 / Web / UI / 打包）
- **B** = 外部阻塞（0=无，1=需真机/标准/厂商样本）

收益同样量化：**G** = 解锁的现场动作数、**A** = 关闭的开放项数（对应 `docs/*open_items*` / `PROJECT.md` TODO）。

> 成本数字是**改动面**不是工期；工期由评审按团队速率换算。这样避免了「不建议改 / 建议改」的立场式结论，换成可判定的 `B=0 且 F≤N` 决策规则。

### 1.3 决策阈值

| 规则 | 判定 |
|---|---|
| `B=0` 且 `R≤3` 且 `F≤8` | **立即排入下一迭代**（如 WP1/WP6） |
| `B=0` 且 `F>8` | 拆子任务分批，但不得跨版本悬置（如 WP2/WP4） |
| `B=1` | 立外部条件工单并并行做可自测部分，**不设为发布门禁前置**（如 WP3/WP11） |
| 任一 WP 使 `--cov-fail-under=91` 或 e2e 61 退化 | **合并阻断**，先补测试 |

---

## 2. P0 详细设计

### WP1 — ASDU 地址长度可配

**问题**（已 grep 实证）：`core/protocol/asdu.py:601` 写死 `ioa_size = 3`；`:501-502` 编码硬编码 2 字节 CA；`config.py` 无任何长度字段；`ASDU.decode(ca_length=...)` 参数存在但 9 个调用点中 3 个显式传 2、其余走默认 2。现场 1 字节 CA / 2 字节 IOA 装置会导致**整帧信息体错位且无报错**。

**候选方案对比**

| 候选 | 做法 | F | C | R | 兼容性 | 结论 |
|---|---|---|---|---|---|---|
| A. 每调用点传参 | 给 9 个文件逐个加 `ca_length/ioa_length` | 9 | 9 | 协议核心+引擎+Web（3 层） | 差：离线解析/桥/pcap 各自可能不一致 | 否决 |
| **B. 配置对象 + 编解码器持有（推荐）** | 新增 `AsduAddressConfig`，引擎/会话构造时注入，所有调用点从同一上下文取 | **5** | **9** | 协议核心+引擎+Web（3 层） | 好：单一真值源，默认 2/3/2 完全向后兼容 | **采纳** |
| C. 全局单例 | 模块级全局变量 | 2 | 9 | 1 层 | 差：多站/桥两侧参数不同时串味，并发不安全 | 否决 |

**实施步骤**

1. `core/config.py` 新增 `AsduAddressConfig(ca_length=2, ioa_length=3, cot_length=2)`，挂到 `AppConfig`；`save`/`load_config` 补 3 个键（沿用现有「未知键忽略」兼容策略）。
2. `core/protocol/asdu.py`：
   - `ASDU` 增加类级/实例级地址上下文；`encode()` 按 `ca_length` 写 CA、按 `ioa_length` 写每个 IOA（`:501-512`）；
   - `decode()` / `decode_header()` 的 `ca_length`、`ioa_size` 改为从上下文取，保留显式参数作为 **override**（离线解析工具需要按帧指定）；
   - `APDU.decode()` 透传（`:1950`）。
3. **9 个调用点统一**（这是必须逐一点名的验收清单）：`master_protocol.py:237/242`、`slave_session.py:195`、`slave_response.py:248`、`compliance_monitor.py:220/278`、`tcp_bridge.py:156`、`webui/frame_diff.py:33`、`webui/frame_translate.py:159/162`、`webui/report.py:36`、`core/protocol/asdu.py` 内部。
4. 桥两侧、多站 `StationConfig` 允许各自独立配置（与 `multi_station.py:32` 已有「每站独立 common_addr」一致）。
5. UI：连接面板新增 3 个下拉（默认 2/3/2），写入 `AppConfig`；`--config` YAML 可覆盖。

**测试下限 T**：单测覆盖 `ca_length∈{1,2} × ioa_length∈{1,2,3} × {SQ=0,SQ=1} × {编码,解码,往返}`，每个组合至少 1 个黄金向量；新增 ≥12 个向量入 `tests/fixtures/frames/`；e2e 用 1B CA 帧走通「连接→GI→点表回显」。`R` 含协议核心，必须保证默认配置下 **1711 用例全绿且既有黄金帧逐字节不变**。

**验收判据（全部满足才算完成）**
- 用 1B CA / 2B IOA 的真实第三方帧解码，IOA、值、品质、时标全部正确；
- 默认配置下所有既有 pcap/黄金向量哈希不变；
- 桥两侧用不同地址长度同时工作不串味；
- `--cov-fail-under=91` 不退化。

**成本/收益**：`F=5, C=9, T≥20, R=3, B=0` → `G=1`（解锁非标装置互联），关闭开放项 1 项（结构性缺口）。按 §1.3 属「立即排入」。

---

### WP2 — 对点 / 传动验收闭环（最致命）✅ 已实现（2026-11-11，WP2a+WP2b 同版本闭环）

**问题**（已 grep 实证）：前端 `对点|传动|核对通过|核对失败|逐点|sign-off` 零命中；`uiStore.ts` 无核对字段；结论只有全局三选一（`CarbonStatusPage.tsx:27-33`）；`design-diff` 是点表清单级比对，不是逐点实测值/传动结果核对。现场每天要产出、要签字归档的东西**完全没有**。

**候选方案对比**

| 候选 | 做法 | F | C | 现场可用性 | 结论 |
|---|---|---|---|---|---|
| A. 只加前端标记 | 在现有页加「通过/失败」勾选，导出 CSV | 3 | 2 | 差：无批量下发、无自动判定、无证据链 | 否决 |
| B. 复用 YAML 测试脚本 | 让用户写脚本表达对点 | 1 | 0 | 差：现场工程师不写 YAML，且脚本级不是点位级 | 否决 |
| **C. 独立「对点/传动」工作台（推荐）** | 新页面 + 后端编排服务 + 逐点证据记录 + 导出器 | **9** | **8 端点** | 好：导入点表→勾选→批量顺序传动→自动比对→导出带时间戳/操作人的记录 | **采纳** |

**数据模型**（新增 `core/data/commissioning.py`）

```
CommissioningSession: id, name, created_at, operator, point_table_snapshot, status
CommissioningItem:    session_id, ioa, name, point_type,
                      expected_value, actual_value, expected_quality,
                      verdict(pending/pass/fail/manual), note,
                      operator, checked_at,
                      tx_frame_hex, rx_frame_hex, tx_time, rx_time   # 证据链
```

**后端编排**（新增 `webui/commissioning.py` + 8 端点）

| 端点 | 作用 |
|---|---|
| `POST /api/commission/sessions` | 从当前点表创建会话（快照，避免运行中改表导致记录错乱） |
| `GET /api/commission/sessions` | 会话列表 |
| `GET /api/commission/sessions/{id}` | 明细（逐点状态） |
| `POST /api/commission/sessions/{id}/run` | **按勾选点顺序批量下发**（复用 `master_commands.py` 30+ 个已有方法；YK 走 SBO 两段式，YC 用读命令/等待自发上送） |
| `POST /api/commission/sessions/{id}/items/{ioa}/verdict` | 人工复核/改判（含备注、操作人） |
| `POST /api/commission/sessions/{id}/stop` | 中止（**必须**能安全停止且不遗留已选择未执行的 SBO） |
| `GET /api/commission/sessions/{id}/export?format=xlsx\|json\|html` | 导出对点表/传动记录 |
| `DELETE /api/commission/sessions/{id}` | 删除 |

**自动判定规则**（可判定，不靠人眼）
- YX：下发/置数后在超时窗内收到匹配 IOA 的变位帧，值 == 期望 → `pass`；超时/值不符 → `fail`；品质位 IV/NT 置位 → `fail` 并记原因。
- YC：读命令回读值落在 `期望值 ± 容差`（容差取点表量程比例，默认 0.5%）→ `pass`。
- YK：必须有 ACTCON + 后续变位确认；**SBO 被拒/超时一律 `fail`，绝不计入通过**。
- 每条记录强制留存 `tx_frame_hex/rx_frame_hex/tx_time/rx_time`，这是「可举证」的核心。

**前端**（新增 1 页 + 3 组件，挂到主站工作台菜单）
- `CarbonCommissionPage.tsx`：点表勾选、期望值录入、执行/停止/进度、逐点红绿判定、备注、导出按钮；
- 复用 `CarbonPointsTable`（10 万行虚拟滚动）与 `useWsBridge`（实时帧/点值）；
- 与 WP4 共用「当前操作人」上下文，与 WP8 共用导出器。

**并发与安全约束（必须写进设计）**
- 同一时刻只允许 1 个活动传动会话（避免与手动命令/周期总召抢序列）；执行期间暂停 `scheduler.py` 的周期 GI/对时；
- 会话状态落 SQLite（复用 `core/data/history.py` 的连接管理，不新建库）；
- `stop` 时按 `master_commands.py:244-257`（单命令）/`:290-298`（双命令）/`:330+`（设点族）的 DEACT 逻辑清理所有已选择未执行的 SBO。

**测试下限 T**：编排状态机单测（空点表/单点/多点/中途停止/SBO 拒绝/超时/重复执行）、8 端点契约测试、前端组件测试、1 条 Playwright e2e（创建→运行→判定→导出）。

**验收判据**
- 导入 100 点表 → 勾选 20 点 → 一键批量传动 → 20 条记录各自带下发帧/回读帧/时间/结论；
- SBO 被拒的点**不可能**被标成通过；
- 导出 xlsx 含逐点证据，可直接打印签字；
- 中断/刷新后会话可恢复（依赖 WP5 的配置持久化思路，但会话本身自带持久化）。

**成本/收益**：`F=9, C=8, T≥30, R=3, B=0` → `G=4`（批量传动、逐点判定、证据留存、签字交付物），这是**决定产品是不是「调试软件」的一项**。按 §1.3 属「B=0 且 F>8 → 拆子任务分批，不得跨版本悬置」：建议拆为 `WP2a 后端编排+导出`（v1.11）与 `WP2b 前端页面`（v1.11），同版本内闭环。

> **实施结果（2026-11-11）**：`core/data/commissioning.py`（判定规则/会话模型）+ `core/data/commission_store.py`（独立 SQLite `commissioning.db`，WAL+RLock）+ `webui/commissioning.py`（编排：SBO 两段式、DEACT 清理、暂停周期 GI、超时/品质/拒绝一律 FAIL 不可能假通过）+ `webui/commission_export.py`（xlsx/json/html 三格式，HTML 全转义）；8 端点注册于 master/slave 角色（bridge 不注册，契约 `webui/api_contract.md` §2.4c 双向自检）；前端 `useCommission` 共享逻辑 + Carbon/PF 双页面 + 菜单「对点传动」（bridge 角色隐藏）。验收判据逐条满足：逐点记录带下发/回读帧 hex 与时间、SBO NACK 判 FAIL、xlsx 逐点证据可打印、会话落库刷新可恢复；无期望值判 MANUAL 待人工，不出假 PASS。

---

### WP3 — 文件传输完工 + T50 按新口径验收 ✅ 已实现（2026-11-12 结案）

**问题**（已 grep 实证）：`core/protocol/file_transfer.py:249` 自述「未实现真正的多节累积与逐节校验」、`:456-457` 去激活是 `no-op (flow not implemented)`；从站多节分包未实现；主站**无文件上传 API**；官方唯一待办 T50（`PROJECT.md:219-221`）5 项真机语义未复测；[file_transfer_fls.md:16](file_transfer_fls.md) 承认标准正文未取得。

**按新口径：全部自测可判定（互测 + 开源多实现交叉证据）**

| 子项 | 外部依赖 | 可自测部分 |
|---|---|---|
| 多节累积 + 逐节 CHS 校验 | 无 | 构造 F_SG 序列、节边界、校验和失败路径，纯协议单测 |
| WITH_DEACT 后续动作 | 多实现交叉证据 | 可插拔 hook + 默认 no-op；按 lib60870-C/.NET/otfabric 观察值回填 |
| 从站多节分包 | 无 | 按节切分发送，用现有 lib60870.NET 双节 600+425 语料做回归 |
| 文件上传方向 F_SC(上传)/F_FR/F_SR | 开源对端配合 | 补主站上传 API 框架与状态机，用 otfabric/lib60870.NET 对端端到端验证 |
| CHS 算法 / FRQ-SRQ 显示 / 否定 FileError | 多实现交叉证据 | 做成显式语义档位（ed1/ed2/项目约定），默认值按交叉证据确定 |

**实施步骤**
1. `core/protocol/file_transfer.py`：把「单节」假设改为节列表；补 `sections` 累积、逐节 CHS 校验、F_LS 结束条件；去激活改为可插拔 `on_deactivate` hook（默认仅记录，行为不变）。
2. `core/engine/slave_response.py` / 新增从站文件服务：支持按节分包发送。
3. `core/engine/master_commands.py` 补上传族 API（目录/选择/文件/节/段/确认的反向），`webui/server.py` 补对应端点。
4. `configs/` 增加文件传输「语义档位」（ed1/ed2/项目约定），把 NOF/SCQ/FRQ-SRQ 的歧义做成**显式配置**而非硬编码猜测。
5. **T50 回填（新口径）**：5 项（NOF / SCQ / WITH_DEACT / 多节 / FRQ-SRQ）按本仓互测 + lib60870-C/.NET/otfabric 多实现交叉证据逐项回填 [file_transfer_open_items.md](file_transfer_open_items.md)；不再要求真机装置。

**验收判据**
- 自测部分：多节文件（≥3 节）双向传输，逐节 CHS 校验失败可复现且被拒；
- 既有 otfabric 25 配对 3071 passed 不退化；本仓 consumer 5/5 通过保留；
- T50：**5 项全部有多实现交叉证据 + 本仓互测回填**即算关闭（2026-11-12 新口径）；
- 上传方向至少 1 个独立开源对端（lib60870.NET / otfabric 栈）端到端通过。

**成本/收益（2026-11-12 修订）**：`F=5, C=6, T≥20, R=2, B=0` → `G=2`（文件上传/下载业务闭环、多实现互操作背书）。口径反转后 **B 从 1 降为 0**：互测矩阵与 5 个开源栈都在本机/WSL2 可复现，不再有外部阻塞，故 WP3 应主动收尾而不是挂起。此项是 §0 发布阈值的一部分。

> **WP3 实施结果（2026-11-12 结案）**：
> - **语义档位（WP3a）** `core/protocol/file_semantics.py` + `AppConfig.file_transfer`（`ed1`/`ed2`/`project`，目录 COT/SCQ、NOF 枚举、否定标志、从站分包大小全部显式化）；非法档位加载期报错，默认 ed1 与历史 golden 帧逐字节一致。
> - **从站多节分包（WP3b）** `FileTransferSlave._split_sections()`：≥3 节逐节 `F_SR→SCQ=6→F_SG→F_LS(LSQ=3)→F_AF(3)`，最后节 LSQ=1，**逐节 CHS**；真实 TCP 768B/3 节×256B 闭环逐字节还原。
> - **主站上传方向（WP3c）** `FileTransferMaster.start_upload()` + `POST /api/master/file {action:"upload", data:hex}`：主站发段/F_LS，子站校验 CHS 落盘回 F_AF；真实 TCP 560B 上传 + 肯定确认 + COMPLETED；CHS 篡改回否定且不落盘。
> - **5 项开放项按新口径结案**：`docs/file_transfer_open_items.md` 结论回填表以 lib60870-C / lib60870.NET / otfabric 5 栈 + 本仓互测交叉证据逐项判定，不再挂「真机待复测」。
> - 门禁：**2093 passed / 覆盖率 91.26%**、前端 162 单测、i18n 0、Playwright 63 e2e、ruff 全绿；契约 §2.2 `/api/master/file` 扩展 + `configs/master_config.yaml` 加 `file_transfer` 节。

---

### WP4 — 操作安全与审计流水 ✅ 已实现（WP4a 2026-11-12 / WP4b 2026-11-12）

**问题**（已 grep 实证）：`interlock|闭锁|联锁|操作票|operator|user_id|操作人` 在 `core/`+`webui/` 零命中（命中项均为品质位 BL 或断言参数）；认证仅单静态 token（`webui/server.py:167-185`）；日志是 `logger.info` 级运行日志，无操作人、无防篡改；会话只有导出无恢复。

**设计（三层，逐层可独立验收）**

1. **身份层**（改造 `webui/server.py:167-185` 的 `token_auth`）
   - 保留现有单 token 作为「兼容模式」；新增 `Operator`（id / name / role / token_hash）与 `--auth-config` YAML；
   - `role ∈ {viewer, operator, admin}`：viewer 只读，operator 可发命令，admin 可改配置/管理用户；
   - 前端 `CarbonAuthGate` 扩展为登录（沿用现有 localStorage 令牌机制），请求头带 `X-Operator`，后端写入请求上下文。
2. **闭锁层**（新增 `core/engine/interlock.py`）
   - 独立于 SBO 的**防误操作条件**：点表新增 `interlock` 字段（如「仅当某 YX 为分位才允许合闸」）；下发前求值，不满足则拒绝**且不发任何帧**，记录拒绝原因；
   - 提供「强制解锁」需 admin + 二次确认 + 强制写审计；
   - 保持 `master_commands.py:155-190` 已注明的主/子站 SBO 边界差异语义不变（勿当缺陷改）。
3. **审计层**（新增 `core/data/audit.py`，SQLite 表 + 哈希链）
   - 每条记录：时间戳、操作人、角色、来源 IP、动作、目标 IOA、下发帧 hex、应答帧 hex、结果、前置闭锁状态；
   - 每条 `hash = SHA256(prev_hash || canonical_record)`，形成**防篡改链**；提供 `GET /api/audit/verify` 校验链完整性；
   - 独立留存周期（不与运行日志混用），`GET /api/audit/export` 导出 JSON/CSV；
   - WP2 的每条传动记录自动写入审计（复用同一条链，不另建体系）。

**候选对比**

| 候选 | F | 防篡改 | 归因到人 | 结论 |
|---|---|---|---|---|
| A. 只加日志字段 | 2 | 无 | 无 | 否决 |
| B. 外部 SIEM 转发 | 3 | 依赖外部 | 部分 | 否决（现场离线环境不适用） |
| **C. 本地哈希链 + 角色 + 闭锁（推荐）** | **7** | **有** | **有** | **采纳** |

**测试下限 T**：三角色权限矩阵（每端点 × 3 角色）、闭锁命中/未命中/强制解锁、哈希链篡改检测、审计导出与 WP2 联动。

**验收判据**
- 用 viewer 账号调 `/api/master/yk` 返回 403，且链上无该动作；
- 删除/修改审计表中任一条 → `/api/audit/verify` 报出断点位置；
- 闭锁不满足时**抓包确认链路上没有任何命令帧**；
- 现有 1711 用例在「兼容模式（无 auth-config）」下行为完全不变。

**成本/收益**：`F=7, C≈12 端点改造, T≥25, R=3, B=0` → `G=3`（可归因、防误操作、可举证），关闭开放项 1 项。按 §1.3 拆为 `WP4a 身份+审计` / `WP4b 闭锁` 同版本闭环。

> **WP4a 实施结果（2026-11-12）**：`core/data/audit.py`（SHA-256 哈希链：`hash=SHA256(prev_hash‖canonical_json)`，`verify()` 报首个断点 id 与原因）+ `webui/audit.py`（`OperatorRegistry` 多用户三角色 + `role_allowed()` 权限矩阵唯一真值源 + ContextVar 身份/动作意图）+ `bridge._cmd()` 命令汇聚点落链（帧证据取命令窗口内 tx/rx 首帧，无身份上下文不记）+ `--auth-config users.yaml`（token 只存 SHA-256，常数时间比较）+ WP2 编排联动（`commission/yk|yc|step` 复用同一条链）。**兼容模式（无 auth-token/auth-config）行为与 v1.10.0 完全一致**；viewer 越权 403 且链上无痕（验收判据实测）；篡改/删链 `verify` 报断点。前端「操作审计」页（Carbon/PF）+ `X-Operator` 头。

> **WP4b 实施结果（2026-11-12）**：`core/engine/interlock.py`（条件解析/求值：多条件 AND、取值失败按不满足、非法配置加载即报错）+ 点表 `interlock` 字段（YK/YC/STEP 点声明，YAML 往返，非空才写，旧点表零影响）+ `bridge._interlock_gate()`（**下发前求值，不满足则一个帧都不发**；DEACT 撤销帧例外，安全清理必须可发；拒绝与强制解锁均写 §2.4d 同一审计链）+ `POST /api/master/{yk,setpoint,step,bitstring}` 新增可选 `force`（需 admin，二次确认，写 `force-unlock` 审计）+ 前端：点表「联锁」标记（内联，不新增列以免压窄表格）+ 命令弹窗闭锁条件与强制解锁复选框。文档 [`interlock.md`](interlock.md)。验收判据实测：闭锁不满足时发送列表为空（零帧）、非 admin force 拒绝且零帧、点表 YAML 往返保真。

---

## 3. P1 详细设计

### WP5 — 工程配置方案管理 ✅ 已实现（2026-11-12）

**问题**：`CarbonMasterPage.tsx:29-31` 的 host/port/addr 是 `useState`，刷新即回 `127.0.0.1:2404`；`uiStore.ts` 只持久化语言/主题/套件/令牌；`/api/export/session.json` 是帧事件导出，不是配置；多站草稿也是内存态。

**方案**：后端 `GET/POST /api/profiles`（命名方案，内容为 `AppConfig` 子集 + 点表引用 + 告警阈值 + 报告模板），落 `configs/profiles/*.yaml`（复用 `core/config.py:241-330` 的 `load_config` 兼容策略）；前端头部加「方案」下拉 + 保存/另存/导入/导出；`onMount` 自动恢复上次方案。与 WP1 的地址长度配置共用同一份 YAML。

`F=4, C=4, T≥10, R=2, B=0`；验收：设 3 套方案切换，刷新后参数/阈值/点表全部还原；旧版 `--config` 单文件仍可直接启动。

> **实施结果（2026-11-12）**：`core/data/profiles.py`（方案 YAML 存取：名称校验防路径穿越、坏文件不影响列表、活动指针 `_active.yaml` 且被 git 忽略）+ `webui/profiles.py`（`capture` 快照当前生效参数 / `apply` 写回运行态含 WP1 的 `set_default` 与点表导入 / `restore_active`）+ 8 端点（契约 §2.4f）+ 审计落链（`profiles/save|apply|delete`）+ `core/config.py::apply_profile` 与 CLI `--profile`（无浏览器场景的方案加载，显式开关）。
> **关键取舍**：**服务端启动不自动应用方案**——端口/角色只由 CLI 与 `--config` 决定，保证 CI/e2e 与旧工作流确定性；"刷新后还原"由前端 onMount 调 `/api/profiles/restore` 完成。方案**不覆盖** TLS/证书路径、历史库保留期与显示偏好（避免一份方案悄悄改掉安全与存储配置）；方案文件本身即合法 `AppConfig` YAML，`--config` 与方案目录双向通用。
> 随仓示例方案 `configs/profiles/示例-标准2_3_2.yaml`；前端「工程配置方案」卡片挂在状态总览页（不占菜单、不动页头，视觉基线仅 `status-light.png` 变化）。

---

### WP6 — 链路参数可观测面板 ✅ 已实现（2026-11-12）

**问题**：状态页只有 VS/VR/window、tx/rx/dropped（`CarbonStatusPage.tsx:19-25,108-113`），k/w/t0~t3、未确认 I 帧数、重连次数与原因、链路状态时间线均无 UI。

**方案**：`core/protocol/state_machine.py` 与 `sequence.py` 暴露只读快照（当前 t1 剩余、未确认 I 帧数、重连计数/原因、最后一次 STARTDT/STOPDT 时刻）；`/api/status` 扩展字段（**向后兼容：只增不改**）；新增 `CarbonLinkStatsCard`（数值卡 + 状态时间线），复用现有 WS 快照推送。

`F=3, C=2, T≥8, R=2, B=0`；验收：制造 t1 超时，面板能显示「未确认 I 帧数 / t1 剩余 / 重连原因」三项并随时间线更新。按 §1.3 属「立即排入」。

> **实施结果（2026-11-12）**：三处协议层各加只读 `snapshot()`——`ConnectionStateMachine`（状态/已保持时长/四定时器剩余/**最近 20 次状态变迁时间线**）、`SequenceManager`（k/w/VS/VR/**unacked**/窗口可用）、`TCPClient.link_stats()`（目标/连接态/重连计数与间隔/**最近失败原因与时刻**，**从未建连时也有记录**）；引擎侧 `MasterEngine/SlaveEngine.link_snapshot()` 聚合成一段（子站取首条连接并附 `clients`）；`/api/status` 只增 `link` 键，**引擎未启动时也存在**（state/sequence 为 null、transport 给出配置目标）——"连不上"正是最需要它的时刻。前端 `CarbonLinkStatsCard`/`PfLinkStatsCard`：指标卡（**未确认 I 帧与 t1 剩余并排**，t1 超时的两个前因同屏）、t0~t3 表、状态时间线、transport 摘要。验收判据用**真 TCP 静默对端**复现（`test_real_t1_timeout_snapshot_shows_three_fields`）：总召唤发出后 `unacked≥1`、`t1.active=true` 且剩余递减、超时后 `reconnect_count≥1`。

---

### WP7 — 报文值域解码树 ✅ 已实现（2026-11-12）

**问题**：[design_guidelines.md:456](design_guidelines.md) 明确「报文查看器无信息对象值/品质列，⏸ 单独排期」；现在只有摘要列 + 悬停 HEX 分段翻译（`CarbonFrameViewer.tsx:16-111`）。

**方案**：后端 `/api/frames/decode` 从「分段翻译」升级为**结构化树**（`{apci, asdu_header, objects:[{ioa, value, quality{IV,NT,SB,BL,OV}, timestamp, raw_hex}]}`，SQ=1 时展开地址 base+i）；前端表格行可展开子表。依赖 WP1 的地址长度配置才能对非标帧正确解析，**故排在 WP1 之后**。

`F=3, C=2, T≥12, R=2, B=0`；验收：SQ=1 的 20 对象帧展开后 20 行值/品质/时标齐全，与 golden 向量逐字段一致。

> **实施结果（2026-11-12）**：`webui/frame_translate.py` 新增 `decode_tree()`——`{apci, asdu, objects[]}` 结构化树，**SQ=1 显式展开为 `base+i`** 并标 `sq_index`，每对象含 `value/value_display/quality/quality_bits{iv,nt,sb,bl,ov}/quality_raw/timestamp/raw_hex`；`/api/frames/decode` 在既有 `segments` 之外**纯新增 `tree` 键**（旧契约不变，§2.9）。前端两个报文查看器各加「对象」列，点击就地展开子表（不弹窗——现场要边看报文流边对照多个对象）；子表显示 IOA/值/品质位/时标/原始字节，品质异常标色。**只对含信息对象的 I 帧出子表**，S/U 帧给「无信息体」说明而不是空表。验收判据实测：`test_sq1_twenty_objects_expanded` 断言 20 行地址 `base+i`、值逐条相等、第 4 条 IV、第 8 条 NT+BL。附带确认标准细节：**SIQ/DIQ 的 bit0 是值本身不含 OV**（OV 仅 QDS 有），单点遥信的 `quality_bits.ov` 恒 false——测试按标准写，不迁就实现。

---

### WP8 — 原生 Excel / PDF 报告 ✅ 已实现（2026-11-12）

**问题**：`core/testing/report.py:23-30` 仅 text/json/html/junit；`webui/report.py:307` 靠浏览器「打印 → 另存为 PDF」；无逐点证据归档。

**方案**：新增 `core/export/` 包，`Exporter` 接口 → `XlsxExporter`（openpyxl，本仓已用于 `/api/points/xlsx`）/ `PdfExporter`（ReportLab 或 WeasyPrint）/ `HtmlExporter`（保留现有自包含 HTML，浏览器打印仍可用）；统一 `Evidence` 模型聚合：会话信息 + 帧统计 + **WP2 逐点证据** + WP4 审计摘要 + 曲线快照。端点 `GET /api/export/report?format=html|xlsx|pdf`。**PDF 用可选依赖**（`report[pdf]` extra），避免打断现有 onefile 打包体积与 CI。

`F=5, C=3, T≥10, R=2, B=0`；验收：同一会话导出三种格式，逐点证据条数一致；onefile 打包在**未装 PDF extra** 时仍可启动（HTML/xlsx 可用）。

> **实施结果（2026-11-12）**：`core/export/` 包（`Evidence` 统一数据模型 + `xlsx`（openpyxl，3 sheet）/`pdf`（reportlab **可选依赖 `report[pdf]`**）/`html`（复用既有自包含渲染 + 逐点/审计段）三导出器）；`GET /api/export/report?format=html|xlsx|pdf`（§2.4h）自动并入最近一次 WP2 传动会话的逐点证据与 WP4 审计流水。前端状态页加「导出 Excel/PDF」按钮。**实测**：三种格式逐点条数一致（测试断言），PDF 真实生成 `%PDF-1.4`（装 extra 后 5200+ 字节），未装 extra 时端点返回 400 + 安装提示（非 500）。

---

### WP9 — 旁路真实网卡抓包 ✅ 已实现（2026-11-12）

**问题**：`core/capture/format.py:481` 自述 pcap 是「合成头非真实网络信息」（`:243-247` 同理）；录制只挂接引擎收发回调（`core/engine/master.py:259-267` 的 `set_raw_frame_callback`，`:175` 持有句柄），无 libpcap/scapy/raw socket，抓不到第三方主站↔装置的原始报文。

**方案**：新增 `core/capture/sniffer.py`，Windows 用 Npcap（可选依赖）、Linux 用 AF_PACKET；输出直接复用 `format.py:469-500` 的 pcap/pcapng 写入与 `load_pcap`（`:515-612`），因此导入/回放/diff 全链路**零改动复用**；BPF 过滤 `tcp port 2404`；权限不足时降级为「仅引擎录制」并明确提示。

`F=2, C=2, T≥8, R=1, B=1(网卡权限)`；验收：旁路抓一段真实主站↔装置流量，导入后帧数量与非标地址长度（WP1）解析结果一致。注意此能力**受现场网络镜像/权限约束**，属增强项不属发布门禁。

> **实施结果（2026-11-12）**：`core/capture/sniffer.py`——Linux `AF_PACKET`（标准库，需 root/CAP_NET_RAW）/ Windows Npcap+scapy（可选）；构造以太网+IPv4+TCP 帧提取完整 104 APDU（VLAN 支持、半帧不猜）；输出复用 `format.save_pcap`/`load_pcap`，**回放/diff 零改动**。4 端点（§2.14b）+ 抓包页旁路卡片。**诚实降级实测**：本机无 Npcap → `start` 返回 `ok=false` + 具体原因，不假装抓到包。构造帧验证解析链路（24+ 例），本机无权限无法做真网卡端到端——保持「B=1」标注。

---

### WP10 — 点表在线编辑 + 服务化/容器交付 ✅ 已实现（2026-11-12）

**10a 点表在线编辑**：`CarbonPointsTable` 现在是纯展示（`src/carbon/components/CarbonPointsTable.tsx:23-31`）；加行内编辑（IOA/名称/组/量程/启用/SBO）、`POST /api/points/upsert|delete`，改后**不重置设计基准**（`design-diff` 基准独立存）。`F=3, C=3, T≥10`。

**10b 部署形态**：全仓无 Dockerfile / compose / `*.service` / nssm / winsw；CLI 工具不进 exe（[user_guide.md:122](user_guide.md)）。交付 `Dockerfile`（多阶段构建前端+后端）、`docker-compose.yml`、`deploy/iec104-tester.service`（systemd）、`deploy/install-service.ps1`（Windows 服务，NSSM 或 `sc.exe` + `--no-gui`）；离线部署文档（无 CDN、无外网依赖）；把 `capture_tool.py` 等 CLI 纳入 exe 随包。**注意**：[architecture_plan.md:501](architecture_plan.md) 已把「多用户/远程协作」列为非目标、`SECURITY.md:34` 明确「不应作为生产 SCADA 网关」——服务化仅解决「无人值守长期跑」，**不改变该安全边界**，文档须同步写明。

`F=6, C=0, T≥6, R=1, B=0`；验收：一条命令起容器并访问 UI；Windows 服务开机自启且 `--no-gui` 日志可查；离线机器（断网）exe 全功能可用。

---

## 4. P2 详细设计（WP11 标准合规收口，2026-11-12 按新口径拆包）

> **⚠ 口径变更（2026-11-12，用户明确指令「按同一口径处理」）**：WP11 与 WP3/T50
> 一样，验收证据 = **本仓真实 TCP 互测 + 多独立开源实现交叉证据**（lib60870-C /
> lib60870.NET / otfabric 5 栈矩阵，含 TLS(62351-3)、62351-5 向量）。
> **不再要求 IEC 标准原文、厂商 SCD 样本、检测机构清单、现场抓包**；
> 旧文「全部 B=1 / 只立工单」作废。
> **保留诚实边界**：`docs/tls.md` 的「不宣称支持 IEC 62351 应用层认证（-4/-6）」
> 继续有效——本仓只做 TLS 传输层 + WP4 审计，这是标准事实而非证据不足。

**WP11 不是一个整体 B=1**：下表 9 个子项里 5 项外部条件本就写「无」。按可判定性拆为：

| 包 | 子项 | 外部条件 | 处理 |
|---|---|---|---|
| **WP11a（B=0，立即做）** | 文档口径漂移统一 + 版本守卫加用例数断言 | 无 | ① 先做（对外口径硬伤） |
| | `auto_clock_sync` 死配置收口、合规阈值 300s / 时标格式配置化 | 无 | ② |
| | tests/README 7 个单模块覆盖率缺口 | 无 | ③ |
| | 62351 最小合规说明（TLS + WP4 审计边界，不宣称合规）+ 冗余切换可观测接入 WP6 | 无（矩阵已覆盖 TLS） | ④ |
| | design_guidelines 保留项（告警抑制/趋势预设/字号/手动置数） | 无 | 按现场反馈择期，不设门禁 |
| **WP11b（增强项，不阻塞）** | SCD 厂商私有映射（≥2 份样本）、型式试验级用例清单、真机语料库 | 按新口径以**已有开源语料**（otfabric cases.tsv / lib60870 golden 帧）结案或立增强工单 | ⑤，不设门禁 |

| 子项 | 现状证据 | 收口动作 | 外部条件 |
|---|---|---|---|
| IEC 62351 应用层认证 / SA / RBAC / CRL / 密钥轮换 / 重放防护 | [tls.md:12-22](tls.md) 6 项全 ❌ | 按新口径：以 otfabric 62351-3/-5 交叉向量覆盖传输层，出「TLS + WP4 审计」最小合规说明，**明确不宣称应用层合规** | 无（不宣称合规即可判定） |
| IEC 60870-5-10 冗余组语义 / 双通道热备 / 备用通道健康探测 / 切换期在途命令重发 / 切换 UI 可观测 | [redundancy.md:96-108](redundancy.md) | 逐项补；至少把「切换可观测性」接入 WP6 面板 | 标准原文 |
| 建链后自动时钟同步（死配置） | `core/config.py:39-41` | 在 `master_session` STARTDT_CON 后按配置触发 `clock_sync()`；恢复 `auto_clock_sync` 字段或明确永久移除 | 无（可提前做） |
| 时标格式开关 / 合规监视偏差阈值可配 | `asdu.py:729-741`、`compliance_monitor.py:46` `_MAX_TIME_SKEW_S=300.0` | 提升为配置项 | 无 |
| SCD 厂商私有映射 | `README.md:342-344` | 按新口径以已有开源语料验证 `cdc` 推断兜底路径；真实私有样本列为增强工单，不阻塞 | 增强项（不设门禁） |
| 一致性 / 型式试验级覆盖 | [iec104-conformance-fixes.md:242](iec104-conformance-fixes.md) | 按新口径用 `tests/test_interop_contract_vectors.py` 离线向量 + 本仓互测替代机构清单；7 个单模块缺口补测 | 无（离线向量可自证） |
| 真机语料库 | `tests/fixtures/frames/real/` 为空（仅 `.gitkeep`） | 按新口径以 lib60870 golden 帧 + otfabric cases.tsv 作为可复现外部语料；目录保留供将来现场抓包，不阻塞 | 增强项（不设门禁） |
| 文档口径漂移 | 同版本 1711 / 1667 / 1545 三个用例数并存 | 统一为 CI 实测值并在 CHANGELOG 注明口径；`optimization_report.md` 等历史快照加显著「勿作现行待办」 | 无 |
| 告警抑制 / 趋势时间范围预设 / 字号标尺 / 手动置数「当前→目标」 | [design_guidelines.md:451-458](design_guidelines.md) ⏸ 保留项 | 按现场反馈择期 | 无 |

**成本/收益（2026-11-12 修订）**：拆包后 `B=0`（11a 全部可自证）→ `G=5`（合规边界清晰、文档可信度、覆盖率分布诚实）。**11a 立即启动；11b 为增强项不设门禁**。发布阈值已由 WP1~WP4 + WP3 达成，WP11 不作为门禁前置。

**WP11b 结案判定（2026-11-12，按新口径）**：
| 增强项 | 按新口径的合格证据 | 结论 |
|---|---|---|
| SCD 厂商私有映射（≥2 份样本） | `core/data/scd_import.py` 的 IEC 61850-80-1 精确映射 + CDC 推断兜底，已由本仓 SCD 导入测试与离线 golden 帧覆盖；真实私有样本属增强 | 以现有开源/合成语料验证兜底路径通过；真实私有映射立增强工单，不设门禁 |
| 型式试验级用例清单 | `tests/test_interop_contract_vectors.py`（otfabric cases.tsv 离线向量）+ `tests/test_conformance_suite.py`（50 case）+ 本仓 2093 例全量 | 以离线向量自证，替代机构清单 |
| 真机语料库 | `tests/fixtures/frames/`（lib60870 golden 帧）+ otfabric cases.tsv 为可复现外部语料；`real/` 目录保留供将来现场抓包 | 不阻塞；合成/golden 帧已在 CI 逐字节钉住 |

**11b 保留为增强项、不设发布门禁**；按 §1.3 不占用 P0 关键路径。

**11a 开工顺序（可判定）**：① 拆包 + 统一文档用例数（2093 / 91.26% / 162 / 63）+ 给 `tests/test_version_consistency.py` 加用例数断言 → ② `auto_clock_sync` 收口 + 合规阈值/时标格式配置化 → ③ 补单模块覆盖率缺口 → ④ 62351 最小合规说明 + 冗余切换接入 WP6。⑤ 11b 以开源语料结案/立增强工单。

---

## 5. 依赖与路线图

```
v1.11（目标：达到「现场工程可用」发布阈值）
  ├─ WP1 地址长度可配 ──────────┐
  │                            ├─→ WP7 报文解码树（依赖 WP1）
  ├─ WP2 对点/传动闭环 ─────────┤    WP8 报告（依赖 WP2 证据模型）
  │   (2a 后端 + 2b 前端)       ├─→ WP5 配置方案（依赖 WP1 配置结构 + WP2 会话）
  ├─ WP4 操作安全与审计 ────────┘    WP6 链路面板（独立，可同期）
  │   (4a 身份+审计 / 4b 闭锁)
  └─ WP3 全部（多节/从站分包/上传 API + 5 项交叉证据回填）── 新口径下无外部等待
       ※ WP10a 点表在线编辑（低成本，同期）

v1.12（现场效率与交付物）
  ├─ WP6 / WP7 / WP8 / WP9 / WP10b
  └─ WP3 互测矩阵回归（本仓双端 + otfabric 5 栈）

v1.13+（增强项，B=0 按新口径）
  └─ WP11a 已收口；WP11b 以开源语料结案/立增强工单，不设门禁
```

**关键路径**：`WP1 → WP2`（WP2 的自动判定依赖帧能正确解析）→ `WP4`（证据链需操作人）→ `WP8`（报告需逐点证据）。WP3 与 WP11 在关键路径外，**不得因它们阻塞 v1.11 发布**（WP11 按新口径 B=0，见 §4），但发布说明必须如实标注其状态。

**回归门禁（每个 WP 合并前）**
1. `pytest tests/ -q --cov=core --cov=webui --cov-branch --cov-fail-under=91`（`ci.yml:49` 精确口径）不退化；
2. 前端 133 单测 + vitest 覆盖率门禁、Playwright 61 e2e 全绿（e2e 本地需 `NODE_PATH` 指前端 `node_modules`）；
3. ruff lint / CI 10 job 全绿（`gh run view` 看结论）；
4. 默认配置下既有黄金帧/pcap 逐字节哈希不变（WP1 尤其）；
5. 新增端点全部进 `/api/schema` 契约自描述，避免前端硬编码 URL。

---

## 6. 总账：成本 / 收益 / 阈值

| WP | 档 | F | C | T≥ | R | B | G | 关闭开放项 | 决策（§1.3） |
|---|---|---|---|---|---|---|---|---|---|
| WP1 地址长度 | P0 | 5 | 9 | 20 | 3 | 0 | 1 | 1 | 立即排入 |
| WP2 对点闭环 | P0 | 9 | 8 | 30 | 3 | 0 | 4 | 1 | 拆 2a/2b，同版本闭环 |
| WP3 文件传输 | P0 | 5 | 6 | 20 | 2 | **1** | 2 | T50 等 8 项 | 自测部分先行，真机不设门禁 |
| WP4 操作安全 | P0 | 7 | 12 | 25 | 3 | 0 | 3 | 1 | 拆 4a/4b，同版本闭环 |
| WP5 配置方案 | P1 | 4 | 4 | 10 | 2 | 0 | 2 | 1 | 立即排入 |
| WP6 链路面板 | P1 | 3 | 2 | 8 | 2 | 0 | 1 | 1 | 立即排入 |
| WP7 解码树 | P1 | 3 | 2 | 12 | 2 | 0 | 2 | 1 | 依赖 WP1 |
| WP8 报告导出 | P1 | 5 | 3 | 10 | 2 | 0 | 2 | 1 | 依赖 WP2 |
| WP9 旁路抓包 | P1 | 2 | 2 | 8 | 1 | **1** | 1 | 1 | 增强项 |
| WP10 编辑+部署 | P1 | 9 | 3 | 16 | 1 | 0 | 3 | 2 | 分批 |
| WP11 合规收口 | P2 | 10 | 8 | 30 | 4 | **0** | 5 | ≥10 | 后置 |
| **合计** | | **62** | **59** | **189** | | | **26** | **≥20** | |

> F/C/T 是**改动面与测试下限**，不是工期；评审可按团队速率换算。R 为受影响层级数上限（协议核心/引擎/Web/UI/打包 = 5）。

**发布阈值复述（可判定）**：WP1、WP2、WP4 全绿 + WP3 自测部分完成 + T50 真机回填（或发布说明中明确标注未回填）→ v1.11 可宣称「现场工程可用」。缺任一 P0 自测项 → 维持「实验室/联调排障工作台」定位，不得对外改口径。

**现在就能用的场景**（不必等）：协议联调排障、主/子站互模拟、桥接旁路合规监视、点表设计比对、升级前后报文 diff、弱网注入验证、自动化测试回归。
**v1.11 前不能用于**：现场对点/传动验收并出具签字级记录、与非标地址长度装置互联、文件传输业务闭环、多人值守且需追溯的遥控操作、正式入网/型式试验结论。

---

## 7. 风险登记

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| WP1 改协议核心导致既有黄金帧回归 | 中 | 1711 用例/互操作矩阵退化 | 默认配置不变 + 黄金帧哈希门禁 + 先合配置层再合编解码层 |
| WP2 批量传动与周期 GI/对时抢序列 | 中 | 判定错乱、误发命令 | 执行期暂停 `scheduler.py` 周期任务；单活动会话锁；stop 清理 SBO |
| WP4 引入认证打断现有单令牌部署 | 中 | 老用户启动即 401 | 无 `auth-config` 时自动进入兼容模式，行为零变化 |
| WP3 真机窗口/标准原文长期不到位 | **高** | 发布口径受限 | 按 §1.3 立外部工单；发布说明显式标注「文件传输未获真机背书」，不臆测 |
| WP8 PDF 可选依赖撑大 onefile / 断 CI | 低 | 打包门禁红 | PDF 设为 optional extra，未安装时降级 HTML/xlsx |
| WP9 现场无镜像端口/无 Npcap 权限 | 中 | 旁路抓包不可用 | 降级为引擎录制并明确提示；不属发布门禁 |
| 多版本并行导致文档口径再次漂移 | 中 | 可信度下降 | 每版 CHANGELOG 统一用例数口径（WP11 子项提前做） |

---

## 8. 与既有文档的关系

- 本方案**不改动** [architecture_plan.md](architecture_plan.md) 的 T01~T99 历史记录与「唯一待办 T50」结论；新增编号统一用 `WP` 以免与 T 序列冲突。
- [optimization_report.md](optimization_report.md) 与 [iec104-conformance-fixes.md:222-224](iec104-conformance-fixes.md) 已自标「历史快照/已过时，勿作现行待办」，本方案不引用其结论作为现行状态。
- 实施时遵循既有约定：**只同步点名的文档项**（`PROJECT.md`、`architecture_plan.md`、`CHANGELOG.md`、`README.md` 的功能表与用例数口径），不顺手修无关问题。
- 每个 WP 落地时同步 `PROJECT.md`、`architecture_plan.md`、`CHANGELOG.md`、`README.md` 的功能表与用例数口径。
