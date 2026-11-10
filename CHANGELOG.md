# Changelog

本文件记录对外可见的功能/修复；版本号与 `pyproject.toml`、
`core/version.py`、`webui/frontend/package.json` 保持一致。

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
