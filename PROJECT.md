# IEC 60870-5-104 Tester

## 项目用途
IEC 60870-5-104 协议测试工具，支持主站/子站模拟、报文录制回放、
网络异常模拟、一致性测试。面向电力系统 SCADA 调试和测试场景。

## 技术栈
Python 3.11+, Web UI (aiohttp + HTML/CSS), asyncio, struct（协议编解码）

## 架构分层
入口层: app.py（统一 Web 入口 + headless CLI） / apps/web_master.py / apps/web_slave.py（瘦入口） / run_tests.py / capture_tool.py / sim_tool.py
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
| core/protocol/types.py | 59 种 TypeID 枚举定义 | 低 |
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

## 关键设计约定

### 协议层
- APCI: I 格式（信息）、S 格式（确认）、U 格式（控制）
- ASDU 结构: TypeID(1B) + SQ(1B) + Cause(2B) + CommonAddr(2B) + IOBs + 数据体
- 59 种 TypeID 在 types.py 用枚举定义，asdu.py 按 TypeID 分发解析
- k/w 流控: k=12（未确认上限）, w=8（确认间隔）

### 编码风格
- 协议层: 纯同步 struct.pack/unpack，无 async，无 GUI 依赖
- 引擎层: asyncio，通过 core/transport 管理 TCP 连接
- GUI 层已移除（原桌面框架）；界面为 webui/（HTML/CSS + aiohttp），纯 web 形态——浏览器是唯一 UI，无桌面壳
- 入口层 app.py 提供统一 Web 入口 `run_web()`：启动服务后台线程轮询端口就绪后再打开浏览器；`--no-browser` 关闭自动打开
- 后台任务: 引擎层统一用 `_spawn()` 创建，保留任务引用并记录异常
- 响应注入: `ResponseBehavior` 承载延迟/丢帧/损坏/不响应/品质/错误 COT；错误 COT 由 `SlaveEngine._reply_cot()` 统一处理（应答 COT +1，配置项 `errors.wrong_cot`）
- 真机语义优先: 功能语义有歧义时按真实装置行为实现（用户明确要求）。已落地：遥控→同 IOA 遥信变位 + SOE 上送、遥调→同 IOA 遥测更新 + 上送（`SlaveEngine._reflect_command_result`）；召唤按点表声明分流单点/双点
- 前端约定: `app.js` 必须把 `$`/`$$` 暴露到 window（页面内联脚本直接用裸 `$` 绑事件，漏暴露会静默导致所有按钮失效）；点值刷新走 WS `"refresh"` 协议 + 节流，不做整表重建
- 按钮状态单一来源: 顶部「连接/断开」「启动监听/停止」的 `disabled` 只由**服务端状态快照**（`status.started`）驱动，不得只靠点击后的返回码 —— 否则页面刷新后按钮与真实状态不一致，用户"点不了"
- UI 风格: 浅色工业风（ISA-101 高性能 HMI）——中性浅灰底、颜色只用于状态与类型标签、扁平无装饰、禁用态显式灰化、字段带标签；点表全边框 + 表头/单元格统一左对齐 + 数值等宽
- 状态一致性: 任何会改变服务端状态的分支（含"已是该状态"的空操作）都必须广播事件，前端据此重新对齐；前端另加 5s 兜底轮询，保证最终一致
- 帧格式必须字节级对照标准: APCICodec 编码端曾把 S 帧 SS 的 bit0 置 1，自家解码 `>> 1` 掩掉后互通自洽，真机按标准校验直接断开。编码与解码要**独立对照标准**，不能只对拍
- 真机兼容性: 部分装置每次连接都发 EI 并高频推流，收到主站 I 帧会断开——自动重 GI 默认关（`auto_gi_on_init_end`）；对这类装置用 `tests/e2e/qa_real_device.py` 做只读验证
- IOA 一律按**十进制**表示与存储（点表 YAML/界面/实时库）；标准不规定遥信遥测的 IOA 范围，地址规划是项目约定——写点表时注意别把十六进制字面量当十进制（0x4001=16385≠4001）
- 遥测不刷新先查**设备是否自发上送**：实测有真机只回总召唤数据（静默 70s 零遥测帧），此时用周期总召，不要误判为主站解析/更新问题
- 协议完整性: `TypeID` 枚举里**每个类型都必须同时有解码注册与 ASDUBuilder 构造器**（否则就是"能解不能发"的半实现）；新增类型时用 `tests/test_protocol_type_coverage.py` 的护栏用例兜底

### 测试
- 单元测试: tests/test_*.py（协议各层）
- 一致性测试: tests/conformance/test_conformance.py（42 个用例）
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
- [x] PyInstaller 脚本 build/build_all.py（iec104-master / iec104-slave）
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
- [ ] 升降命令（调节步）不做联动：点表未建模步位置点（真机为 M_ST_NA_1 档位），需要时应新增点类型
- [x] 多站管理器在 Web 会话关停时的资源清理（`stop()` 已无阻塞，仍缺显式回收路径）
- [x] 主站定义表双击值直接发命令（YK/YC/STEP 经确认弹窗下发；SBO/选择-执行不绕过）

## 双应用入口（纯 Web UI）

| 产品 | 入口 | 端口默认 |
|------|------|----------|
| IEC104 主站 | `python apps/web_master.py`（= `python app.py --mode master`） | 8765 |
| IEC104 子站 | `python apps/web_slave.py`（= `python app.py --mode slave`） | 8766 |

联调：开两个终端分别执行 `python app.py --mode master` / `python app.py --mode slave`（或对应瘦入口），浏览器中两个页面操作。

架构：`webui/bridge.py` 引擎桥 + `webui/server.py` aiohttp REST/WS + `webui/static` 工业深色页，浏览器为唯一 UI（无桌面壳）。
共享：`core/` 引擎。README 与代码对齐：主站含组召唤/复位/测试/读/参数/文件与点表导出；子站含响应注入与模拟。多站/录制/网络模拟见 CLI。
