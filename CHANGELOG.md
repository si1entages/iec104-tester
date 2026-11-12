# Changelog

本文件记录对外可见的功能/修复；版本号与 `pyproject.toml`、
`core/version.py`、`webui/frontend/package.json` 保持一致。

## [1.11.0] — 2026-11-12

### Added

- **ASDU 地址字段长度可配（WP1 / 现场非标装置互联，方案 `docs/optimization_plan_v111.md`）**：
  新增 `core/protocol/address.py`，把历史上硬编码的 CA 2B / IOA 3B / COT 2B 提升为
  一级配置，支持 **CA 1/2B、IOA 1/2/3B、COT 1/2B**。三种配置方式：
  ① YAML `asdu_address: {ca_length, ioa_length, cot_length}`；
  ② CLI `--ca-length/--ioa-length/--cot-length`（共 7 个新参数，另含桥两侧独立 4 个）；
  ③ 库调用 `set_default` / `use_default` / 单帧 `address_config` override。
  发送侧 74 个 `ASDUBuilder.build_*`、接收侧 9 个解码调用点、离线 diff/翻译/报告摘要
  共用同一真值源；**透明桥两侧各包 `use_default` 实现任务级隔离**，互不串味。
  `ASDU.encode()` 在 IOA 超出配置位宽时显式报错，不静默截断（防止遥控打到错误对象）。
  `/api/status` 新增只读 `asdu_address` 键，Carbon/PF 状态总览页显示生效口径。
  详见 [`docs/asdu_address_config.md`](docs/asdu_address_config.md)。

- **对点/传动验收闭环（WP2 / 现场交付物，方案 `docs/optimization_plan_v111.md`）**：
  新增「对点传动」页面（master/slave 角色可见，bridge 隐藏）：从点表勾选 + 填期望值/
  回读异址 `command_ioas` 建会话 → 一键批量传动（逐点 SBO 两段式/设点/步命令）→
  自动判定（品质异常/值不符/超时/SBO 否定确认一律 FAIL，无期望值判 MANUAL
  待人工，不出假 PASS；YC 按容差）→ 人工改判 → 导出 **xlsx / json / html** 三格式
  可签字交付物（逐点带下发帧/回读帧 hex 与时间，HTML 全转义可直接打印）。
  会话落独立 SQLite `data/commissioning.db`（WAL），刷新/重启可恢复；执行期间
  暂停周期 GI/对时、中止补发 DEACT 清理已选未执行遥控；`commission.*` 事件复用
  既有 WS `event` 通道。新增 REST 端点 8 个（契约 `webui/api_contract.md` §2.4c）。

- **操作审计 + 多用户三角色（WP4a / 现场交付物，方案 `docs/optimization_plan_v111.md`）**：
  新增「操作审计」页面（master/slave 角色）：每条主站命令/子站置数/传动下发自动追加
  **SHA-256 哈希链**（`hash=SHA256(prev_hash‖canonical)`，独立 SQLite `data/audit.db`），
  记录操作人/角色/来源 IP/动作/目标/结果/原因/**下发与回读帧 hex**；「校验链」一键
  检测事后删改并报出断点 id；导出 JSON/CSV 归档。被权限拒绝的操作**不入链**（越权
  无痕可查证）。新增 `--auth-config users.yaml` 多用户三角色
  （viewer 只读 / operator 可操作 / admin 全权，权限矩阵见契约 §2.4d）；
  **兼容模式（未配置认证）行为与 v1.10.0 完全一致**；仅配单 token 时为匿名 admin，
  前端可用「操作人」输入（`X-Operator` 头）归因，多用户模式忽略该头防冒名。
  WP2 每条传动记录自动复用同一条审计链。新增 REST 端点 4 个
  （`/api/audit/records|verify|export`、`/api/auth/users`）+ `/api/auth` 纯新增
  `mode/operator/role` 字段（契约 `webui/api_contract.md` §2.4d）。

- **防误操作闭锁（WP4b / 现场安全，方案 `docs/optimization_plan_v111.md`）**：
  点表 YK/YC/STEP 点可声明 `interlock`（引用遥信期望位置，多条件 AND），
  遥控/设点/升降/比特串在**发送任何帧之前**求值——不满足则**零帧下发**并返回
  业务错误与条件明细；取值失败（遥信未上送）按不满足处理（未知工况不操作）。
  拒绝与「强制解锁」均写入审计哈希链（`yk/interlock-blocked` / `yk/force-unlock`），
  强制解锁需 admin 角色。DEACT 撤销帧不受闭锁限制（安全清理必须可发）。
  界面：点表「联锁」标记（内联不新增列）+ 命令弹窗条件提示与强制解锁复选框。
  详见 [`docs/interlock.md`](docs/interlock.md)。

- **工程配置方案管理（WP5 / 现场交付，方案 `docs/optimization_plan_v111.md`）**：
  状态总览页新增「工程配置方案」卡片：把当前**连接 / t0~t3 / k-w / ASDU 地址长度 /
  点表引用 / 告警阈值**存成命名方案（纯文本 `configs/profiles/<名称>.yaml`），
  换现场一键切换；**浏览器刷新后自动恢复上次应用的方案**。支持另存/覆盖/删除/
  导出 YAML/文本导入。新增 CLI `--profile <名称>`（无浏览器场景；方案文件本身也
  可直接当 `--config` 用）。方案只覆盖工程参数，**不含** TLS/证书路径、历史库
  保留期与显示偏好；服务端启动**不**自动应用方案（端口/角色仍只由 CLI 与
  `--config` 决定）。REST 端点 8 个（契约 §2.4f），管理动作仅 admin 可写，
  保存/应用/删除写入审计哈希链。详见 [`docs/profiles.md`](docs/profiles.md)。

- **链路参数可观测面板（WP6 / 现场排障，方案 `docs/optimization_plan_v111.md`）**：
  状态总览页新增「链路参数」面板：连接状态机状态与已保持时长、**t0~t3 各定时器剩余**、
  **未确认 I 帧数 / k**、VS/VR、**重连计数与最近失败原因（含从未建连时的原因）**、
  最近 8 次**状态变迁时间线**。`/api/status` 只增只读 `link` 键，且**引擎未启动时也存在**
  （给出配置目标）——"连不上"正是最需要看它的时刻。数据来自三处协议层只读快照
  （状态机 / 序列 / TCP 传输），任何一段异常只降级该段，不影响状态上报。
  契约 `webui/api_contract.md` §2.4g。

- **报文值域解码树（WP7 / 现场排障，方案 `docs/optimization_plan_v111.md`）**：
  报文查看器新增「对象」列，点击就地展开该帧的信息对象子表——**每个 IOA 的值、
  五位品质位（IV/NT/SB/BL/OV）、时标、原始字节**。`/api/frames/decode` 在既有
  分段文本之外**纯新增结构化 `tree` 键**（旧契约不变）。**SQ=1 的连续帧会展开成
  N 行 `base+i`**（此前只能看到"N 个对象同地址"）；品质异常行标色。
  只对含信息对象的 I 帧出子表，S/U 帧给「无信息体」说明。契约 §2.9。

- **原生 Excel / PDF 报告（WP8）**：状态页新增「导出 Excel / 导出 PDF」按钮，
  `GET /api/export/report?format=html|xlsx|pdf` 输出可归档报告（摘要 + **WP2 逐点证据**
  + WP4 审计流水 + 告警 + 结论），三种格式共用同一 `Evidence`，**逐点条数一致**。
  xlsx 三个工作表；PDF 为横向 A4 表。**PDF 依赖 `report[pdf]` 可选 extra**，
  未安装时返回 400 + 安装提示（onefile 包 HTML/xlsx 仍可用）。契约 §2.4h。
- **旁路真实网卡抓包（WP9）**：抓包页新增旁路卡片——Linux `AF_PACKET` /
  Windows Npcap，BPF 过滤 2404 端口，抓到的 APDU 直接复用既有 pcap 写入/导入/
  回放/diff 链路。能力或权限不足时**明确返回原因并降级为引擎录制**，绝不假装抓到包。
  受现场网络镜像/权限约束，属增强项不属发布门禁。契约 §2.14b。
- **标准合规收口（WP11 / 2026-11-12 按新口径结案）**：用户确认「按同一口径处理」——与 WP3/T50 一样以互测 + 开源多实现交叉证据验收，不再等标准原文/厂商样本/检测机构清单/现场抓包。
  - 拆包为 **11a（B=0 已交付）/ 11b（增强项不设门禁）**；方案 `docs/optimization_plan_v111.md` §4 与路线图同步。
  - 新增 `docs/baseline.json` 用例数单一真值源；`tests/test_version_consistency.py` 除版本徽章外**新增用例数断言**（实测把 2121 改成 1711 即失败）；双语 README 基线统一为 **2121 / 91.49% / 164 / 63**。
  - `MasterConfig.auto_clock_sync` 从死配置恢复并在 STARTDT CON 后真实发 C_CS_NA_1（默认关闭零回归）；`compliance.max_time_skew_s`（原硬编码 300.0）与 `time_tag_format` 提升为 YAML 配置，`configs/master_config.yaml` 补样例。
  - `tests/test_wp11a_coverage.py` 表驱动 17 例补齐 `master_protocol` 多类型总召唤响应分支；`tests/README.md` 清单按新口径更新。
  - `docs/tls.md` 补「按新口径合规结论」：**TLS(62351-3) + WP4 审计已由 otfabric 5 栈与离线向量验证**，但 **62351-4/-6 应用层认证、SA、RBAC、CRL、密钥轮换、重放防护仍未实现，不宣称 62351 合规**（诚实边界保留）。冗余双通道切换可观测接入 WP6 面板（活动通道/切换次数/主备连接）。
  - 11b（SCD 私有映射/型式试验/真机语料）以已有开源语料结案、真实样本立增强工单，不设门禁。

- **文件传输完工 + T50 按新口径验收（WP3 / 2026-11-12 结案）**：用户明确反转口径
  （「找不到真机测试，服务端客户端互测 + 其他开源软件测试能过就行」），故以
  **本仓 master↔slave 真实 TCP 互测 + 多独立开源实现交叉证据**验收，不再等真机。
  - 新增 `core/protocol/file_semantics.py` + `AppConfig.file_transfer` 语义档位
    （`ed1` 默认逐字节兼容历史 / `ed2` = lib60870.NET + otfabric 共识 / `project`），
    NOF/SCQ/FRQ-SRQ/WITH_DEACT/分包大小显式化，非法档位加载期报错。
  - **从站多节分包**：≥3 节逐节 `F_SR→SCQ=6→F_SG→F_LS(LSQ=3)→F_AF(3)`、
    最后节 LSQ=1、逐节 CHS；真实 TCP **768B/3 节×256B** 逐字节还原。
  - **主站上传方向**：`POST /api/master/file {action:"upload", data:hex}`，
    主站发段/F_LS → 子站校验 CHS 落盘 → 回 F_AF；真实 TCP **560B 上传** +
    肯定确认 + COMPLETED；CHS 篡改回否定且不落盘。
  - 5 项开放项（NOF / SCQ / WITH_DEACT / 多节 / FRQ-SRQ）以 lib60870-C、
    lib60870.NET、otfabric 5 栈矩阵 + 本仓互测交叉证据**逐项结案**
    （[`docs/file_transfer_open_items.md`](docs/file_transfer_open_items.md)）。
    契约 §2.2 扩展 `/api/master/file`；`configs/master_config.yaml` 加 `file_transfer` 节。
  - **发布阈值达成**：WP1~WP4 + WP3 全部按新口径通过 → 可对外宣称「现场工程可用」；
    剩余仅 WP11（标准原文/厂商样本外部阻塞）。

- **点表在线编辑 + 服务化交付（WP10）**：点表工具栏可新增/编辑/删除点定义
  （`POST /api/points/upsert`、`DELETE /api/points/delete`）；**在线改点不重置设计基准**，
  design-diff 仍能报出差异。交付 `Dockerfile` / `docker-compose.yml` /
  `deploy/iec104-tester.service` / `deploy/install-service.ps1` / `docs/deploy.md`
  （离线部署说明），并把 `capture_tool` 等 CLI 工具纳入 exe 随包。
  **服务化仅解决无人值守长期跑，不改变「非生产 SCADA 网关」安全边界**。契约 §2.4i。

### Fixed

- headless 透明桥（`--mode bridge --no-gui`）此前不加载 `--config`，本次补上
  `asdu_address` 节的加载，避免用户写了 YAML 却被静默忽略。
- 离线报文 diff / 测试报告帧摘要 / 桥帧摘要此前固定 `ca_length=2`，现随生效配置解析。

### 兼容性

- 默认 2/3/2 与 v1.10.0 **逐字节一致**；旧 YAML 缺 `asdu_address` 节自动回落默认值；
  `/api/status` 只增键不改既有键；`POST /api/bridge/start` 的两个新字段可选、不传即旧行为。
- WP2 的 8 个 commission 端点仅 master/slave 角色注册（bridge 角色不注册），不影响既有路由；
  `data/commissioning.db` 为新库，不触碰历史库。
- WP4a 的 4 个 audit 端点同上仅 master/slave 注册；**未配置认证时整体直通**（兼容模式
  行为与 v1.10.0 一致，无审计身份不入链）；`/api/auth` 只增键不改既有键；
  `data/audit.db` 为新库，不触碰历史库。
- WP4b 的 `interlock` 为点表可选字段、`force` 为命令端点可选键：**未配置闭锁的点、
  未传 `force` 的请求、旧点表 YAML 行为与 v1.10.0 完全一致**；`/api/points` 只增键。
- WP5 全部为新增：无方案目录时 `/api/profiles` 返回空列表；不传 `--profile` 时启动路径
  与 v1.10.0 一致；方案 YAML 可被 `--config` 直接加载（双向通用）。
- WP6 全部为新增：`/api/status` 只增 `link` 键、`schemaVersion` 不递增；状态机时间线为
  内存环形缓冲（20 条），进程重启即清空，不引入任何持久化文件。
- WP7 全部为新增：`/api/frames/decode` 只增 `tree` 键，`segments` 结构逐字段不变；
  报文查看器新增一列（96px），既有列宽与筛选行为不变。
- WP8/9/10 全部为新增：`/api/export/report.html` 与既有抓包端点行为不变；
  `report[pdf]` 为可选依赖；旁路抓包在无权限时降级；点表在线编辑不动设计基准。

### 验证

- WP1：`tests/test_asdu_address_config.py`（45 例）+ `tests/test_tcp_bridge.py` 桥隔离 2 例。
- WP2：`tests/test_commissioning.py`（判定规则/持久化/导出转义/API 全流程/编排状态机）。
- WP4a：`tests/test_audit.py` 32 例（哈希链/篡改检测报断点/权限矩阵/兼容模式/编排联动）。
- WP4b：`tests/test_interlock.py` 35 例（解析/求值/点表往返/零帧下发/force 权限/DEACT 例外/API）。
- WP5：`tests/test_profiles.py` 42 例（名称校验/存取容错/3 套方案切换全量还原/点表还原/导入导出/
  方案文件即合法 `--config`/三角色权限/审计）。
- WP6：`tests/test_link_observability.py` 21 例（三处快照语义/**真 TCP 静默对端复现 t1 超时**/
  未建连即有失败原因/降级不崩 status）+ 前端 12 例链路展示逻辑。
- WP7：`tests/test_frame_decode_tree.py` 23 例（SQ=1 20 对象逐字段/五位置品质/SIQ 无 OV/
  截断帧可读错误/旧 `segments` 契约不变）+ 前端 5 例解码树展示逻辑。
- WP8/9/10：`tests/test_export_report.py`（28 例，三格式一致 + PDF 可选依赖降级）+
  `tests/test_sniffer.py`（构造帧解析/畸形帧/权限降级/pcap 往返/端点 40+ 例）+
  `tests/test_points_online_edit.py`（**设计基准不重置**/全类型字段/端点 30+ 例）+
  前端 `pointEdit.test.ts`（8 例）。
- WP3：`tests/test_file_transfer_multisection.py`（13 例，含 3 节真实 TCP + CHS 拒绝）、
  `tests/test_file_transfer_upload_direction.py`（7 例，含 560B 上传闭环）、
  文件传输全套 + 离线互操作契约向量 **101 passed**。
- WP11：`tests/test_wp11a_config.py` 11 例 + `tests/test_wp11a_coverage.py` 17 例 +
  前端 `linkPanel.test.ts` 2 例；`test_config_wiring_cleanup.py` 旧「死字段」断言按接线后语义更新。
- 累计口径：全量后端 **2121 passed / 覆盖率 91.49%**（门禁 91）、前端 typecheck + **179 单测**、
  i18n 清单 0、Playwright **63 e2e**（含视觉基线 `commission-light.png`、`audit-light.png`，
  及因 WP5/WP6 卡片更新的 `status-light.png`）、ruff 全绿。
- 发版前补齐：`webui/frontend/src/lib/wp11Hooks.test.tsx`（15 例，覆盖 WP2/WP4a/WP5/WP9 四个
  共享 hook 的 guard 生命周期、期望值 bool>number>string、`ok=false` 错误呈现、空名拦截、
  无活动方案静默与快照缺省）——修复 v1.11 前端 V8 覆盖率门禁（原 164 单测下
  statements 53.71 / lines 56.12 / functions 49.25 均低于阈值，`npm run test:coverage` 会红）；
  补后 179 单测下 60.72 / 63.36 / 54.33 / 54.46 全过阈。`docs/baseline.json` 同步为 179。

## [1.10.0] — 2026-11-10

### Added

- **Excel(xlsx) 点表导入 + 设计 vs 实测比对（T95 / A2）**：新增 `openpyxl` 运行时依赖；
  xlsx 导出/解析（中英列头 + 中文类型别名兼容、行级错误收集不 fail-fast）、
  `POST /api/points/xlsx/preview|import`（预览无副作用）、导入即快照设计基准 +
  `POST /api/points/design {set|clear}`；`GET /api/points/design-diff` 输出
  **缺（设计有/实测无）/ 多（实测有/设计无，即自动学习兜底进来的真实 IOA）/
  值域（类型不符或实测观测极值越出设计声明域）** 三类清单（清单截断 200，
  summary 为全量计数）。点表导入收 .xlsx（二进制 POST），主站页新增设计比对卡
  （Carbon/PF）——对应真机联调缺口：真机 IOA 16385+ 与演示表 1001 对不上。
- **离线报文对比（T96 / D）**：`webui/frame_diff.py` 纯函数——两段录制
  （`.i104`/`.json`）按规格化签名（方向 + 帧型 + ASDU 头 + 信息体 IOA/值/品质，
  剥 CP56Time2a 时标）做多重集 diff；**忽略会话易变字段**（N(S)/N(R)、时间戳、
  metadata.client_id、S 帧 rx_seq）；`POST /api/capture/diff {a,b}`（路径安全复用
  CaptureService 校验）；抓包页「报文对比」卡（Carbon/PF）。现场标准动作「装置
  升级前后各录一段人工逐帧对比」自动化：自 diff 为空、改值/删帧/COT 变化可检出。
- **桥场景化注入时间线 + 自动判定（T97 / C）**：桥接页新增「注入时间线」卡
  （Carbon/PF）——结构化步骤编排（标签/时长/丢帧%/延迟/期望）→ 逐步施加
  NetworkCondition → 逐窗采集注入统计增量与合规违规（按 ts 归窗）→ 自动判定
  （`none`/`loss`/`k-exceed`/`t1`/`disconnect`）；`GET/POST /api/bridge/timeline`
  + `run|stop`；判定防误报（运行起点吃掉历史违规游标、超时类证据不作「无扰动」
  反证、t3 一律排除），结果自动进测试报告新段「11. 注入时间线」。闭环验收：
  「注入丢包 → 应见 k 超窗」合成帧单测 + e2e 真桥双证据。

### Fixed

- **桥角色状态页 404 轮询**：T98 把桥接页纳入 UI 巡检矩阵后即刻发现——状态页
  无条件挂载告警卡与网络模拟卡，bridge 部署（端点未注册）下轮询
  `/api/alarms`、`/api/simulation` 得 404；改为角色已知且非 bridge 才渲染
  （含 status 未加载首帧闪现防护）。
- **录制同秒撞名**：默认捕获文件名按秒生成，两段录制在同一秒内完成会互相
  覆盖（T96 e2e 实测）——e2e 显式命名规避；`GET /api/capture/diff` 文件名
  校验沿用 CaptureService._path，防路径穿越。

### Quality gates

- **T98 桥接页纳入 UI 巡检矩阵**：ui-audit / ui-contrast / ui-nontext-contrast
  三门禁补桥接页（走 BRIDGE 8769 webServer；PF/Carbon × 3 视口 × 中英深浅），
  ui-audit 新增独立用例断言 bridge 部署角色隔离。
- **T99 非文本门禁覆盖 PF 伪元素/box-shadow 边框**（T89 遗留收口）：「边框」段
  补 `::before`/`::after` 逐边 border 读取与零偏移/零模糊/正扩散 box-shadow 环
  （readFocus 同筛选），可感知性取内外相邻色较优者。实测 PF 检查数 **0 → 780 处**、
  Carbon 308 处不劣化，PF/Carbon × 中英深浅 × 含桥页 **0 硬失败**。
- 视觉基线随 T95 主站页设计比对卡重录（页高 2063→2199px，预期产品变化）。

### Verified

- 后端 pytest **1711 passed / 4 deselected**；CI 口径 `--cov=core --cov=webui
  --cov-branch --cov-fail-under=91` 合并分支覆盖 **91.11%**（门禁 91 不变）；
  前端单测 **133 passed**、i18n 清单 0、tsc/build 全绿；Playwright e2e **61 例**
  （新增 v110-features 3 例 + 三门禁桥接页）；契约三道门禁（§2.4/§2.14/§2.4a
  与 §4.14/§4.15、contract_check、frontend_routes）双向一致；GitHub Actions
  10/10 job 全绿（含 Windows 视觉基线、双平台打包冒烟、3 Python 版本）。

## [1.9.0] — 2026-11-10

### Added

- **值守告警引擎（T93）**：限值越限（点表 min/max）/ 死值陈旧（>60s，含点表
  陈旧标记）/ 突变 / 通信中断（Running 且 rx 停滞 >10s）四类规则；1Hz 评估 +
  去抖 + active→ack→cleared 生命周期 + 有界历史；`GET /api/alarms[/history]`、
  `POST ack/config`；状态页「值守告警」卡（Carbon/PF，可选声音提示）；点表
  值单元格陈旧灰化 + tooltip；告警历史自动进测试报告。
- **连接医生（T94）**：`POST /api/master/doctor` 分层自检（TCP → STARTDT →
  数据流 → 结论建议），取证含对端 S 帧计数、N(R) 推进、保留 COT 计数；对
  「链路通但对端不回确认」类缺陷直接给结论（真机 simulator4 实测）；结论随
  测试报告附存（报告新增「9. 连接诊断」段）；连接面板「诊断」按钮（Carbon/PF）。
- **独立 104 主站验收工具**：`tools/qa_independent_master.py`（裸 socket 按标准
  手写，不经本项目引擎）——外部互操作验收用。

### Fixed

- **I 帧 N(R) 隐式确认不停 t1（真机联调修复）**：原实现只认 S 帧确认，对
  「用 N(R) 隐式确认、少发 S 帧」的合规设备，每发一条命令都会在 t1(15s) 后
  误判超时断链。`process_rx_i_frame_ack` 返回确认窗口是否推进，主/子站会话
  据此停 t1；回归用例锁死（假子站只回 N(R)=1 的 I 帧 → t1 不得超时）。
- **趋势图关闭 ECharts 动画**：高频点值流下 2Hz 重绘的整线滑动像跑马灯，
  按 ISA-101 改瞬时重绘（Carbon/PF）；趋势图单采样态提示（等待数据变化）。
- **PF 桥接页条件卡遮挡**：条件卡裸放在两个 PageSection 之间被后续 section
  覆盖，「应用条件」按钮真实不可点——包进独立 PageSection 修复。

### Verified

- 第三方 simulator4.exe（127.0.0.1:24040）真机联调：连接/STARTDT/GI/对时/
  读/设点全部走通且连接稳定；趋势图像素级验证（曲线区 956 曲线色像素）；
  子站外部通信经独立主站 80 点读取 PASS。后端 pytest **1667 passed**；
  Playwright e2e **57 passed**（新增 trend-live 像素级回归 + T90 五条）；
  前端单测 133 passed；CI 口径 core+webui 分支覆盖 91%。

## [1.8.0] — 2026-11-09

### Added

- **桥上网络条件注入（混沌验收）**：桥从「观察→审计」升级到第三级「主动干扰」——
  桥接观察页可设置丢帧/重复/损坏/延迟/乱序/断线率，主动制造劣质链路考验主站
  容错（k/w、t1/t2/t3、重连）；条件作用于转发路径，旁路观察与合规监视始终看
  干扰前的原始帧（审计证据不污染）；每条链路独立断线状态、运行中动态设置、
  注入统计跨连接累计并进入状态页与测试报告。
- **应用层合规规则第二批**：公共地址不符（会话基线 / 显式期望配置双模式）、
  连续重复自发帧（同类型+IOA+值在 10 秒内 COT=3 重复——设备抖动缺陷）、
  CP56 时标偏离观察时刻超过 300 秒；对象体解析失败一律跳过（保守）。
- **报告嵌曲线快照**：历史页看过的曲线自动嵌入测试报告（最多 4 张 PNG，
  自包含有图可看）；状态页导出改 POST（base64 不放 URL query）并在失败时
  降级 GET；报告只接受 PNG dataURL 前缀（防属性注入）。

### Verified

- 后端 pytest **1654 passed**（新增注入器 11 项、桥注入端到端 4 项、
  条件端点 2 项、合规第二批 7 项、报告嵌图 2 项）；前端单测 **133 passed**；
  Playwright e2e **46 passed** 全量；CI 口径 core+webui 分支覆盖 **91%**；
  typecheck/build、i18n 清单 0、对比度硬失败 0。

## [1.7.0] — 2026-11-09

### Added

- **应用层合规规则**（桥接观察页）：合规监视从传输层深化到应用层——方向错位
  （子站发控制激活帧 / 主站发监视类型）、无请求的响应（COT=7 前无同类型在途
  ACT）、总召唤未终止（未见 COT=10 即再次启动）、非召唤期数据（COT=20~36 /
  37~41 无对应请求）、COT=0；ASDU 只解析头部（畸形对象体不影响监视）；违规
  照旧实时进桥接页与测试报告。
- **报告结论横幅**：状态页导出报告时可填「测试结论」（合格/不合格/有条件
  通过）与说明——报告头部生成彩色结论横幅（合格绿/不合格红/有条件琥珀）。
- **多连接并发压测**：压测卡可设并发连接数（1~8）——压测自建 N 条主站连接
  （每条独立 STARTDT/GI）同时接入子站，总帧数 ≈ 事件数×连接数；统计按连接
  分行（帧数/字节/错误）+ 汇总行。
- **TLS 透传桥**（104S 链路排障）：桥两侧独立可配 TLS——
  `--bridge-listen-tls-cert/key`（桥对主站扮演 TLS 子站）+
  `--bridge-upstream-tls-ca[/cert/key/hostname]`（桥对子站以 TLS/mTLS 接入）；
  明文↔TLS 混合桥接同样支持；TLS 终结在桥，帧内容解密可见（合规监视/录制
  照常工作）。

### Fixed

- 压测结束态 status 从空账目算出 0（引擎拆除后按冻结汇总回放）。
- 压测 STARTDT 等待期间二次启动穿透幂等保护（busy 标志入口同步置位）。

### Verified

- 后端 pytest **1628 passed**（新增应用层合规 9 项、TLS 桥 2 项、结论横幅 2 项、
  多连接端到端用例）；前端单测 **133 passed**；Playwright e2e **46 passed**
  全量；typecheck/build、i18n 清单 0、对比度硬失败 0。

## [1.6.0] — 2026-11-09

### Added

- **历史趋势回放**：历史查询页新增「曲线」页签——按类型（YX/YC/YM）+ IOA
  添加 1~8 个序列，时间范围随查询生效，回放点位历史曲线（遥信/遥脉阶梯、
  遥测折线）；数据源自既有 `data_history` 点位时间序列。
- **协议合规监视**（桥接观察页）：透明桥旁路自动指认传输规约违规——I 帧发送
  序号跳变/重复、确认序号超前（确认未发出的帧）、未 STARTDT 即传数据、
  STARTDT 重复、TESTFR 未获确认重复、k 超窗、t1/t2/t3 超时；违规列表实时
  更新并自动进入测试报告（桥从观察器升级为审计仪）。
- **时钟偏差测量**：主站工作台命令面板「测量时钟偏差」——连发时钟同步命令，
  按子站确认帧携带的子站时钟计算偏差（ms，N 次平均/范围）。
- **报告压测贯通**：压测跑过后「导出测试报告」自动带压测汇总段落
  （事件数/帧数/平均速率/错误）。

### Fixed

- **子站时钟同步确认帧回显主站时间**：按 IEC 60870-5-104 确认帧应携带
  **子站当前时钟**（否则偏差无法测量），已改为携带子站实时时钟。
- 主站时钟同步确认极快返回时偏差样本漏采（发送前先记录时间戳的竞态）。

### Verified

- 后端 pytest **1617 passed**（新增合规监视器合成帧序列 12 项确定性用例、
  时钟偏差真引擎 3 连测）；前端单测 **133 passed**（32 文件）；Playwright
  e2e **46 passed** 全量（新增历史曲线页用例）；typecheck/build、i18n 清单 0、
  对比度硬失败 0。

## [1.5.0] — 2026-11-08

### Added

- **SCD/CID/ICD 点表导入**（IEC 61850 → 104）：子站工作台点表面板「导入」——
  按 IEC 61850-80-1 `Private/Address(casdu,ioa,ti)` **精确映射优先**，无映射按
  DOType `cdc` 推断并按类别分区自动分配 IOA；**先预览**（分类计数 + 告警 +
  可编辑 YAML，多公共地址/IOA 冲突/不支持类型全部告警）再应用；
  YAML/CSV/JSON 直接导入（经典版界面除外）。
- **透明桥 / 旁路监听**：真实主站 ↔ 测试器 ↔ 真实子站。
  - `--mode bridge --no-gui`（headless）：字节级透传（转发永远优先于观察）、
    逐帧摘要日志、`--capture-file` 录制（.json/.pcap）；
  - Web 桥接观察页（默认，8767）：表单启停 + 运行统计（双向帧/字节/客户端/
    重同步）+ 实时报文；菜单按部署角色出现。
- **测试报告导出**：状态总览页一键导出自包含单文件 HTML（浏览器打印即 PDF）：
  会话信息 + 帧统计聚合 + 帧证据逐帧解码 + 事件表。
- **压测编排**（吞吐验收）：测试中心压测卡——子站按目标速率（1~10000 事件/秒）
  自发 YC/YX，主站侧差分统计吞吐（平均事件率/帧率/错误数），时长与速率可配
  （仅单进程双角色模式可用）。

### Verified

- 后端 pytest **1602 passed**；前端单测 **133 passed**（32 文件）；Playwright
  e2e **45 passed** 全量（新增 SCD 导入与桥接观察页用例）；typecheck/build、
  i18n 清单 0、对比度硬失败 0。

## [1.4.0] — 2026-11-08

### Added

- **三套界面共存，同地址即时切换**：`/app/` 内在 **Carbon**（IBM Carbon Design
  System）、PatternFly 6 与 经典版（v1.3.1 antd 界面冻结快照）之间页内切换——
  不刷新、不改 URL，连接/页面/深浅主题/语言保持；右下角 UI 圆钮或 `?kit=` 指定，
  三套覆盖同样的页面与全部主站命令/子站面板。
- **单文件双角色单页工作台**：`iec104-tester` 双击默认同时启动主站+子站，单进程
  单端口 8765，左侧菜单原生切换主站/子站工作台（无 iframe、无双端口）；
  `--mode master|slave|both` 仍可单角色运行；角色切换不清点表/报文缓存。
- 子站模拟控制支持 **YX/YC 独立开启**（只模拟遥信或只模拟遥测），
  `POST /api/slave/sim` 新增 `yx_enabled`/`yc_enabled` 并在状态中回显。
- 自动化 UI 门禁进 Playwright：API 契约（真实后端 × schema 全端点）、界面巡检
  （8 页 × 3 视口 × 中英/深浅）、WCAG AA 文本与非文本对比度、视觉基线回归。

### Changed

- **默认界面改为 Carbon**：`?kit=` → localStorage → 默认 `carbon`，存量 pf 偏好
  视为未设置、跟随新默认；三套头部统一收敛为语言切换 + 明/暗图标切换。
- **品质位按 IEC 60870-5-101 标准化**：`IV/NT/SB/BL/OV` 位定义与 `/api/points`
  品质字符串（`GOOD`、`IV|NT` 等）对齐标准；子站注入面板支持五位置（含 SB）。
- 界面按 `docs/design_guidelines.md` 落地：品质标签语义色、数值右对齐、单位与
  小数位、危险操作 danger 方向、四态（加载/空/错误/降级）完备。
- 主站工作台选中行与趋势 watch 在切页/切套件后保留；「加入趋势」立即以当前值
  作为首个采样。

### Fixed

- 报文查看器悬停翻译恒显示「翻译失败」：前端误读 `/api/frames/decode` 响应形状
  （自功能上线即存在），已对齐扁平 `{ok,format,segments}` 契约并加真实后端回归。
- 趋势图加入点位后曲线一直为空：图表容器为条件渲染、一次性初始化逻辑读到空
  引用后不再重试（三套界面同根因），现随容器出现重试初始化；隐藏页签 0×0 画布
  一并修复。
- 主站命令面板「当前值」冻结在选中瞬间，现跟随 WS 刷新。

### Verified

- 后端 pytest **1562 passed**；前端单测 **133 passed**（32 文件）；Playwright e2e
  **43 passed** 全量；typecheck/build、i18n 清单 0、对比度硬失败 0。

## [1.3.1] — 2026-11-07

### Changed

- 清理 Ant Design 6 弃用告警（前端测试告警从 5 类降为 0）：
  `Alert message` → `title`、`Space direction` → `orientation`、
  `InputNumber addonAfter` → `suffix`、`Modal maskClosable` → `mask.closable`、
  `Statistic valueStyle` → `styles.content`。

### Verified

- 文件传输 C4 回归（第三方 lib60870-C v2.4.1，非真机）：v1.3.0 代码重跑
  800B / 2 节 / LSQ 3,3,1 / CHS 184,72,0，接收完成且无告警；真机项仍待复测。

## [1.3.0] — 2026-11-07

### Changed

- **前端依赖大版本升级**（Dependabot #6，17 项）：React 19.3、Ant Design 6.6、
  TypeScript 7.0、Vite 8.3、Vitest 5.1、ECharts 6.1、zustand 5、jsdom 30 等。
  无协议/API 变更，产物与交互保持一致。
- TypeScript 7 移除 `tsconfig` 的 `baseUrl`：改用
  `paths: {"@/*": ["./src/*"]}`。
- Ant Design 6 移除 `.ant-select-selector` / `.ant-tabs-tabpane-active` 等内部类名：
  测试改用 `role=combobox` / `role=tabpanel` 与 `aria-label`
  （`CommandPanel` / `ManualSetPanel` 补充可访问标签）。
- Vitest 5 + `@vitest/coverage-v8` 5 的覆盖率统计口径变化（旧口径 lines 81%
  → 新口径约 60%）：阈值按新口径重基线为 statements 55 / lines 58 /
  branches 50 / functions 53，并在 `vitest.config.ts` 注明原因。
- CI：`actions/download-artifact` 7→8（#5）。v8 为 ESM，且下载摘要不匹配
  默认直接失败；本仓库 `path` + `merge-multiple` 用法不变。

## [1.2.0] — 2026-11-07

### Added

- **Web 测试中心**：浏览器内选择 `tests/scripts/*.yaml`，子进程隔离运行，
  实时日志、通过/失败汇总，HTML/JSON/TXT 报告在线下载
  （`/api/tests/*` + “自动化测试”页）。
- **Web 报文录制/回放**：开始/暂停/停止录制；录制文件列表与下载；
  一键导出 pcap/pcapng（Wireshark 可打开）；离线回放（播放/暂停/单步/倍速）
  与帧表（`/api/capture/*` + “报文抓包”页）。
- **冗余双通道 Web 配置与状态**：主站连接面板可启用备用前置机并查看
  活动通道、主/备在线状态、切换次数（`redundancy` 请求字段 + 状态字段）。
- **Web UI HTTPS**：`--web-tls-cert/--web-tls-key`；所有响应增加
  CSP / X-Frame-Options / Referrer-Policy / Permissions-Policy 安全头。
- `--version`：打印 `iec104-tester <version>` 并退出。
- 文件传输 5 项开放问题已用第三方 **lib60870-C v2.4.1** 从站实测回填
  （NOF/SCQ/DEACT/多节/FRQ-SRQ），原始记录见
  `docs/file_transfer_third_party_probe_2026-11-07.md`；真机窗口仍需复测。
- 前端覆盖率门禁（`@vitest/coverage-v8`）与 WebUI 独立覆盖率门禁（≥85%）。
- e2e：历史查询、网络模拟、AuthGate、中英切换。
- CI：`concurrency` 取消旧 run、Python 3.14 矩阵、夜间性能基准、
  PR 阶段 Linux onefile 打包 dry-run、Dependabot。

### Changed

- 版本号统一由 `core/version.py` 提供；新增版本一致性测试。
- README 增补 Web 测试中心、录制回放、冗余 UI、HTTPS 截图与说明。

### Fixed

- **文件传输与第三方从站互操作**（lib60870-C v2.4.1 实测）：
  - 文件命令改为 `F_SC_NA_1(122)+COT=FILE(13)`（旧 `F_SC_NB_1(127)+COT=ACT(6)`
    被静默忽略）；
  - 收到 `F_SR` 自动发 `SCQ=6` 节请求；`F_LS` 按 LSQ 回
    `F_AF(肯定文件/肯定节)`；
  - 主站不再发送非标准 `F_FR_NB(128)/F_SR_NB(129)` 确认；
  - CHS 改为按本节段数据校验，支持多节（第三方 800B/2 节实测完成）。
- 文档中 “TLS/冗余未实现”“i18n 剩余 20 文件/535 行” 等历史快照表述已加注
  当前状态，避免与实现漂移。

## [1.1.0] — 2026-11-07

### Added

- Web 网络异常模拟卡片、访问令牌认证（`--auth-token` / `--http-host`）。
- 历史库查询页；分支覆盖率 92%；`qa_full_flow` 进 CI。
- 全站中/英双语（阶段一 + 阶段二，迁移清单归零）。

## [1.0.0] — 2026-11-06

### Added

- 历史库查询 Web UI、一键诊断包、双平台发布流水线、TLS 传输加密、
  冗余双通道、互操作语料库、性能/长稳基准。
