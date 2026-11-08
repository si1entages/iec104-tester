# IEC 60870-5-104 Tester

## 项目用途
IEC 60870-5-104 协议测试工具，支持主站/子站模拟、报文录制回放、
网络异常模拟、一致性测试。面向电力系统 SCADA 调试和测试场景。

## 技术栈
Python 3.11+, Web UI (aiohttp + HTML/CSS), asyncio, struct（协议编解码）

## 架构分层
入口层: app.py（统一 Web 入口 + headless CLI + `--mode master|slave|both`，单文件发布入口） / apps/web_master.py / apps/web_slave.py（源码瘦入口） / run_tests.py / capture_tool.py / sim_tool.py
↓
Web UI层: webui/ （静态页 + REST/WebSocket）
  ├── server.py
  ├── bridge.py
  └── static/
↓
引擎层: core/engine/ （主站/子站/多站）
↓
协议层: core/protocol/
↓
传输层: core/transport/
↓
数据层: core/data/


## 核心模块速查

| 模块 | 职责 | 修改频率 |
|------|------|---------|
| core/protocol/asdu.py | ASDU 编解码，TypeIdentifier → 解析逻辑映射 | 高 |
| core/protocol/types.py | 72 种 TypeID 枚举定义 | 低 |
| core/protocol/apci.py | APCI 帧头编解码（I/S/U 格式） | 低 |
| core/protocol/sequence.py | k/w 流控计数器 | 中 |
| core/protocol/state_machine.py | START/STOP/TEST 状态机 | 中 |
| core/protocol/file_transfer.py | IEC 104 文件传输（目录/读/写） | 低 |
| core/engine/master.py | 主站引擎（发送命令、处理响应） | 高 |
| core/engine/slave.py | 子站引擎（响应召唤、上报数据） | 高 |
| core/engine/multi_station.py | 多站并发管理 | 中 |
| core/transport/ | TCP 异步连接管理（读循环退出必须 `close()` transport，否则 FD 泄漏且 `TCPServer.stop()` 阻塞） | 低 |
| core/data/ | 点表模型、实时数据存储 | 中 |
| core/testing/ | YAML 测试脚本执行引擎 | 中 |
| core/capture/ | 报文录制/回放 | 低 |
| core/simulation/ | 网络异常模拟（丢包/延迟/乱序） | 低 |
| core/config.py | 配置管理（JSON/YAML） | 低 |
| webui/diagnostics.py | 一键诊断包（状态/配置脱敏/日志/帧/事件/点表/历史统计） | 低 |
| tests/fixtures/frames/ | 互操作语料库 + golden manifest（合成基线 + `real/` 真机目录） | 中 |
| tests/perf/ | 性能/长稳基准（默认 `-m "not perf"` 排除） | 低 |
| tools/mutation_smoke.py | 协议层变异冒烟（CI job；当前 12/12 killed） | 低 |
| .github/workflows/release.yml | tag → 双平台打包/启动冒烟/SHA256/GitHub Release | 低 |

## 关键设计约定

### 协议层
- APCI: I 格式（信息）、S 格式（确认）、U 格式（控制）
- ASDU 结构: TypeID(1B) + SQ(1B) + Cause(2B) + CommonAddr(2B) + IOBs + 数据体
- 72 种 TypeID 在 types.py 用枚举定义，asdu.py 按 TypeID 分发解析
- k/w 流控: k=12（未确认上限）, w=8（确认间隔）
- 品质位按 IEC 60870-5-101 定义：IV=0x80 / NT=0x40 / SB=0x20 / BL=0x10 / OV=0x01；编解码、注入与展示共用 `QualityFlag`
  —— **`QualityDescriptor.to_int()` 必须保留 bit7**（曾用 `& 0x7F` 截掉 IV，导致注入"无效"品质被读回 GOOD）
- 品质位注入 `ResponseBehavior.quality_mask()` 只允许使用 `QualityFlag` 常量，不得写字面量（历史上两处掩码不一致）

### 编码风格
- 协议层: 纯同步 struct.pack/unpack，无 async，无 GUI 依赖
- 解码严格性: `APCICodec.decode` / `ASDU.decode` 对畸形/截断输入只抛 `ValueError`；ASDU 信息体数量与 VSQ 不符、对象数据不足时**显式报错**，不再静默返回空对象（fuzz 用例 `tests/test_protocol_fuzz.py` 兜底）
- 引擎层: asyncio，通过 core/transport 管理 TCP 连接
- GUI 层已移除（原桌面框架）；界面为 webui/（HTML/CSS + aiohttp），纯 web 形态——浏览器是唯一 UI，无桌面壳
- 入口层 app.py 提供统一 Web 入口 `run_web()`：启动服务后台线程轮询端口就绪后再打开浏览器；`--no-browser` 关闭自动打开
- 后台任务: 引擎层统一用 `_spawn()` 创建，保留任务引用并记录异常
- 响应注入: `ResponseBehavior` 承载延迟/丢帧/损坏/不响应/品质/错误 COT；错误 COT 由 `SlaveEngine._reply_cot()` 统一处理（应答 COT +1，配置项 `errors.wrong_cot`）
- 网络异常注入: 代理必须挂在**传输层回调**（`engine._client._on_frame` / `engine._server._on_frame`，二者均为动态读取）上，帧进入协议处理前拦截；**不得包装引擎 raw_frame_callback**（UI 观测点），且 install 前须保存原始回调供 `uninstall_from_engine` 恢复（`SimulationManager` 曾因二次包装覆盖 `_original_rx` 导致 RX 帧绕过协议处理）
- 真机语义优先: 功能语义有歧义时按真实装置行为实现（用户明确要求）。已落地：遥控→同 IOA 遥信变位 + SOE 上送、遥调→同 IOA 遥测更新 + 上送（`SlaveEngine._reflect_command_result`）；召唤按点表声明分流单点/双点
- 前端约定: `app.js` 必须把 `$`/`$$` 暴露到 window（页面内联脚本直接用裸 `$` 绑事件，漏暴露会静默导致所有按钮失效）；点值刷新走 WS `"refresh"` 协议 + 节流，不做整表重建
- 按钮状态单一来源: 顶部「连接/断开」「启动监听/停止」的 `disabled` 只由**服务端状态快照**（`status.started`）驱动，不得只靠点击后的返回码 —— 否则页面刷新后按钮与真实状态不一致，用户"点不了"
- UI 风格: **以 [`docs/design_guidelines.md`](docs/design_guidelines.md) 为准**（PatternFly/Carbon 组件模式 + ISA-101/NUREG-0700 领域规则 + antd token 落地）。要点：首次跟随系统主题偏好（缺省深色）、浅色可切换；颜色只表达状态且必须同时有文字/图标；点表数值右对齐、小数点成列、带单位与品质解码；危险操作二次确认且 `danger` 只用于危险方向；每个数据面四态（加载/空/错误/降级）完备
- 状态一致性: 任何会改变服务端状态的分支（含"已是该状态"的空操作）都必须广播事件，前端据此重新对齐；前端另加 5s 兜底轮询，保证最终一致
- 帧格式必须字节级对照标准: APCICodec 编码端曾把 S 帧 SS 的 bit0 置 1，自家解码 `>> 1` 掩掉后互通自洽，真机按标准校验直接断开。编码与解码要**独立对照标准**，不能只对拍
- 真机兼容性: 部分装置每次连接都发 EI 并高频推流，收到主站 I 帧会断开——自动重 GI 默认关（`auto_gi_on_init_end`）；对这类装置用 `tests/e2e/qa_real_device.py` 做只读验证
- IOA 一律按**十进制**表示与存储（点表 YAML/界面/实时库）；标准不规定遥信遥测的 IOA 范围，地址规划是项目约定——写点表时注意别把十六进制字面量当十进制（0x4001=16385≠4001）
- 遥测不刷新先查**设备是否自发上送**：实测有真机只回总召唤数据（静默 70s 零遥测帧），此时用周期总召，不要误判为主站解析/更新问题
- 协议完整性: `TypeID` 枚举里**每个类型都必须同时有解码注册与 ASDUBuilder 构造器**（否则就是"能解不能发"的半实现）；新增类型时用 `tests/test_protocol_type_coverage.py` 的护栏用例兜底

### 测试
- 单元测试: tests/test_*.py（**1545 例**；`tests/perf/` 由 `-m "not perf"` 默认排除）
- 协议 fuzz: tests/test_protocol_fuzz.py（Hypothesis；解码器只允许 `ValueError`）
- 互操作回放: tests/test_frame_corpus_replay.py + tests/fixtures/frames/（golden + MasterEngine 回放）
- 性能/长稳: `pytest tests/ -m perf`（解码吞吐 / 10 万点快照 / 环回 soak，时长由 `IEC104_SOAK_SECONDS` 控制）
- 变异冒烟: `python tools/mutation_smoke.py`（协议层 12 个高价值变异必须全部被杀死）
- 一致性测试: tests/conformance/test_conformance.py（50 个用例，独立 runner）+ tests/test_conformance_suite.py（接入 pytest：11 方法级 + 1 汇总，锁死 50 且零 FAIL/ERROR/SKIP）
- 脚本测试: tests/scripts/（YAML 定义的场景测试）
- Mock 策略: 引擎层测试用 Mock 传输层，不建真连接

## 当前开发重点
<!-- 每次开工前更新这里，AI 就知道上下文 -->
- [x] 接入未使用的 GUI 面板：SimPanel、PointEditor、CapturePanel、TrendChart、MultiStationPanel
- [x] 修复 SlaveView.get_point_editor 空引用、点表批量添加列表处理
- [x] 引擎层 _spawn 安全任务调度（保留引用 + 异常日志）
- [x] README 双语链接修复、补充 requirements.txt
- [x] 响应配置面板 config_changed 应用到 SlaveEngine（ResponseBehavior）
- [x] master↔slave 真连接端到端联调（tests/test_e2e_master_slave.py）
- [x] MultiStationManager 共享事件循环稳定性验证
- [x] 修复 slave/master/transport stop 时 wait_closed 挂起（加超时）
- [x] Web UI：apps/web_master + apps/web_slave 瘦入口，统一走 app.py `cli()`
- [x] 纯 web 形态：移除桌面壳 / `--no-shell` / web_lab 一键联调；浏览器自动打开
- [x] Web API：组召唤/复位/测试/读/参数/文件 + 点表 YAML/CSV/会话导出
- [x] PyInstaller 脚本 build/build_all.py（单文件 `iec104-tester`；双击默认同时启动主站+子站，单页工作台）
- [x] wrong_cot 注入落到 ASDU 构建（子站应答 COT 整体 +1，含 Web UI 开关）
- [x] 对端断开时 transport 未关闭：`_read_loop` 退出补 `close()`（修 FD 泄漏 + `server.stop()` 阻塞 2s）
- [x] 主站↔子站真机联合调试：修 SQ=1 非连续 IOA 错址（`_split_contiguous`）与召唤重复上送遥信
- [x] 命令联动（真机语义）：遥控执行后同 IOA 遥信变位并上送 SOE；遥调执行后同 IOA 遥测更新并上送
- [x] 召唤遥信按点表声明分流单点/双点（`M_SP_NA_1`/`M_DP_NA_1`），消除重复与类型错配、修状态 0 被漏
- [x] 修 Web UI 按钮全失效：`app.js` 未暴露 `$`/`$$`，两页内联脚本首句 ReferenceError（新增 Node 沙箱回归 `qa_verify/qa_webui_dom.mjs`）
- [x] 修主站点值不实时：WS 收到报文/事件后发 `"refresh"` 拉快照（节流 250ms），单元格就地修补不整表重建
- [x] 页面/静态资源加 `Cache-Control: no-cache`，避免前端修复被浏览器启发式缓存挡住
- [x] 修「断开/停止」点不了：按钮可用性改由服务端状态驱动（`status.started`），刷新页面后与后端保持一致
- [x] 修「按钮可点但没效果」：状态变更的空操作分支也必须广播事件（`bridge._notify_ui`），前端操作后立即 + 每 5s 兜底对齐状态
- [x] Web UI 改浅色工业风（ISA-101 高性能 HMI 范式）：点表全边框·统一左对齐·等宽数值、禁用态显式灰化、状态栏字段带标签
- [x] 全流程验收脚本 `tests/e2e/qa_full_flow.py`（12 项：复位→启动→系统命令→控制→参数文件→模拟→注入→点表→多客户端→前端→关停重连）
- [x] 修 S 帧 SS 字段 bit0 被置 1（`encode_s | 0x01`）：自测互通掩盖、真机收到即断开（`tests/test_apci_s_frame.py` 字节级断言）
- [x] 修 t1 超时后永不重连（`_on_timer_expired` 误用 `client.stop()`，改 `disconnect()`）
- [x] 主站点表导入（YAML/CSV/JSON，`/api/points/import` + UI「导入点表」按钮，与导出 CSV 回环兼容）
- [x] 初始化结束(M_EI_NA_1)联动：日志释义「当地电源合上」等；自动重 GI 可配置（`auto_gi_on_init_end`，默认关——实测部分真机收主站 I 帧即断开）
- [x] 真机功能测试脚本 `tests/e2e/qa_real_device.py`（对运行中的主站跑只读类功能矩阵）
- [x] 主站点位自学习（`auto_add_points` 默认开）：按报文解析结果自动补定义表点位（遥信/遥测/遥脉），解决"真机点位不在定义表导致界面无值"
- [x] 周期总召唤（`gi_interval`，默认 0=关；UI「周期总召(秒)」）：对"从不自发上送遥测、只有总召才回数据"的真机是必要手段（实测 20s 间隔 → 80 个遥测点 45s 内全刷新）
- [x] 结构化日志模块 `core/logging_manager.py`：分级/分类/来源，内存环形缓冲 + JSONL 会话文件（轮转）+ Python logging 桥 + Web「日志」面板（过滤/搜索/导出）
- [x] 协议类型覆盖补齐：**72/72 个已定义类型均可构造 + 可解码**（CP24 变体 8、继保事件 6、成组单点 2、无品质 2、位模式测试 1、对称性缺口 2）
- [x] 机制层补齐：T 试验位（编码/解码/子站回显/主站不入库）、读未知 IOA 回 COT=45、C_CD 按请求延时、主站累计量 CP24 变体、ASDU 长度上限强制
- [x] 参数命令主站侧状态跟踪（装载/激活两维：PENDING→OK/TERMINATED/REJECTED/TIMEOUT，记录 COT；`get_parameter_state` / `parameter_states` + REST `/api/master/param_state`、`/api/master/params`）
- [x] 升降命令（调节步）联动：点表新增步位置点类型（真机为 M_ST_NA_1 档位）建模，C_RC_NA_1 执行后联动更新档位点并上送（`tests/test_step_position.py`）
- [x] 多站管理器在 Web 会话关停时的资源清理（`stop()` 已无阻塞，仍缺显式回收路径）
- [x] 主站定义表双击值直接发命令（YK/YC/STEP 经确认弹窗下发；SBO/选择-执行不绕过）
- [x] 互操作语料库 + 回放回归：`tests/fixtures/frames/`（合成基线 golden + `real/` 真机目录），主站引擎逐帧回放断言点值
- [x] 解码器 fuzz/属性测试（Hypothesis）：APCI/ASDU 畸形输入只允许 `ValueError`；截断 ASDU 不再被静默吞掉（严格校验对象数量）
- [x] Windows CI 打包回归 + tag 发布流水线：onedir exe 真实启动冒烟；`v*` tag → 双平台 onefile + SHA256SUMS + GitHub Release
- [x] 性能/长稳基准：`tests/perf/`（解码吞吐、10 万点快照、**20 客户端并发约 2.9k 帧/秒**、主站↔子站环回 soak；默认 `-m "not perf"`；**2h soak 实跑通过：7200s / 34,765 GI / 内存 +0.64 MB**）
- [x] 一键诊断包：`GET /api/diagnostics/export`（状态/配置脱敏/日志/报文/事件/点表/历史统计）+ 状态页按钮
- [x] 一键环回 Demo：`python app.py --demo`（子站+主站独立子进程、自动监听/连接/总召，Ctrl+C 统一回收）
- [x] 分支覆盖率门禁（CI `--cov-branch`：core 92.0% + webui 89%，合并 91.3%，门禁 91）+ 协议层变异冒烟 `tools/mutation_smoke.py`（12/12 killed）
- [x] 历史库查询 UI：`GET /api/history/{stats,data,frames,export}`（§2.11/§4.9）+ Web「历史」页（数据/报文双页签，时间/类型/IOA/方向过滤，CSV 导出；未启用提示）；`tests/test_webui_history_endpoints.py` 4 例 + `HistoryPage.test.tsx` 3 例；全量 1288 passed
- [x] 网络异常模拟接入 Web UI：`/api/simulation`（GET/POST + reset/disconnect，§2.12/§4.10）+ 状态页卡片（预设/自定义/手动断线/统计）；**核心修复**：`SimulationManager.install` 原二次包装 raw 回调会覆盖代理 `_original_rx`，导致 RX 帧绕过协议处理——改为在传输层回调（`_client/_server._on_frame`）拦截并提供 `uninstall_from_engine` 精确恢复；新增 4 后端 + 3 前端用例；全量 1293 passed
- [x] Web 访问安全（B7）：`--http-host`（默认 127.0.0.1）+ `--auth-token`（或 `IEC104_AUTH_TOKEN`）；令牌保护 `/api/*` 与 `/ws`（Bearer / X-Auth-Token / `?token=`），`GET /api/auth` 公开探测；前端 AuthGate 令牌输入 + URL `?token=` 导入；非回环监听且无令牌时启动告警；新增 4 后端 + 2 前端用例；全量 1297 passed
- [x] 一致性套件接入 pytest：`tests/test_conformance_suite.py` 按套件 `_test_*` 方法参数化（失败输出具体 case id）+ 汇总用例锁死 42 case/零 FAIL/ERROR/SKIP；独立 runner 保留；全量 1308 passed
- [x] 分支覆盖率 88.86%→92.08%：补 `scheduler`（47%→97%）、`data_store`（83.6%→95%）、`master_session`（77.5%→92%）、`multi_station`（80.6%→98%）及协议层零散分支（types/asdu 负数编码、短报文异常、时标变体、自定义类型校验、APDU 编解码）；新增 73 例；CI 门禁 88→91（保留约 1 点抖动余量）；全量 1381 passed
- [x] 全流程验收进 CI：`e2e-full-flow` job 内拉起主站(8765)/子站(8766)/IEC 24040，等就绪后跑 `tests/e2e/qa_full_flow.py` 12 阶段（本机实测 12/12 通过、exit 0），退出回收服务，失败上传两端日志；历史库以 `--no-history` 关闭
- [x] 前端 i18n（阶段一）：零依赖 `src/i18n`（zh/en 词典 + `t()`/`useT()`/`tNow()`）、头部「中 / EN」切换（localStorage 记忆、antd ConfigProvider locale 联动）；已覆盖外壳/认证/状态/日志/历史/模拟卡片/共享列宽/运行时告警；`npm run i18n:inventory` 当时剩余 20 文件/535 行（工作台内部，T40 已完成并清零）；新增 5 用例（字典键对齐 + 英文渲染）；前端 123 passed
- [x] 前端 i18n（阶段二，完成）：主站（CommandPanel/PointCommandDialog/ConnectionPanel/MasterPage/TrendChart）、子站（SlavePage/SlaveConnectionPanel/ManualSetPanel/ResponsePanel/SimulationPanel/TestInjectionPanel）、多站（MultiPage/StationCard/MultiStatusView/stationDraft）、报文解析与查看器（lib/frame.ts 双语对照表 + FrameViewer/FrameTranslatePopover）、共享点表（PointsTable/PointsTools）全部迁入词典；**`npm run i18n:inventory` = 0 文件 / 0 行**；zh 文案逐字保留，前端 123 passed / typecheck 通过
- [x] 文件传输真机核实准备（C4，无真机）：`docs/file_transfer_open_items.md`（5 项开放清单：NOF 语义/SCQ 组合/WITH_DEACT/多节/FRQ-SRQ，含验证步骤、判定标准、回填模板）+ `tests/e2e/qa_file_transfer_probe.py`（只读探针：默认目录召唤，结构化打印 NOF/LOF/NOS/LSQ/CHS/FRQ/SRQ/AFQ；本机对模拟器实测跑通）；user_guide §11 与 FLS 文档已互链；**2026-11-07 第三方 lib60870-C v2.4.1 实测回填 5 项（NOF/SCQ/DEACT/多节/FRQ-SRQ），并修复 3 项互操作问题（122/COT13、SCQ=6 节流程、停发 128/129）；默认代码复测 800B 多节文件接收完成；真机窗口仍待复测**
- [x] D1 WebUI 覆盖率门禁：全量覆盖 `webui/` 从 77.1% → 89%（server 92% / session 97% / capture 75% / testcenter 79%）；新增 HTTP 边界、会话分发、抓包、测试中心、安全头等用例；CI 增加独立 `coverage report --include="webui/*" --fail-under=85`
- [x] D2 前端覆盖率：`@vitest/coverage-v8` + `npm run test:coverage`（阈值 78/78/80/55，当前 lines 80.1% / branches 83.3% / functions 56.5%）；CI 上传 coverage artifact
- [x] D3 e2e 补口：历史查询、网络模拟、AuthGate、中英切换 4 条 Playwright 用例（本地 22/22）
- [x] D4 CI 工程化：concurrency 取消旧 run、Dependabot（pip/npm/actions）、Python 3.14 矩阵、夜间 perf workflow、PR 阶段 Linux onefile dry-run、coverage XML artifact
- [x] D5 版本/文档一致性：`core/version.py` 单一版本源 + 三处一致性测试；历史文档的 TLS/冗余/i18n 清单表述加注当前状态
- [x] D6 前端依赖大版本升级（v1.3.0）：React 19/Ant Design 6/TypeScript 7/Vite 8/Vitest 5/ECharts 6 等 17 项（PR #6）；适配 TS7 去 `baseUrl`、antd6 角色/aria 选择器；Vitest5 覆盖率口径重基线（55/58/50/53）；`actions/download-artifact` 7→8（PR #5）；合并后 master CI 10/10 绿
- [x] D7 antd 6 弃用告警清零 + C4 回归：`Alert message→title`、`Space direction→orientation`、`InputNumber addonAfter→suffix`、`Modal maskClosable→mask.closable`、`Statistic valueStyle→styles.content`；前端测试 antd 告警 0、128 passed、Playwright 22/22；lib60870 第三方文件传输 800B/2 节回归通过（真机仍待）
- [x] E1 Web 测试中心：`/api/tests/*`（脚本列表/运行/停止/状态/报告下载）+「自动化测试」页；子进程隔离、实时日志、50 用例脚本可选；4 后端 + 2 前端用例
- [x] E2 报文录制/回放进 Web：`/api/capture/*`（录制启停/暂停/文件/导出 pcap/加载/回放/单步）+「报文抓包」页；5 后端 + 2 前端用例
- [x] E3 冗余双通道进 Web：`POST /api/master/start` 支持 `redundancy`，状态返回活动通道/主备在线/切换次数；连接面板可配置；新增后端 12 + 前端 1 用例
- [x] E4 Web HTTPS + 安全头：`--web-tls-cert/--web-tls-key`，CSP / X-Frame-Options / Referrer-Policy / Permissions-Policy；4 个安全头/证书用例
- [x] E5 发布体验：`--version`、README 4 张界面截图、`SECURITY.md`、`CHANGELOG.md`
- [x] F2 一致性负例：新增 8 个畸形 APCI/ASDU 用例（42→50），独立 runner 与 pytest 汇总同步锁死
- [x] 修复报文查看器悬停翻译恒显示「翻译失败」：后端契约 §2.9 返回扁平 `{ok, format, segments}`，前端却读取 `r.translation`（自 `810c340` 上线即存在）；前端对齐扁平结构、单测改为真实响应形态，新增 `tests/e2e/specs/frame-translate.spec.ts`（真实后端 + 浏览器悬停）回归；契约端点测试锁定响应键集；前端 128 passed / Playwright 23/23
- [x] API 响应契约升级为可执行单一源：`api/contract.ts` 零依赖 schema DSL（失败抛 `ApiContractError` 带 JSON 路径）+ `api/contracts.ts` 覆盖全部 JSON 端点 + `apiGet/apiPost/apiPostText` 每次响应强制校验 + `ContractKeyChecks` 编译期比对 schema 字段集与 `types.ts` 接口 + Playwright `api-contract.spec.ts`（真实后端 × 同一 schema：主站/子站只读矩阵、幂等命令、连接+总召运行态）；顺带修正 `SessionExport` 信封形状、`HistoryStats` 未启用零值、参数状态未连接错误响应；前端 136 passed / Playwright 27/27 / 后端 1545 passed
- [x] 单文件发布 + 单页工作台（单进程双角色）：一个 `iec104-tester` 双击默认同时启动主站+子站，**一个进程、一个 8765 端口**；左侧「主站工作台 / 子站工作台」两个菜单在同一 SPA 内切换，子站 API/WS 挂 `/slave/api`、`/slave/ws`，页面原生渲染（无 iframe/双滚动条）；`--mode master|slave|both` 仍可单角色运行；`--mode both` 自动按角色拆分历史库，两个 `EngineBridge` 共享事件循环但引擎/日志隔离；`MasterPage`/`SlavePage` 共用 `WorkbenchShell` 骨架（flex 不换行：桌面端点表自适应 + 右侧面板固定 400/420px，避免面板被宽表挤到下一行）；查询键按角色隔离（`['points', role]` 等），切换主站/子站不再清空缓存、切回不重新拉点表；后端 1551 passed / 前端 138 passed / Playwright 28/28；本机单 exe 实测 both 单进程单端口与 master/slave 单角色
- [x] 工作台两处体验缺陷修复：① 点表提示文案（「单击行以选中并手动置数」等）从 Card 标题区移到表体工具行——标题区被右侧工具挤压后长文案只剩半句；Playwright 断言 `points-hint` 完整可见（`scrollWidth<=clientWidth`）。② 模拟控制支持 **YX/YC 独立开启**（只模拟遥信或只模拟遥测）：`POST /api/slave/sim` 新增 `yx_enabled`/`yc_enabled`（默认均 true、至少一项；关闭类型不要求 selected ioas），模拟循环跳过关闭类型、不产生该类报文；`GET /api/status` 回显 `simulation_yx`/`simulation_yc` 供刷新后回填；UI 两个开关并禁用对应参数；后端新增 5 例、前端新增 4 例，Playwright 覆盖只开 YX 的真实请求体
- [x] UI 自动巡检 + 静态路由一致性（第一类可自动发现问题）：新增 `ui-audit.spec.ts`（8 菜单页 × 3 视口 × 中英/深色 + 主/子站页签 + 命令面板折叠区全展开 + 单角色 8765/8766），自动检查文本裁切（scrollWidth）、页面横向滚动、控件出视口、console error/warn、API 4xx/5xx、错误 Alert、空白页签、漏出 i18n key，并探活导出/下载链接；巡检发现并修复：① 英文/窄屏下点表标题被 Card `extra` 工具条压到 7px、工具被裁 → 工具条移入表体首行自动换行；② 英文「手动置数」类型标签超宽 → 短标签；③ 点表 YAML/CSV/会话 JSON 导出缺 `Content-Disposition: attachment`（浏览器内联显示而非下载）；④ 合并模式下子站「报文抓包」页会列出/可下载主站录制 → `CaptureService` 按角色前缀隔离（无前缀手工文件双方可见）。新增 `tests/test_frontend_routes.py`（前端 API 方法+路径 ↔ 后端路由）；`npm run i18n:inventory` 恢复 0（契约层诊断文案标记 `i18n-ignore-file`）；前端 142 passed、后端 1559 passed、Playwright 33/33、ruff 通过
- [x] 配色对比度自动化 + WCAG AA 主色：新增 `ui-contrast.spec.ts`（8 页 × 浅/深主题 + 选中行，祖先 alpha 合成有效背景，WCAG 2.1 对比度，普通 4.5:1 / 大字 3:1，含 `::placeholder`；3488 处文本 **0 硬失败 / 0 建议项**，全部 AA；默认 <3:1 门禁，`CONTRAST_REPORT=1` 仅报告）；主色 `#13c2c2`（白底/白字双向仅 ~2.2:1）→ `#0a7575`（~5.5:1），亮青保留为 `colorInfo`（深色品牌字/信息色）；显式配置浅/深选中菜单、Tabs/Pagination 强调色，success/warning/error 标签前景/背景 token；placeholder、次要/三级文字、Switch 轨道、空表占位文字提升；不可访问预设标签 gold/cyan/purple/green 改为 success/blue/default（帧方向 发送 success / 接收 blue，格式 I/S/U = blue/success/default）；6 处硬编码颜色改 token，新增 `test_frontend_style_tokens.py` 静态门禁；前端 142 passed、后端 1560 passed、Playwright 34/34、ruff 通过
- [x] 非文本对比 + 视觉回归基线：新增 `ui-nontext-contrast.spec.ts`（WCAG 1.4.11 / 2.4.7）：控件边框、Switch 轨道、纯图标按钮、键盘 Tab 焦点环与相邻背景 ≥3:1；702 处 0 硬失败（禁用控件豁免）。修复 `colorBorder`（浅 #8c8c8c / 深 #6b6b6b）、Button `defaultBorderColor`、深色选中 Switch 轨道 #0b7f7f、全局 `:focus-visible` 焦点环（浅 #0a7575 / 深 #5cdbd3）。新增 `visual.spec.ts`：专用单角色服务 8768（无引擎/无帧/无历史），浅/深主站工作台 + 状态总览整页基线；按平台分目录（已提交 win32 基线，`windows-build` CI job 自动跑视觉回归；无基线平台自动 skip，`VISUAL_UPDATE=1 --update-snapshots` 生成新平台基线）；Windows 全量 Playwright **38/38 passed**（Linux 35 passed + 3 skipped）
- [x] 界面套件共存（同地址即时切换）：根入口与 UI 解耦（`src/main.tsx` 常驻 QueryClient/WS/契约协商，`PfRoot`/`ClassicRoot`/`CarbonRoot` 只做 UI），**PatternFly / 经典版（antd 6，v1.3.1 冻结）/ Carbon** 三套在 `/app/` 同一文档内切换——不刷新、不改 URL、连接与页面保持，深浅主题/语言跟随；`useKitCss` 保证 `<head>` 同时只有当前套件的全局样式表（PF 逐组件 CSS 置空、Carbon styles.css 含全局 reset 同样按需挂载），经典版数据层用 re-export shim 指向共享层。右下角 UI 圆钮切换，`?kit=pf|classic|carbon` + localStorage。e2e 41 passed（`ui-kit.spec.ts` 3 条含 Carbon）、前端单测 133 passed、视觉基线重拍、exe 重建（19.0 MB；Carbon 的 IBM Plex 字体本地化进包）。详见 `docs/ui_kits.md`
- [x] T71 反馈批次：**Carbon 设为默认套件**（`resolveInitialKit`：`?kit=` → localStorage → `carbon`，存量 pf 偏好视为未设置）；三套外壳头部统一收敛为**只留中英切换 + 深浅图标切换**（Sun/Moon 类图标，不再用文字），状态类信息只在页面内呈现；主站工作台**选中行与趋势 watch 移入共享 `uiStore`**（切菜单/切套件回来不丢），且选中行按 key 从点表缓存现取——命令面板「当前值」继续跟随 WS 刷新（不回退到快照冻结，与经典版同一 bug 修复）；**趋势图「没有曲线」根因修复**：三套件趋势图的容器 div 是条件渲染（无 watch 时占位），一次性 init effect 挂载时读到空 ref 即永久 bail，之后「加入趋势」也不会建图——改为回调 ref，容器每次出现都重挂 ResizeObserver 并重试 init（隐藏面板 0×0 时跳过，可见后再创建）；「加入趋势」并立即以当前值写入首采样（连接空闲也有曲线起点）。e2e `ui-kit.spec.ts` 增至 5 条（含「加入趋势后切页返回，选中与曲线保留」）；修正 2 处 e2e 自身问题：@carbon/react 1.120 无 `--selected` 修饰类改语义选择器、Carbon↔PF 互切用例改等 `dataset.kit` 完成信号（原用 PF/Carbon 同名 point-row 判断切换完成，属竞态）
- [x] T72 SCD/CID/ICD 点表导入（IEC 61850 → 104）：`core/data/scd_import.py` 双路径映射——**IEC 61850-80-1 精确映射优先**（`Private/Address(casdu,ioa,ti)`，ti→类别按本仓 `TypeID` 对表且 ti 优先于 CDC），无映射按 DOType `cdc` 推断 + IOA 自动分区分配；iterparse 流式（数十 MB 可用）、SDI/DAI/BDA 嵌套路径保留；多公共地址取众数+明细告警（可显式指定）；IOA 冲突/越界/不支持 ti 全部告警。`POST /api/scd/preview` 无副作用预览（契约 §2.4a + 前端编译期键集比对），Carbon/PF 子站工作台「导入」按钮：SCD 预览（计数+告警+可编辑 YAML）→ 应用走既有导入端点（经典版按冻结承诺不加）。后端 16 项 pytest + 真实厂商 SCD（58KB/65 信号）实弹通过；Dependabot 残留分支清理（PR #5 核实 MERGED 后删除）
- [x] T73 透明桥/旁路监听：`--mode bridge --no-gui`（headless 现场可用）——真实主站 ↔ 测试器 ↔ 真实子站字节级透传（转发先行、解析纯旁路），双向 APCI 切帧（半包缓存/脏字节重同步）+ 逐帧摘要日志（方向 + APCI/ASDU），`--capture-file` 复用 PacketRecorder（.json/.pcap）；多客户端独立上游连接；绑定失败人话报错。`core/engine/tcp_bridge.py` 内核 11 项 pytest（含真主站↔桥↔真子站全链路：STARTDT/GI 往返与透传内容校验、capture 落盘链路）+ CLI 实弹
- [x] T75 测试报告导出：状态总览页「导出测试报告」按钮（Carbon/PF）→ `GET /api/export/report.html`（attachment 自包含单文件 HTML，浏览器打印即 PDF）：会话信息 + 帧统计聚合 + 帧证据逐帧 APCI/ASDU 解码（脏帧回退）+ 事件表；`webui/report.py` 纯函数零依赖，pytest 6 项
- [x] T76 压测编排：测试中心页压测卡（Carbon/PF，仅双角色部署显示）→ `POST /api/loadtest/start|stop` + `GET /api/loadtest/status`：子站按目标速率（1~10000 eps）自发 YC/YX，主站 ConnectionStats 差分统计吞吐（avg_eps/avg_fps/errors）；编排层不改引擎（复用 slave_set_* 公开路径）；仅 both 模式挂载；真引擎端到端 pytest 3 项（1.5s@80eps 吞吐差分可见）
- [x] T74 桥接 Web UI 页（bridge 角色三件套）：① `EngineBridge` 增 **bridge 角色**（无引擎；`_BridgeRoleSessionStub` 把全部引擎操作统一拒绝为干净错误 dict——避免 20 处散落守卫漏一处即 500）+ `start_bridge/stop_bridge` + status 携带 `bridge_stats/bridge_cfg` + 帧节流（1Hz）广播状态刷新；② server：`POST /api/bridge/start|stop`，**引擎专属路由按角色跳过**（master/slave/multi 启停、点表写入、网络模拟在桥应用上 404，普通 UI 流量到不了），app.py `--mode bridge` 默认 Web 模式（8767；`--no-gui` 保留 T73 headless 形态）；③ 前端（Carbon/PF，经典版按冻结承诺不加）：`Role/PageKey` 增 bridge、菜单按角色过滤、**桥接观察页**（配置启停 + KvList 统计 + 复用 FrameViewer 的 WS 实时帧），`ok:false` 业务错误显形（端口被占不再静默）；④ e2e `bridge.spec.ts`：第 4 个 webServer（8769）+ 用例内 echo 上游 + node:net STARTDT 回环探针（本机部分端口段 bind 10048 → 测试监听口改 OS 派空闲口）。验证：后端 15 项桥 Web pytest；UI 端到端「启动→透传回环→帧视图/统计→停止」通过

### TODO（暂缓，等待外部条件）

- [ ] **C4 真机复测**：真机窗口到位后，按 [`docs/file_transfer_open_items.md`](docs/file_transfer_open_items.md) 的 5 项清单（NOF/SCQ/DEACT/多节/FRQ-SRQ）逐项复测并回填。已完成两轮 lib60870-C v2.4.1 第三方回归（2026-11-07，含 v1.3.0 复测），第三方结论不能替代真机。

## 双应用入口（纯 Web UI）

| 产品 | 入口 | 端口默认 |
|------|------|----------|
| 单文件发布 | `iec104-tester`（双击默认 both：一个进程/8765 端口，左侧两个角色菜单） | 8765 |
| IEC104 主站 | `python apps/web_master.py`（= `python app.py --mode master`） | 8765 |
| IEC104 子站 | `python apps/web_slave.py`（= `python app.py --mode slave`） | 8766 |

联调：`python app.py`（默认 both）单进程/单端口打开一个工作台，左侧菜单切换主站/子站；也可用 `--mode master` / `--mode slave` 分开启动。

架构：`webui/bridge.py` 引擎桥 + `webui/server.py` aiohttp REST/WS + `webui/frontend`（React/Vite，产物 `webui/static/app`），浏览器为唯一 UI（无桌面壳）。
共享：`core/` 引擎。README 与代码对齐：主站含组召唤/复位/测试/读/参数/文件与点表导出；子站含响应注入与模拟。多站/录制/网络模拟见 CLI。

界面：默认 **Carbon**；同一地址 `/app/` 内可即时切到 **PatternFly 6** 或 **经典版**（antd 6，v1.3.1 界面冻结），
右下角 UI 圆钮切换（`?kit=pf|classic|carbon`，选择持久化，页面/连接/主题/语言保持；
存量 pf 偏好视为未设置，跟随新默认）。
架构与隔离方式见 [`docs/ui_kits.md`](docs/ui_kits.md)。
