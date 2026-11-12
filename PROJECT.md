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
- 单元测试: tests/test_*.py（**1667 例**；`tests/perf/` 由 `-m "not perf"` 默认排除）
- 协议 fuzz: tests/test_protocol_fuzz.py（Hypothesis；解码器只允许 `ValueError`）
- 互操作回放: tests/test_frame_corpus_replay.py + tests/fixtures/frames/（golden + MasterEngine 回放）
- 性能/长稳: `pytest tests/ -m perf`（解码吞吐 / 10 万点快照 / 环回 soak，时长由 `IEC104_SOAK_SECONDS` 控制）
- 变异冒烟: `python tools/mutation_smoke.py`（协议层 12 个高价值变异必须全部被杀死）
- 一致性测试: tests/conformance/test_conformance.py（50 个用例，独立 runner）+ tests/test_conformance_suite.py（接入 pytest：11 方法级 + 1 汇总，锁死 50 且零 FAIL/ERROR/SKIP）
- 脚本测试: tests/scripts/（YAML 定义的场景测试）
- Mock 策略: 引擎层测试用 Mock 传输层，不建真连接

## 当前开发重点
<!-- 每次开工前更新这里，AI 就知道上下文 -->

### v1.9.0（已发布 `95933a7`，2026-11-10；2026-11-09 选定质量门禁收口 A+B+D，2026-11-10 真机联调后追加：T90 收口 + T93 值守告警（吸收 T91）+ T94 连接医生）

> 依据：v1.8.0 已发布（`76cdb4f`，2026-11-09），T72~T87 全部交付；剩余待办只有外部阻塞项
> （T50 真机窗口、SCD 私有映射适配需厂商样本）。候选比选与成本/验收阈值见
> [`docs/architecture_plan.md`](docs/architecture_plan.md)「2026-11-09 候选方向比选」。
> 本批**不新增功能面**，只补门禁与端到端覆盖。

- [x] **T88 文档与发布收口**（P0，0.5~1 人日）：README 按已发布基线重写——徽章 `version-1.8.0` / `Tests-1655`、删除「🚧 开发中（v1.7.0 之后，尚未发版）」小节并把 T85/T86/T87 提为正式特性（桥接页增「网络条件注入」描述）；**英文版 `README_eng.md` 同步收口**（此前停在 1545 例 / 88.82% 覆盖 / 「ISA-101 industrial style」，缺桥/SCD/三套 UI/压测/报告，已补齐）；新 logo 三文件入库（`resources/logo.svg` 760×200 wordmark、`resources/icon.svg` 改版、`docs/pr-assets/logo-preview.png`）；`app.py` 三处帮助文本纠偏（`--mode bridge` 曾写「headless」，实为默认 Web 桥接页 8767；`--http-port` 默认补 8767）；新增守卫用例 `tests/test_version_consistency.py::test_release_docs_match_version`（README 徽章 / CHANGELOG 首条 ↔ 版本源，已验证能抓漂移）。**验收**：全套 **1655 passed / 4 deselected**、ruff 全仓通过、双语徽章一致、`git status` 无残留
- [x] **T89 默认套件 Carbon 纳入 UI 门禁**（P1，2~3 人日）：新增 `tests/e2e/specs/kitProfiles.ts`（套件档案：导航/当前项/折叠开关 + 巡检选择器两套件**并集**；`GATE_KITS` 由 `E2E_KITS` 决定，默认 `pf,carbon`），`helpers.ts` 的 `appUrl(base, hash, kit)` 增套件维度，三项页级门禁（`ui-audit` / `ui-contrast` / `ui-nontext-contrast`）逐套件参数化（**Playwright 46 → 50 例**，页面矩阵翻倍；计划里写的「~85 例」是错估，实际是按套件复制 4 例），并用 `dataset.kit` 断言 `?kit=` 真的生效（防「静默跑错界面」）；**门禁自身 8 处度量缺陷按实测修正**（Carbon 焦点是内嵌 box-shadow 环 / 负 offset outline / 画在子元素与伪元素上 / 焦点色有 0.1s 过渡 / 静态边框不是焦点环 / `outline-style:auto` 是浏览器默认环 / `:focus-visible=false` 按 WCAG 2.4.7 不适用 / 1~2px 屏幕阅读器专用盒子不是裁切）；**抓到并修好 Carbon 三类真缺陷**：占位符 2.56:1（规范 §4.4 要 ≥3:1）、空值破折号与 12px 提示文字 2.91~4.16:1（63 处内联 opacity → token 色，24 个文件）、头部品牌链接无可见焦点环。**验收**：`E2E_KITS=carbon` 与默认全量 **50 passed**；Carbon 文本对比 4273 处 / 非文本 288 处 / 8 页×3 视口×中英深浅 **0 硬失败 · 0 建议项 · 0 裁切 · 0 横向滚动 · 0 console error**；PF 回归 0 硬失败；前端 133、style-token/路由门禁、ruff 全绿；`webui/static/app` 已重建。**遗留（非本轮引入）**：PF 6 的控件边框画在伪元素/`box-shadow` 上，非文本门禁的「边框」段对 PF **0 命中**（Carbon 10 命中）→ PF 控件边界对比度实际未被覆盖，已记入 T91 之后的候选
- [x] **T92 真机联调批次：simulator4 外部互操作 + t1 隐式确认修复 + 趋势图验证（2026-11-10）**：用户用第三方「simulator4.exe」（监听 127.0.0.1:24040）做真机验收，反馈「无法连接」「趋势图看不到」。**实测结论**：① 主站对真机连接/STARTDT/GI/对时/读/设点全部走通（ACTCON/ACTTERM 实证）；② **发现并修复我方标准缺陷**——I 帧的 N(R) 是隐式确认（§5.3.3），引擎原来只认 S 帧、不停 t1 → `process_rx_i_frame_ack` 改为返回「确认窗口是否推进」，主/子站会话在推进时停 t1（回归用例 `test_i_frame_implicit_ack_stops_t1`：假子站只回 N(R)=1 的 I 帧从不发 S 帧，t1 不得超时）；③ **对端缺陷取证**：simulator4 从不确认我方 I 帧（0 个 S 帧、N(R) 恒 0，命令回显带非标 COT=47）→ 我方按标准 t1(15s) 超时断链并自动重连——监测流不受影响，**每发一条命令后 ~15s 链路重建一次**，属对端不合规；④ **趋势图验证通过**（像素级）：对真机自动学习的「遥测16385」加入趋势，曲线区 956 曲线色像素、截图为证——「看不到」的根因是连接断（②修复前每条命令都断链）+ 选中了不变化的演示点（真机 IOA 在 16385+，演示表 YC_0001=IOA 1001 永远 0.00）；⑤ 新增**独立 104 主站验收工具** `tools/qa_independent_master.py`（裸 socket 按标准手写，不走本项目引擎）——对子站 STARTDT/GI/80 点读取 **PASS**，UI 手动置数（type36/COT=3）与品质注入开关对外部客户端实时可见，UI 客户端列表正确显示外部客户端；⑥ 新增像素级趋势回归 `trend-live.spec.ts`（曲线区 >20 曲线色像素）+ 单采样态提示 `trend.waiting`（Carbon/PF，i18n）。**验证**：后端 **1656 passed**、e2e **51 passed**、前端 133、ruff/i18n 0 全绿。已知限制：simulator4 的 N(R) 恒 0 属对端缺陷，本项目侧按标准只能 t1 断链，无法代为修复
- [x] **T90 v1.8.0 新特性 e2e 补齐**（P1，3~4 人日；2026-11-10 交付 `4e178a9`：`tests/e2e/specs/v19-features.spec.ts`）：压测卡（1 连接 × 1s@50eps，含结束态冻结回归）/ 桥条件注入卡（丢帧 100% 仍见干扰前原始帧）/ 合规违规列表（序号跳变 → 违规行 +1）/ 时钟偏差测量 / 报告结论横幅 + 嵌曲线导出，共 5 条（复用 `bridge.spec.ts`「用例内 echo 上游 + OS 派空闲口」范式）。**验收**：5 条在 PF 与 Carbon 下均绿、无 console error、无 4xx/5xx
- [x] **T91 点表陈旧（stale）态**（P2，1.5~2 人日；**2026-11-10 决定并入 T93 值守告警，已随 T93 交付 `15a00be`**——陈旧即「死值」规则，数据层前提与 UI 标记一并实现）：`core/data/data_store.py` 五个数据类补 `last_update_time`（wall clock，毫秒；**不能复用 `last_change_time`**——只在值变化时写，恒定值周期上送会被误判陈旧）→ `/api/points` 每行带 `ts` → 三套件点表按阈值（默认 60s）标灰 + 图标 + tooltip（契约 `pointSchema` 增键，满足编译期键集比对）。**验收**：停更 60s 出现陈旧标记、恢复上送即消失；同步 `docs/design_guidelines.md` 附录 A 该项 ⚠→✓
- [x] **T93 值守告警引擎**（P1，3~4 人日；吸收 T91；2026-11-10 交付 `15a00be`）：让工具脱离盯屏值守——四类规则（评估点值快照与连接状态）：① 限值越限（YC 超出点表已有 `min_value`/`max_value`）；② 死值/陈旧（最后更新超阈值，默认 60s 可配，即原 T91）；③ 突变（相邻两次更新的变化幅度超阈）；④ 通信中断（state≠Running 或 rx 停止 N 秒，默认 10s）。数据层前提同原 T91：`data_store` 各数据类补 `last_update_time`（wall clock 毫秒；**不能复用只在值变化时写的 `last_change_time`**，恒定值周期上送会被误判陈旧）。告警生命周期 active→ack→clear + 去抖（连续 N 次评估才触发）+ 历史入库；`GET /api/alarms[/history]` + WS `alarm` 事件（契约 §2.x + 前端 schema 编译期键集比对）；UI（Carbon/PF）状态页告警卡（激活列表 + 确认 + 可选声音）+ 点表陈旧标记（`/api/points` 带最后更新时间，三套件灰化+图标，阈值与告警一致）；告警历史段自动进测试报告。**验收**：四类规则各有一条真机/注入触发证据（超限用置数越限、死值用停模拟、突变用大跨度置数、断链用手动断开）；契约 + 前端单测覆盖
- [x] **T94 连接医生**（P1，0.5~1 人日；2026-11-10 交付 `d2082bc`）：把 T92 那轮「连不上」的人工分层排查变成一键自检——`POST /api/master/doctor` 分层执行：① TCP connect（报「端口不通/防火墙」）；② STARTDT ACT→CON（t1 内）；③ 数据流观察（N 秒 rx>0？自动学习了哪些 IOA/类型？）；④ 结论 + 人话建议（端口错/对端不回确认/点表 IOA 分区不匹配）。复用 T92 取证逻辑（S 帧计数、N(R) 推进、COT 异常——对 simulator4 类对端直接给出「链路通但对端不回确认」结论）。UI（Carbon/PF）连接面板「诊断」按钮 → 逐层结果行（红绿 + 建议）；诊断结论可附进测试报告。**验收**：对 simulator4 给出明确的对端不确认结论；对本仓子站四层全绿

### v1.10.0（已发布：tag `v1.10.0` / commit `951d5c9`，2026-11-10；用户指定开工并当日发版：真机联调三缺口 A2/D/C → T95~T97 + T89 遗留两项门禁 → T98/T99）

> 依据：v1.9.0 已发布；`docs/architecture_plan.md`「2026-11-10 迭代方向比选」中 ⏸ 的
> A2/D/C 三项，加上 T89 遗留的桥接页巡检与 PF 边框覆盖，用户指定全量开工。
> **发版证据**：Release 流水线 `42832085143` 全绿，三资产
> （windows-x64.zip / linux-x64.tar.gz / SHA256SUMS.txt）已发布；CHANGELOG [1.10.0]、
> 双语 README 徽章/特性、四个版本源（core/version.py、pyproject.toml、
> package.json、package-lock.json）与静态资源同步；版本守卫用例全绿。

- [x] **T95 Excel(xlsx) 点表导入 + 设计 vs 实测比对**（A2，P1，2~3 人日；2026-11-10 交付 `18cc6a2`）：后端 `webui/points_xlsx.py`（新增 openpyxl 依赖）：xlsx 导出/解析（列头中英双语兼容、行级错误收集不 fail-fast）+ `POST /api/points/xlsx/preview|import`（preview 无副作用，仿 SCD preview 先例）；设计基准：导入 xlsx 时快照为设计表 + `POST /api/points/design {action:set|clear}`（CSV/YAML 导入亦可手动建基准）；`GET /api/points/design-diff` 三类差异——**缺**（设计有/实测无）、**多**（实测有/设计无，即自动学习兜底进来的真实 IOA）、**值域**（类型不符或实测观测极值越出设计声明域——取 data_store 的观测 min/max，勿与设计声明值混淆）。前端（Carbon/PF；经典版冻结仅数据层）：点表导入收 .xlsx（二进制 POST）、主站页设计比对卡（基准管理 + 缺/多/值域分组清单）；契约三件套（api_contract.md §2/§4 + endpoints.ts + contracts.ts 键集比对）同步。**验收**：真实 xlsx 导入 + 三类差异各有触发证据；pytest 覆盖解析/比对/端点（中英列头、坏行收集、文件名安全）。**交付**：解析器 10 项 pytest（中文列头/类型别名/强制分支/空簿/坏行与有效行并存）+ e2e（fixtures/points.xlsx → 子站页导入 → 主站页基准比对「与实测一致」）；实测教训：`str(v or "")` 把 0 当空值（min_value=0 被吞，已修）
- [x] **T96 离线报文对比（升级前后 diff）**（D，P1，3~4 人日；2026-11-10 交付 `18cc6a2`）：后端纯函数 `webui/frame_diff.py`（仿 report.py 零依赖模式）：两段录制（.i104/.json）按「规格化签名」做多重集 diff——签名 = 方向 + 帧型 + ASDU 头（type/vsq/cot/ca）+ 信息体（IOA+值，剥 CP56Time2a 时标）；**必须忽略易变字段**：APCI N(S)/N(R)（两段会话各自从 0 起算）、时间戳、metadata.client_id。输出 `{identical, totals, entries:[{签名摘要, count_a, count_b}]}`；`POST /api/capture/diff` body `{a,b}`（复用 CaptureService 目录与文件名校验）。前端（Carbon/PF）抓包页「报文对比」卡：两个文件下拉 + 对比按钮 + 差异表（规格化内容 | A 段次数 | B 段次数）。**验收**：同录制自 diff 为空（identical=true）；人为改动（改值/删帧/COT 变化）可检出；pytest 纯函数 + 端点（含路径安全）。**交付**：pytest 11 项（自 diff 空/改值/删帧/COT·CA·类型变化/PN·T 位/空 ASDU/脏帧回退/截断/跨格式/端点 400 族）+ e2e 真桥录两段（A vs A identical、A vs B 改值检出）；实测教训：capture 默认文件名按秒生成，同秒两段录制撞名覆盖（e2e 已显式命名）
- [x] **T97 桥场景化注入时间线 + 自动判定**（C，P1，5~7 人日；2026-11-10 交付 `18cc6a2`）：后端 `webui/timeline.py` TimelineService（bridge 角色）：步骤模型 `{label, duration_s, condition(NetworkCondition 字段), expect(none/loss/k-exceed/t1/disconnect)}`；`GET/POST /api/bridge/timeline` + `POST /api/bridge/timeline/run|stop`（运行中重复 run 与未启动桥拒绝）。执行：逐步 set_condition → 按 tick 采集窗口内 injection_stats 增量 + compliance 新违规（按 ts 归窗）→ 逐步判定（loss 看 dropped 增量；k-exceed/t1 看窗口内违规 kind；none 要求零丢帧零违规；disconnect 看断链增量）→ 结果 `{steps:[{ok, observed, violations, detail}], ok_all}` 入历史并自动进测试报告（report.py 新段，仿 T93 告警段先例）；判定逻辑用合成帧序列锁死防误报（仿 test_compliance_monitor.py helpers，tick 可注入）。前端（Carbon/PF）桥接页「注入时间线」卡：结构化步骤编辑器（标签/时长/丢帧%/延迟ms/期望）+ 保存 + 运行 + 逐步骤红绿结果行。**验收**：「注入丢包 → k 超窗」闭环判定证据（合成帧单测 + e2e 真桥）；判定入报告；时间线运行期间合规监视照常。**交付**：防误报口径实测打磨两处——①运行起点吃掉历史违规游标（上次运行/运行前流量不参与）；②none 判定不吃 t1/t2/t3 超时类证据（陈旧会话状态在首窗必误触发），t3 与注入无关一律排除；e2e 教训：合成流量必须「合规」——迷你主站发监视方向数据会被 dir-wrong 正确抓住、恒值上送被 spont-duplicate 抓住（监视器是对的，改用上游发数据+客户端确认的合规角色）；报告段「11. 注入时间线」断言入 e2e
- [x] **T98 桥接页纳入 UI 巡检矩阵**（P1，0.5 人日；2026-11-10 交付 `5a662c7`）：三个页级门禁（ui-audit / ui-contrast / ui-nontext-contrast）页面清单补 bridge 页——门禁主部署（8767 both）按角色过滤本就没有桥菜单，须走 BRIDGE 8769 webServer（已常驻）；PF/Carbon 两套 × 3 视口 × 中英深浅对齐主巡检口径。**验收**：桥接页 0 硬失败、0 裁切、0 console error；巡检计数纳入。**交付**：ui-audit 新增独立桥接页用例（断言 bridge 部署角色隔离），ui-contrast/ui-nontext 在模式循环内补桥接页扫描；**巡检即刻抓到真缺陷**：桥角色状态页无条件挂载告警卡/网络模拟卡 → 轮询未注册的 /api/alarms、/api/simulation 得 404——按标准修（角色已知且非 bridge 才渲染，规避 status 未加载首帧闪现）
- [x] **T99 非文本门禁覆盖 PF 伪元素/box-shadow 边框**（P1，1 人日；2026-11-10 交付 `5a662c7`）：T89 遗留——PF 6 控件边框画在 `::before`/`::after`（form-control 边框实测为 `inset:0` 伪元素）与 box-shadow 环上，「边框」段只读元素自身 border → PF **0 命中**。补：① 元素自身无边框时读 `::before`/`::after` 的逐边 border 宽色；② 零偏移/零模糊/正扩散的 box-shadow 环（与 readFocus 同一筛选，避免把高程阴影误判成边框）；对比色取内外相邻色中较优者（任一侧 ≥3:1 即可感知，防误报）。**验收**：PF 边框段命中 > 0、Carbon 回归不劣化（原 10 命中）、0 硬失败；抓到的真缺陷按标准修。**交付**：实测 PF 检查数 0 → **780 处**（伪元素逐边 + 零偏移零模糊正扩散 box-shadow 环）、Carbon 308 处不劣化；PF/Carbon × 中英深浅 × 含桥接页 **0 硬失败**（PF 边框色值本身达标，无需改产品 CSS）

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
- [x] T85 桥上网络条件注入（混沌验收）：帧级丢/重/坏/延迟/乱序/断线（条件器复用 NetworkCondition），帧边界重组保证半包/脏字节不丢；旁路观察始终看干扰前原始帧；`POST /api/bridge/condition` + 桥接页条件卡（Carbon/PF）+ 报告注入段；每条链路独立断线状态、统计跨连接累计、运行中动态设置；pytest 14 项
- [x] T86 应用层合规规则第二批：公共地址不符（基线/显式期望双模式）、连续重复自发帧（同值 COT=3 在 10s 内重复）、CP56 时标偏离 >300s（对象体解析失败跳过）；合规监视器合计 28 项
- [x] T87 报告嵌曲线快照：历史曲线 getDataURL → 共享 store（4 张）→ POST 报告端点嵌 `<img>`（仅 PNG dataURL 前缀，防注入）；状态页导出改 fetch+Blob（失败降级 GET）；pytest 2 项
- [x] T81 合规监视器应用层规则：方向错位（子站发控制 ACT/主站发监视类型）、无请求响应（COT=7 前无在途 ACT，60s 过期）、总召唤未终止、非召唤期数据（COT=20~36/37~41）、COT=0——`ASDU.decode_header` 只取头部（畸形对象体不影响监视）；pytest 应用层 9 项
- [x] T82 报告结论横幅：`conclusion/conclusion_kind`（合格绿/不合格红/有条件琥珀）→ 状态页导出区「结论下拉 + 说明输入 + 导出」（Carbon/PF）；pytest 2 项
- [x] T84 TLS 透传桥：`BridgeConfig` 双侧独立 ssl context（明文↔TLS 混合桥接支持；TLS 终结在桥——帧解密可见，合规监视/录制照常）；CLI `--bridge-listen-tls-cert/key` + `--bridge-upstream-tls-ca[/cert/key/hostname]`；pytest 2 项（混合桥接双向，证书复用 tests/certs）
- [x] T83 多连接并发压测：压测自建 N 条主站连接（1~8，独立 MasterEngine auto STARTDT+GI）同时接入子站，per_connection 分行统计；结束态回放冻结汇总（修「拆引擎后 status 算 0」）；busy 竞态修复（STARTDT 等待期二次启动穿透）；真引擎 2 连接端到端 pytest（总帧数≈事件数×2）
- [x] T79 协议合规监视器：桥旁路自动违规指认（序号跳变/重复、确认超前、未启动传数据、STARTDT/TESTFR 时序、k/t1/t2/t3 超时）——违规列表进桥接页与测试报告；`core/engine/compliance_monitor.py` 合成帧序列 pytest 12 项（确定性，不起真机）
- [x] T80 时钟偏差测量：**修规约符合性缺陷**（子站时钟同步确认曾回显主站时间，按标准改携子站当前时钟）+ 主站偏差采集（RTT/2 近似）+ `POST /api/master/clock_offset` 测量端点 + 命令面板「测量时钟偏差」按钮；真引擎 3 连测偏差近 0 稳定
- [x] T77 历史趋势回放：历史页「曲线」页签（Carbon/PF）——`data_history` 点位时间序列回放曲线（序列 1~8、时间范围随查询、遥信阶梯/遥测折线、0×0 防护同趋势图）；数据层早已落库，本轮纯补消费侧（后端零改动）
- [x] T78 压测×报告贯通：`LoadTestService.last_summary()` → 报告自动带「压测汇总」段落（跑过才有）；pytest 7 项
- [x] T75 测试报告导出：状态总览页「导出测试报告」按钮（Carbon/PF）→ `GET /api/export/report.html`（attachment 自包含单文件 HTML，浏览器打印即 PDF）：会话信息 + 帧统计聚合 + 帧证据逐帧 APCI/ASDU 解码（脏帧回退）+ 事件表；`webui/report.py` 纯函数零依赖，pytest 6 项
- [x] T76 压测编排：测试中心页压测卡（Carbon/PF，仅双角色部署显示）→ `POST /api/loadtest/start|stop` + `GET /api/loadtest/status`：子站按目标速率（1~10000 eps）自发 YC/YX，主站 ConnectionStats 差分统计吞吐（avg_eps/avg_fps/errors）；编排层不改引擎（复用 slave_set_* 公开路径）；仅 both 模式挂载；真引擎端到端 pytest 3 项（1.5s@80eps 吞吐差分可见）
- [x] T74 桥接 Web UI 页（bridge 角色三件套）：① `EngineBridge` 增 **bridge 角色**（无引擎；`_BridgeRoleSessionStub` 把全部引擎操作统一拒绝为干净错误 dict——避免 20 处散落守卫漏一处即 500）+ `start_bridge/stop_bridge` + status 携带 `bridge_stats/bridge_cfg` + 帧节流（1Hz）广播状态刷新；② server：`POST /api/bridge/start|stop`，**引擎专属路由按角色跳过**（master/slave/multi 启停、点表写入、网络模拟在桥应用上 404，普通 UI 流量到不了），app.py `--mode bridge` 默认 Web 模式（8767；`--no-gui` 保留 T73 headless 形态）；③ 前端（Carbon/PF，经典版按冻结承诺不加）：`Role/PageKey` 增 bridge、菜单按角色过滤、**桥接观察页**（配置启停 + KvList 统计 + 复用 FrameViewer 的 WS 实时帧），`ok:false` 业务错误显形（端口被占不再静默）；④ e2e `bridge.spec.ts`：第 4 个 webServer（8769）+ 用例内 echo 上游 + node:net STARTDT 回环探针（本机部分端口段 bind 10048 → 测试监听口改 OS 派空闲口）。验证：后端 15 项桥 Web pytest；UI 端到端「启动→透传回环→帧视图/统计→停止」通过

### v1.11.0（已发布：tag `v1.11.0`，2026-11-12；现场工程可用优化，方案见 `docs/optimization_plan_v111.md`）

> 评估标准由「路线图是否跑完」改为「能否在现场工作使用」，差距集中在交付物（对点传动记录 / 非标装置互联 / 操作审计证据链），共 11 个 `WP` 工作包（P0×4 / P1×6 / P2×1）。T 序列仍仅剩 T50 / SCD 私有映射两项外部阻塞。

- [x] **WP1 ASDU 地址字段长度可配（P0，2026-11-11 实现）**：新增 `core/protocol/address.py`（`AsduAddressConfig` + 进程级 `set_default` / 任务级 `use_default` / 单帧 override 三级优先级）；`core/protocol/asdu.py` 的 encode/decode/decode_header 按配置取 **CA 1/2B、IOA 1/2/3B、COT 1/2B**，IOA 位宽溢出显式 `ValueError` 不静默截断；`AppConfig.asdu_address` YAML save/load（旧配置缺节自动回落 2/3/2）；CLI 新增 7 参数（通用 `--ca-length/--ioa-length/--cot-length` + 桥两侧 4 个），`--demo` 透传、headless 桥独立加载配置；`BridgeConfig.listen_address/upstream_address` 经两个转发任务各包 `use_default` 实现**两侧独立不串味**；9 个解码调用点去掉硬编码 `ca_length=2`（含 `frame_diff`/`report`/`tcp_bridge` 摘要）；`/api/status` 新增只读 `asdu_address` 键，前端契约 `contracts.ts`/`types.ts` 与 Carbon/PF 状态页显示生效口径。详见 [`docs/asdu_address_config.md`](docs/asdu_address_config.md)。
  - **验收实测**：`tests/test_asdu_address_config.py` 45 例（12 长度组合 × SQ、CP56 时标、APDU/头部解码、三级优先级、YAML 往返、旧配置兼容、非法值拒绝）+ `tests/test_tcp_bridge.py` 新增 2 例（桥两侧隔离 / `use_default(None)` 不屏蔽进程默认）全绿；默认 2/3/2 下既有黄金帧逐字节不变；全量后端 **1770 passed / 覆盖率 91.25%**（`--cov-fail-under=91`）、前端 typecheck + 133 单测、Playwright **61 e2e**、ruff 全绿。
- [x] **WP2 对点/传动验收闭环（P0，2026-11-11 实现，WP2a+WP2b 同版本闭环）**：新增 `core/data/commissioning.py`（`CommissionSession/CommissionItem` + 判定规则：品质异常/值不符/超时/SBO NACK 一律 FAIL，无期望值判 MANUAL 不出假 PASS，YC 按容差）+ `core/data/commission_store.py`（独立 SQLite `data/commissioning.db`，WAL + `RLock`，低频长期留存与历史库分离）+ `webui/commissioning.py`（编排服务：单活动会话守卫、逐点 SBO 两段式下发、中止时对所有已选未执行遥控补发 DEACT、执行期间暂停周期 GI/对时、完成自动恢复、EventBus 推 `commission.*` 事件不新增 WS kind）+ `webui/commission_export.py`（xlsx/json/html 三格式交付物，HTML 全转义可直接打印签字）；`webui/server.py` 注册 8 端点（仅 master/slave 角色，bridge 404），DB 操作走 `asyncio.to_thread`；前端 `src/lib/useCommission.ts` 共享逻辑 + Carbon/PF 双页面 + 菜单「对点传动」（bridge 角色隐藏），支持点表勾选、逐点期望值/回读异址 `command_ioas` 草稿、人工改判、逐点下发/回读帧 hex 证据；契约 `webui/api_contract.md` §2.4c + `contracts.ts` 8 条 `ContractKeyChecks` + 新增 `apiDelete`。
  - **验收实测（2026-11-11）**：`tests/test_commissioning.py` 覆盖判定规则/持久化/导出转义/API 全流程/编排状态机（stop、NACK、DEACT 清理、GI 暂停恢复、emit 失败、shutdown）全绿；全量后端 **1817 passed / 覆盖率 91.09%**（`--cov-fail-under=91`）、前端 typecheck + **137 单测**、i18n 清单 0、Playwright **62 e2e**（含新增「对点传动」视觉基线 `commission-light.png`）全绿。
- [x] **WP4a 操作审计 + 多用户三角色（P0 的 WP4 前半，2026-11-12 实现）**：新增 `core/data/audit.py`（`AuditStore`：SHA-256 哈希链 `hash=SHA256(prev_hash‖canonical_json)`，独立 SQLite `data/audit.db` WAL+RLock，`verify()` 全链校验报首个断点 id/原因——改一条 hash_mismatch、删一条 chain_break）+ `webui/audit.py`（`OperatorRegistry`：`--auth-config users.yaml` 多用户，token 只存 SHA-256 + `hmac.compare_digest`；`role_allowed()` 三角色权限矩阵唯一真值源；请求级 `Identity`/`AuditIntent` ContextVar）+ `webui/server.py`（token_auth 扩展：多用户命中→身份入上下文+权限检查；兼容单 token→匿名 admin、`X-Operator` 头补充操作人；多用户模式忽略该头防冒名；被 401/403 拒绝的请求**不入审计链**）+ `bridge._cmd()` 命令汇聚点落链（action=去 `/api/` 前缀路径，帧证据取命令窗口内 tx/rx 首帧 hex，`--demo` 等无身份调用不记）+ WP2 编排联动（每条传动以会话检查人身份写 `commission/yk|yc|step`，复用同一条链）+ 前端「操作审计」页（Carbon/PF：记录表 + 链校验 + json/csv 导出 + 操作人输入 localStorage）。4 新端点（`/api/audit/records|verify|export` + `/api/auth/users`，master/slave 角色注册）+ `/api/auth` 纯新增 `mode/operator/role`（契约 §2.4d）。
  - **验收实测（2026-11-12）**：`tests/test_audit.py` 32 例（哈希链/篡改检测报断点/权限矩阵/兼容模式不变/viewer 越权 403 且链上无痕/编排联动）全绿；既有 `test_webui_auth.py` 断言按纯新增字段适配；全量后端 **1849 passed / 覆盖率 91.05%**（`--cov-fail-under=91`）、前端 typecheck + 137 单测、i18n 清单 0、Playwright **63 e2e**（含新增视觉基线 `audit-light.png`）、ruff 全绿。
- [x] **WP4b 防误操作闭锁（P0 的 WP4 后半，2026-11-12 实现）**：新增 `core/engine/interlock.py`（条件解析 + 求值：多条件 AND、取值失败/读取异常按**不满足**处理即未知工况不操作、非法配置在点表加载时即 `ValueError` 不静默）；点表 `PointDef.interlock` 字段（YK/YC/STEP 三类命令点可声明，YAML 往返且**仅非空才写**，旧点表零影响）；`bridge._interlock_gate()`（**发送任何帧之前**求值：不满足则返回业务错误且**零帧下发**，DEACT 撤销帧作为安全清理动作例外始终可发；拒绝写 `yk/interlock-blocked` 审计、强制解锁写 `yk/force-unlock` 审计，复用 §2.4d 同一条哈希链）；`POST /api/master/{yk,setpoint,step,bitstring}` 新增可选 `force`（需 admin，界面二次确认，非 admin 拒绝且零帧）；`GET /api/points` 命令行新增只读 `interlock` 摘要。前端：点表类型列内联「联锁」标记（**不新增列**，避免压窄表格，符合 9:3 + 横向滚动约定）+ 命令弹窗列出闭锁条件与「强制解锁」复选框（危险色二次确认）。文档 [`docs/interlock.md`](docs/interlock.md) + 契约 §2.4e。演示点表**不预置**闭锁（避免"点了遥控却被拒"的困惑），仅在 `configs/demo_points.yaml` 给注释示例。
  - **验收实测（2026-11-12）**：`tests/test_interlock.py` 35 例（解析/求值/点表往返/**闭锁不满足时发送列表为空**/值未知即阻断/非 admin force 拒绝且零帧/DEACT 例外/API 契约形状）全绿；全量后端 **1880 passed / 覆盖率 91.06%**（`--cov-fail-under=91`）、前端 typecheck + 137 单测、i18n 清单 0、Playwright **63 e2e**（既有视觉基线零漂移）、ruff 全绿。
- [x] **WP3 文件传输完工 + T50 按新口径验收（P0，2026-11-12 结案）**：**2026-11-12 用户明确反转口径**——「找不到真机测试。服务端客户端互测+其他开源软件测试能过就行，不用纠结真机」，故不再等待真机装置。
  - `core/protocol/file_semantics.py` + `AppConfig.file_transfer`：`ed1`（默认，历史 golden 帧逐字节一致）/`ed2`（lib60870.NET + otfabric 共识：目录 COT=5/SCQ=0、NOF 枚举校验）/`project` 三档，NOF/SCQ/FRQ-SRQ/DEACT/分包大小全部显式化；非法档位加载期报错。
  - **从站多节分包**：按 `section_size` 切 N 节，逐节 `F_SR→SCQ=6→F_SG→F_LS(LSQ=3)→F_AF(3)`、最后节 LSQ=1、**逐节 CHS**；真实 TCP **768B / 3 节×256B** 闭环逐字节还原。
  - **主站上传方向**：`FileTransferMaster.start_upload()` + `POST /api/master/file {action:"upload", data:hex}`；真实 TCP **560B 上传**子站落盘 + F_AF 肯定 + 主站 COMPLETED；CHS 篡改回否定且不落盘。
  - **5 项开放项结案**：[`docs/file_transfer_open_items.md`](docs/file_transfer_open_items.md) 以 lib60870-C v2.4.1 / lib60870.NET / otfabric 5 栈（25 配对 3071 passed）+ 本仓真实 TCP 互测交叉证据逐项判定；`tests/test_file_transfer_*.py` 全套 + 离线契约向量 **101 passed**。
  - **验收实测**：全量后端 **2093 passed / 覆盖率 91.26%**、前端 162 单测、i18n 0、Playwright **63 e2e**、ruff 全绿。**发布阈值达成，可对外宣称「现场工程可用」**；剩余仅 WP11（标准/样本外部阻塞）。
- [x] **WP5 工程配置方案管理（P1，2026-11-12 实现）**：新增 `core/data/profiles.py`（方案 YAML 存取：名称校验拒绝路径穿越、坏文件不影响列表、活动指针 `_active.yaml` 已被 git 忽略）+ `webui/profiles.py`（`capture()` 快照当前生效参数；`apply()` 写回运行态——连接、t0~t3、k/w、**ASDU 地址长度经 WP1 的 `set_default` 同步**、点表引用（走既有 `import_yaml` 重建实时库）、告警阈值；`restore_active()`）+ `core/config.py::apply_profile()` 与 CLI **`--profile <名称>`**（无浏览器场景；CLI 参数 47→48）+ 8 端点（`GET/POST /api/profiles*`，契约 §2.4f）+ 审计（`profiles/save|apply|delete` 入 WP4a 哈希链）。前端「工程配置方案」卡片挂**状态总览页**（Carbon/PF）：方案下拉 + 应用/删除/导出 YAML/另存/覆盖/文本导入 + 活动标记；**挂载时 `restore` 自动恢复上次方案**。随仓示例 `configs/profiles/示例-标准2_3_2.yaml`。文档 `docs/profiles.md`。
  - **关键取舍**：① **服务端启动不自动应用方案**——端口/角色只由 CLI 与 `--config` 决定，CI/e2e 与旧工作流保持确定性；"浏览器刷新后还原"由前端 onMount 调 restore 完成。② 方案**只覆盖工程参数**，不含 TLS/证书路径、历史库保留期、显示偏好（避免一份方案悄悄改掉安全与存储配置）。③ 方案文件本身即合法 `AppConfig` YAML → `--config` 与方案目录**双向通用**，旧单文件启动不受影响（`tests/test_profiles.py` 直接断言）。
  - **验收实测（2026-11-12）**：`tests/test_profiles.py` 42 例（含「3 套方案切换后连接/链路参数/ASDU 长度/阈值全部还原」逐项断言、点表引用还原、路径穿越拒绝、三角色权限、四类审计动作）全绿；全量后端 **1926 passed / 覆盖率 91.05%**（`--cov-fail-under=91`）、前端 typecheck + 137 单测、i18n 清单 0、Playwright **63 e2e**（仅 `status-light.png` 因新增卡片重生成后通过）、ruff 全绿。
- [x] **WP6 链路参数可观测面板（P1，2026-11-12 实现）**：三处协议层各加只读 `snapshot()`——`ConnectionStateMachine`（状态/已保持时长/t0~t3 剩余/**最近 20 次变迁时间线**，环形内存不落库）、`SequenceManager`（k/w/VS/VR/**unacked 未确认 I 帧**/窗口可用）、`TCPClient.link_stats()`（目标/连接态/重连计数与间隔/**最近失败原因与时刻**，**从未建连时也有记录**）；`MasterEngine/SlaveEngine.link_snapshot()` 聚合（子站取首条连接 + `clients` 计数）；`/api/status` **只增** `link` 键，且**引擎未启动时也存在**（state/sequence 为 null、transport 给出配置目标）——"连不上"正是最需要该面板的时刻。前端 `CarbonLinkStatsCard`/`PfLinkStatsCard`：指标卡（**未确认 I 帧与 t1 剩余并排**，t1 超时的两个前因同屏）、t0~t3 明细表、状态变迁时间线、transport 摘要行；共享纯逻辑 `src/lib/linkPanel.ts`。契约 §2.4g。
  - **验收实测（2026-11-12）**：`tests/test_link_observability.py` 21 例，其中 `test_real_t1_timeout_snapshot_shows_three_fields` 用**真 TCP 静默对端**（收帧不回确认）复现验收判据——总召唤发出后 `unacked≥1`、`t1.active=true` 且剩余递减、超时断链后 `reconnect_count≥1`；另覆盖未建连即有失败原因、降级路径不崩 status。全量后端 **1947 passed / 覆盖率 91.10%**（`--cov-fail-under=91`）、前端 typecheck + **149 单测**、i18n 清单 0、Playwright **63 e2e**、ruff 全绿。
- [x] **WP7 报文值域解码树（P1，2026-11-12 实现）**：`webui/frame_translate.py` 新增 `decode_tree()`——`{apci, asdu, objects[]}` 结构化树；**SQ=1 显式展开为 `base+i`** 并标 `sq_index`（不再显示成"N 个对象同地址"）；每对象含 `value / value_display / quality / quality_bits{iv,nt,sb,bl,ov} / quality_raw（不截位）/ timestamp / raw_hex`。`/api/frames/decode` 在既有 `segments` 之外**纯新增 `tree` 键**（§2.9，旧契约不变）。前端 Carbon/PF 报文查看器各加「对象」列，点击**就地展开子表**（不弹窗——现场要边看报文流边对照多个对象）；**只对含信息对象的 I 帧出子表**，S/U 帧给「无信息体」说明而不是空表。
  - **验收实测（2026-11-12）**：`tests/test_frame_decode_tree.py` 23 例，`test_sq1_twenty_objects_expanded` 逐条断言 20 行地址 `base+i`、值相等、第 4 条 IV、第 8 条 NT+BL；另覆盖 I/S/U 三帧、五位置品质（QDS）、CP56 时标、单对象降级、截断帧可读错误、`segments` 旧契约不变。**按标准确认**：SIQ/DIQ 的 bit0 是值本身不含 OV（OV 仅 QDS 有），单点遥信 `quality_bits.ov` 恒 false——测试按标准写，不迁就实现。全量后端 **1970 passed / 覆盖率 91.08%**（`--cov-fail-under=91`）、前端 typecheck + **154 单测**、i18n 清单 0、Playwright **63 e2e**、ruff 全绿。
- [x] **WP8 原生 Excel/PDF 报告（P1，2026-11-12 实现）**：新增 `core/export/` 包——`Evidence` 统一数据模型（会话信息 + 帧统计 + **WP2 逐点证据** + WP4 审计流水 + 告警 + 结论 + 曲线），`xlsx`（openpyxl，摘要/逐点证据/审计流水 3 sheet）/`pdf`（reportlab，**可选依赖 `report[pdf]`**）/`html`（复用 `webui/report.py` 自包含渲染 + 逐点/审计段）三导出器；`GET /api/export/report?format=html|xlsx|pdf`（契约 §2.4h），`?session=` 缺省取最近一次传动会话。前端状态页加「导出 Excel/PDF」。**未装 PDF extra 时端点返回 400 + 安装提示（非 500）**，onefile 包 HTML/xlsx 仍可用。
  - **验收实测**：三种格式**逐点证据条数一致**（`test_point_count_identical_across_formats`）；装 reportlab 后 PDF 真实生成 `%PDF-1.4`；本机起服务实测 html/xlsx/pdf **均 200**。
- [x] **WP9 旁路真实网卡抓包（P1，2026-11-12 实现）**：新增 `core/capture/sniffer.py`——Linux `AF_PACKET`（标准库，需 root/CAP_NET_RAW）、Windows Npcap+scapy（可选）；解析以太网/IPv4/TCP（含 VLAN）提取完整 104 APDU（半帧不猜），按 `tcp port 2404` 过滤，缓冲上限 20000 帧；输出构造成既有 `FrameEntry`，**`save_pcap`/`load_pcap`/回放/diff 全链路零改动复用**。4 端点（契约 §2.14b）+ 抓包页旁路卡片（Carbon/PF）。**诚实降级**：无能力/无权限时 `start` 返回 `ok=false` + 具体原因，不假装抓到包（本机实测：无 Npcap → 明确原因）。真网卡端到端受现场网络镜像/权限约束，保持 B=1 标注，**不属发布门禁**。
- [x] **WP10 点表在线编辑 + 服务化/容器交付（P1，2026-11-12 实现）**：
  - **10a**：`POST /api/points/upsert` / `DELETE /api/points/delete`（契约 §2.4i）支持五类点的新增/就地改字段/删除；前端 Carbon/PF 点表工具栏加「新增点/编辑点」对话框（共享 `src/lib/pointEdit.ts`）。**关键约定：在线增改删点不重置 `design` 设计基准**——`design-diff` 仍应报出「多/缺」差异（测试端到端断言），要更新基准须显式 `/api/points/design {action:"set"}`。
  - **10b**：`Dockerfile`（node 构建前端 + python 运行时多阶段，tini PID1、非 root、healthcheck）、`docker-compose.yml`（强制 `IEC104_AUTH_TOKEN`、命名卷持久化、`configs` 只读挂载）、`deploy/iec104-tester.service`（systemd，基础加固）、`deploy/install-service.ps1`（sc.exe 注册 + 令牌放 Machine 环境变量，无令牌拒绝安装）、`deploy/.env.example`、`docs/deploy.md`（离线部署：无 CDN、wheels 离线安装、docker save/load、CAP_NET_RAW 说明）；`build/build_all.py` 把 `capture_tool`/`sim_tool`/`run_multi_station`/`run_tests` 纳入 exe 随包。**服务化不改变 `SECURITY.md` 的「非生产 SCADA 网关」边界**，文档已写明。
  - **交付物实测**：compose YAML / systemd 单元 / PowerShell 脚本语法校验通过；本机起同一 `app.py` 入口 200；`pyproject.toml` 加 `report[pdf]` extra。
- [x] **WP11 标准合规收口（P2，2026-11-12 按新口径结案）**：用户确认「按同一口径处理」——与 WP3/T50 一样以互测 + 开源多实现交叉证据验收，不再等标准原文/厂商样本/检测机构清单/现场抓包。
  - **拆包**：WP11 不是整体 B=1（9 项里 5 项外部条件本就写「无」）。**11a（B=0 已交付）**：① 统一文档用例数并新增 `docs/baseline.json` 单一真值源 + `tests/test_version_consistency.py` 加用例数断言（实测改错即红、恢复即绿）；② `MasterConfig.auto_clock_sync` 从死配置恢复并在 `master_session` 的 STARTDT_CON 分支真实接线（默认 false 零回归）；`compliance.max_time_skew_s`（原硬编码 300.0）与 `time_tag_format` 提升为配置；③ `tests/test_wp11a_coverage.py` 表驱动 17 例补齐 `master_protocol` 多类型 GI 响应分支；④ `docs/tls.md` 补「按新口径合规结论」（TLS 62351-3 + WP4 审计已验证，**62351-4/-6 应用层认证仍不宣称合规**）+ 冗余双通道切换可观测接入 WP6 面板（活动通道/切换次数/主备连接）。**11b（增强项不设门禁）**：SCD 私有映射/型式试验清单/真机语料以已有开源语料（otfabric cases.tsv、lib60870 golden 帧、离线契约向量）结案，真实样本立增强工单。
  - **验收实测**：全量后端 **2121 passed / 覆盖率 91.49%**、前端 **179 单测**、i18n 0、Playwright **63 e2e**、ruff 全绿；`baseline.json` 守卫能抓用例数漂移。`README.md` / `README_eng.md` 基线统一为 2121 / 91.49% / 179 / 63（发版前补 `wp11Hooks.test.tsx` 15 例，修 v1.11 前端 V8 覆盖率门禁）。**发布阈值维持已达成状态**；11 个 WP 全部按新口径收口。

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
