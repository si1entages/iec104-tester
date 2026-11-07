# 文件传输 F_LS 八位组语义核实（T24）

> 范围：IEC 60870-5-101/104 文件传输 ASDU 的**八位组语义**，重点是
> **F_LS_NA_1（最后的节、最后的段）= TypeID 123**。
> 结论分两类：**已核实**（有明确依据）与**待核实**（依据不足，列出开放问题，不臆测）。
> 实现改动只落在 `core/protocol/file_transfer.py` 与 `tests/`；其余落点见「待修」。

## 1. 核实方法与依据

| 依据 | 性质 | 用途 |
|---|---|---|
| lib60870.NET `lib60870/CS101/FileObjects.cs`（commit `4ad2923d`，mz-automation） | **字节级参考实现**（业界广泛部署的开源参考栈） | 各类型信息体的字段顺序、长度、编码方式，以及 LSQ/AFQ/SCQ/FileError/NameOfFile 取值表 |
| lib60870.NET API 文档 `lib60870.CS101` 命名空间 | 同上（枚举定义与注释） | 枚举名/值/语义交叉印证 |
| j60870（openmuc）信息元素清单 | 第三方实现交叉印证 | 印证 F_LS 的信息元素组合为 NOF+NOS+LSQ+CHS |
| go-iecp5 `docs/filetransfer.md` | 第三方实现交叉印证 | 印证「F_LS 携带 CHS 校验和」与 LSQ 的用法 |
| IEC 60870-5-101 标准正文 | **未能取得**（付费标准，且本环境无法访问权威原文） | —— 故所有「字段顺序/长度」结论均以参考实现的**字节级编解码代码**为依据，并在第 4 节列出仍需真机确认项 |

> 说明：lib60870 是 CS101/CS104 文件传输在工程实践中的事实参照实现，其
> `Encode()`/`Parse()` 逐字节写出/读入字段，可直接作为八位组布局依据；但由于
> 未取得标准正文，凡涉及「标准是否允许其它变体」的问题一律列入**待核实**。

## 1.1 独立交叉印证（提交前追加，来源与本文件原依据相互独立）

为避免「只信单一实现」，以下结论另经**三个互相独立**的渠道复核，结论一致：

| 独立来源 | 佐证的具体结论 |
|---|---|
| Schneider Electric《Telecontrol — Engineering User's Guide》Figure 33/34（公开手册） | F_FR_NA_1 = 文件名 + **文件长度「Range 0..16777215」**（= 2^24−1 → **24 位/3 字节**）+ 文件准备就绪限定词（0=肯定 / 1=否定）。**独立印证 §5.1 的 LOF=3 字节** |
| PMC 期刊论文（IoT/遥测系统）Table 6（F_DR_TA_1 目录 ASDU 定义） | 目录 ASDU = IOA(3) + NOF(**2**) + LOF(**3**) + SOF(1) + CP56Time2a(7)。**独立印证 LOF=3 字节** |
| go-iecp5 `docs/filetransfer.md` + `asdu/asdu.go`（独立 Go 实现） | ① F_SG_NA_1 = `IOA + NOF(2) + NOS(1) + LOS(1) + 数据`，注释明确「**没有段号字段**」→ **独立印证 §5.2**；② F_LS_NA_1 携带 **CHS 校验和**，LSQ=3 表示最后的段、LSQ=1 表示最后的节；③ 每节校验和 = 「该节所有段八位组的**算术和 mod 256**」→ 为 §4.1 的 CHS 定义提供了**候选答案**（仍列待核实，见下） |
| lib60870.NET `CS101/FileServices.cs`（本次另行直读源码） | ① `new FileLastSegmentOrSection(ioa, nof, sectionNumber, LSQ, checksum)` → 字段顺序 `NOF,NOS,LSQ,CHS`；② 状态机以 `lastSection.LSQ` 判定 `SECTION_TRANSFER_WITHOUT_DEACT`/`FILE_TRANSFER_WITHOUT_DEACT`/`FILE_TRANSFER_WITH_DEACT`，并以 `lastSection.CHS == sectionChecksum` 做**节校验**；③ `new FileSegment(ioa, nof, sectionNumber, segmentData)` → 无段号字段 |

**标准正文状态**：IEC 60870-5-101/104 正文（含 §7.4.11 文件传输）仍**未取得**——
付费标准，本环境无法访问权威原文；检索到的公开片段仅能确认**类型标识语义表**
（`<120>:=file ready F_FR_NA_1` … `<123>:=last section, last segment F_LS_NA_1`），
**不含八位组级布局**。故：

- 「字段顺序/长度」以**多个互相独立的字节级参考实现 + 厂商公开手册**为依据（可信度高，但严格说不是标准原文）；
- 「标准是否允许其它变体」「CHS 是否就是算术和 mod 256」等**仍留在第 4 节待核实**，未因新增渠道而擅自升级为"已核实"。

> **4.1（CHS 算法）的进展**：go-iecp5 与 lib60870 **两者都用「该节所有段八位组的算术和 mod 256」**
> 且在收端以 `CHS == 计算值` 判定节的肯定/否定确认。本仓库已按该候选答案**实现**
> （发送侧计算 + 接收侧告警校验，见 §4.1 与 §5）——依据来源与「非标准原文」这一
> 事实在实现处与文档中**并列写明**，真机联调（§6 第 3 步）仍是最终确认手段。

## 2. 已核实（含依据）

### 2.1 类型标识

`F_FR_NA_1=120`、`F_SR_NA_1=121`、`F_SC_NA_1=122`、`F_LS_NA_1=123`、`F_AF_NA_1=124`、
`F_SG_NA_1=125`、`F_DR_TA_1=126` —— 与多份 PICS/互操作性文档一致，**本实现一致，无需修改**。

### 2.2 各类型信息体（不含 IOA）的字段顺序与长度

依据：lib60870 `FileObjects.cs` 的 `GetEncodedSize()` 与 `Encode()`（含逐字节 `SetNextByte` 顺序）。

| 类型 | 标准布局（依据：lib60870 `Encode()`） | 标准长度 | 本实现长度 | 结论 |
|---|---|---|---|---|
| F_FR_NA_1(120) | `NOF(2,LE) + LOF(3,LE) + FRQ(1)` | **6** | 6 | ✅ 已修（原 7，见 5.1） |
| F_SR_NA_1(121) | `NOF(2) + NOS(1) + LOF(3) + SRQ(1)` | **7** | 7 | ✅ 已修（原 8，见 5.1） |
| F_SC_NA_1(122) | `NOF(2) + NOS(1) + SCQ(1)` | **4** | 4 | ✅ 长度一致；SCQ 取值表已修（见 5.3/§2.6） |
| **F_LS_NA_1(123)** | **`NOF(2) + NOS(1) + LSQ(1) + CHS(1)`** | **5** | 5 | ✅ 末两字节角色已修（a75b9da），CHS 已实现（见 4.1） |
| F_AF_NA_1(124) | `NOF(2) + NOS(1) + AFQ(1)` | **4** | 4 | ✅ 长度与 AFQ 取值均一致 |
| F_SG_NA_1(125) | `NOF(2) + NOS(1) + LOS(1) + 数据`（**无段号字段**） | 4+len | 4+len | ✅ 已修（原 5+len，见 5.2） |
| F_DR_TA_1(126) | `NOF(2) + LOF(3) + SOF(1) + CP56Time2a(7)` | **13** | 13 | ✅ 已修（原 14，见 5.1） |

`LOF`（length of file / section）为 **24 位（3 字节）**；本实现曾按 32 位写入，是 F_FR / F_SR /
F_DR 各多 1 字节的直接原因，**已改为 3 字节小端**（编解码两侧 + `ASDU.decode` 长度表同步）。
`FRQ`/`SRQ` 的最高位（`0x80`）分别为「否定确认 / 未就绪」标志。

字节级回归：`tests/test_file_transfer_golden.py`（10 个 F_* 的完整线缆帧期望 hex
硬编码 + 4 条解码侧独立核对）——往返测试无法发现对称性错误，黄金用例补上这一环。

### 2.3 LSQ 取值表（F_LS_NA_1 第 4 字节）

依据：lib60870 `enum LastSectionOrSegmentQualifier : byte`。

| 值 | 名称 | 语义 |
|---|---|---|
| 0 | `NOT_USED` | 未使用（目录传输的结束标记即用此值） |
| 1 | `FILE_TRANSFER_WITHOUT_DEACT` | **整个文件**传输的最后一节；不要求去激活 |
| 2 | `FILE_TRANSFER_WITH_DEACT` | **整个文件**传输的最后一节；要求去激活 |
| 3 | `SECTION_TRANSFER_WITHOUT_DEACT` | 仅**当前节**传输结束（文件未结束）；不要求去激活 |
| 4 | `SECTION_TRANSFER_WITH_DEACT` | 仅**当前节**传输结束（文件未结束）；要求去激活 |

**判定规则（已核实）**：**仅 LSQ=1/2 表示"整个文件传输结束"**；LSQ=3/4 只表示
「本节结束」，文件可能还有后续节；LSQ=0 不表示任何结束。

### 2.4 AFQ 取值表（F_AF_NA_1 第 4 字节）

依据：lib60870 `enum AcknowledgeQualifier`：`0=NOT_USED`、`1=POS_ACK_FILE`、
`2=NEG_ACK_FILE`、`3=POS_ACK_SECTION`、`4=NEG_ACK_SECTION`。
本实现 `AckFileSection.qualifier` 的文档与之一致 ✅。

### 2.5 SCQ 取值表（F_SC_NA_1 / F_SC_NB_1 第 4 字节）

依据：lib60870.NET ``enum SelectAndCallQualifier`` + go-iecp5 ``FileCallOrSelect``
（两个互相独立的字节级实现取值一致）。

| 值 | 名称 | 语义 |
|---|---|---|
| 0 | 缺省 | 未指定 |
| 1 | `SELECT_FILE` | 选择文件 |
| 2 | `REQUEST_FILE` | 请求文件 |
| 3 | `DEACTIVATE_FILE` | 去激活文件 |
| 4 | `DELETE_FILE` | **删除文件**（旧实现误当"选择文件"，见 5.3） |
| 5 | `SELECT_SECTION` | 选择节（本实现暂借 5 触发目录上送，见 4.4） |
| 6 | `REQUEST_SECTION` | 请求节 |
| 7 | `DEACTIVATE_SECTION` | 去激活节 |

实现出处：``core.protocol.types.SCQ_NAMES``（唯一取值表）。

### 2.6 FileError 取值表

依据：lib60870 `enum FileError`：`0=DEFAULT`、`1=REQ_MEMORY_NOT_AVAILABLE`、
`2=CHECKSUM_FAILED`、`3=UNEXPECTED_COMM_SERVICE`、`4=UNEXPECTED_NAME_OF_FILE`、
`5=UNEXPECTED_NAME_OF_SECTION`（用于否定 AFQ 时携带错误码）。**本实现未建模该字段**
（只发 AFQ，不带错误码）→ 见 4.2。

## 3. 本次已修（`core/protocol/file_transfer.py`）

**问题**：`LastSection` 的字段名 `last_segment` / `status` 与标准不符，导致
*读*与*写*都把 **LSQ 与 CHS 两个字节用反了**：

- 旧「读」：以第 5 字节（标准中的 **CHS 校验和**）作为完成判据 —— 任何校验和恰为
  1/2 的报文都会被误判为"传输完成"，而 LSQ=1 但校验和为其它值的报文反而不完成。
- 旧「写」：把**段数**写进第 4 字节（标准中的 **LSQ**）、常量 1 写进第 5 字节。
  文件被切成 ≥3 段时 LSQ 会落到 3/4（=仅节结束）甚至 >4（超出定义域）。

**修改**（不改任何线缆长度，只改两个字节的角色与判定）：

1. 新增 LSQ 常量与语义分组 `LSQ_FILE_COMPLETE=(1,2)`、`LSQ_SECTION_COMPLETE=(3,4)`；
2. `handle_last_section()` 按**字节位置**解释（`last_segment` 槽 = LSQ、`status` 槽 = CHS），
   **仅 LSQ∈{1,2} 判定完成并回调**；LSQ∈{3,4} 记录"本节结束"；LSQ=0 不判定；
   超出 0-4 记告警；
3. `_send_last_section()` 在 LSQ 八位组写 1（`FILE_TRANSFER_WITHOUT_DEACT`，本实现
   把整个文件作为单个节发送）；目录结束标记明确写 `LSQ_NOT_USED=0`；
4. `FileTransferContext.last_segment` 更名为 `lsq`（该字段本就存的是 LSQ）。

用例：`tests/test_file_transfer_fls.py`（20 例）覆盖 LSQ 定义域、1/2 与 3/4 的分流、
LSQ=0、非法 LSQ、CHS 不参与判定、0/1/200/201/700 字节的分段边界、收发闭环
（编码→解码→主站判定）、目录结束标记。

## 4. 待核实（含开放问题，未臆测、未改动）

> 真机联调执行清单（5 项开放项的验证步骤、判定标准、记录模板）见
> [`file_transfer_open_items.md`](file_transfer_open_items.md)；
> 配套只读探针 `python tests/e2e/qa_file_transfer_probe.py`。
> 第三方实测原始记录：[`file_transfer_third_party_probe_2026-11-07.md`](file_transfer_third_party_probe_2026-11-07.md)。

### 4.1 CHS（本节校验和）—— 已按候选答案实现（依据非标准原文）
- **判定**：CHS = **本节所有段数据八位组的算术和 mod 256**。依据为两个互相独立的
  字节级实现的一致做法：
  ① lib60870-C `file_server.c::calculateChecksum`（`checksum += data[i]`，uint8 溢出即 mod 256）；
  ② go-iecp5 `docs/filetransfer.md`（「该节所有段八位组的算术和 mod 256」）。
- **非标准原文**：IEC 60870-5-101/104 正文未取得，上述仅为工程实现的一致做法；
  依据来源与该事实在 `core/protocol/file_transfer.py`（`section_checksum` 处注释）
  与本节**并列写明**。
- **实现方式**：发送侧 `_send_last_section` 按 `section_checksum()` 计算并写入第 5 字节；
  接收侧 `handle_last_section` 在 LSQ∈{1,2,3,4} 时按同算法核对，**不匹配记告警、
  不丢弃数据、不改变完成判定**（完成判定只看 LSQ）；LSQ=0（目录结束标记）与
  超定义域取值不校验。之所以不"校验失败即拒收"，是因为算法本身未经标准正文确认。
- **遗留确认**：真机联调（§6 第 3 步）——构造校验和错误，观察对端是否回 AFQ=2/4
  及是否携带 FileError（关联 4.2）；起始/结束偏移（是否含 LOS/段头）亦以真机为准。

### 4.2 否定确认是否必须携带错误码（FileError）
- **开放问题**：AFQ=2/4（否定文件/否定节）时，信息体内是否必须/可以带 FileError 码？
  本实现只发 4 字节（NOF+NOS+AFQ），无错误码字节。lib60870 的 `FileACK` 构造函数
  接受 `FileError errorCode`，但其 `Encode()` 只写 AFQ —— 与"错误码随 AFQ 语义隐含"一致，
  但不足以断定标准要求。
- **建议**：以标准正文或真机（构造一次校验和错误，观察对端回帧字节数）确认。

### 4.3 NOF 的含义（Ed.1「文件名」vs Ed.2「文件类型」）
- lib60870 把 NOF 定义为枚举 `NameOfFile`（0=DEFAULT / 1=TRANSPARENT_FILE /
  2=DISTURBANCE_DATA / 3=SEQUENCES_OF_EVENTS / 4=SEQUENCES_OF_ANALOGUE_VALUES）；
  本实现把 `file_name` 当任意 16 位标识使用（内部自洽，但真机语义未知）。
- **第三方实测（2026-11-07，lib60870-C v2.4.1）**：正选 NOF=1 → F_FR len=800 status=0；
  负选 NOF=9 → F_FR len=0 status=0x80。该实现按 Ed.2 枚举解释，NOF 必须匹配提供者。
- **开放问题**：目标装置用哪一版语义？目录召唤返回的 NOF 取值集合是什么？（真机待测）

### 4.4 目录传输的表达方式（SCQ 与 NOF 的组合）—— 已选**内部一致的项目约定**
- **决定**：目录请求沿用 **SCQ=5**（`SCQ_REQUEST_DIRECTORY`），这是**项目约定值**，
  **不是标准值**——标准表中 5=`SELECT_SECTION`（j60870 同）。未取得标准正文的
  「请求目录的 SCQ/NOF 组合」前，不臆测其它组合。
- **内部闭环证据**（`tests/test_file_transfer_fls.py::test_directory_request_closes_loop_master_to_slave`）：
  master `file_call_directory` 发 F_SC_NA_1(SCQ=5) → 子站 `handle_file_request(5)` 回
  每文件一条 F_DR_TA_1 + 一条 F_LS_NA_1(LSQ=0) 终止标记，主子两侧都认 5。
- **第三方实测（2026-11-07）**：lib60870-C 的 file service 只处理 SCQ=1/2/3/6，
  **没有目录处理器**；SCQ=5（COT=6 或 13）均无回帧。故 SCQ=5 仅为本项目内部约定，
  不是可移植的目录表达；真机需按装置手册确认。
- **遗留**：真机对 5 的解释可能不同（按标准应理解为"选择节"），真机联调（§6 第 4 步）
  记录对端实际所用组合后再定夺是否改值。常量化后即使要改，也只动
  `SCQ_REQUEST_DIRECTORY` 一处定义。

### 4.5 `WITH_DEACT` 的后续动作
- LSQ=2/4 语义上要求"随后去激活"。**开放问题**：主站收到后是否必须回
  `F_AF`（去激活确认）或发送 DEACT 命令？本实现不区分 WITH_DEACT，仅按完成处理，
  未做任何推断性补发。
- **第三方实测（2026-11-07）**：lib60870-C 实际用 LSQ=3（节结束）/1（文件结束），
  主站回 `F_AF POS_ACK_SECTION` 后继续/结束，**未等待 COT=8 DEACT**。
  真机若使用 LSQ=2/4，仍需按清单复测。

### 4.6 多节（multi-section）流程 —— 已实现主站逐节接收
- 主站：收到 `F_SR` 自动发 `F_SC(SCQ=6, NOS)`；`F_SG` 段数据同时累积到文件与
  **本节缓冲**；`F_LS` 按 LSQ 回 `F_AF`（LSQ=1/2 → 肯定文件 1；3/4 → 肯定节 3），
  CHS 按本节缓冲校验（不把上一节数据算进下一节）。
- 从站：仍按单节发送（多节分包未实现，属另一项）。
- **第三方实测（2026-11-07，默认代码）**：lib60870-C 800B 文件分 2 节×400B，
  每节 2 段（236+164B），LSQ=3/3/1，CHS=184/72/0；主站完整接收
  `File received: name=1 size=800`，无 CHS 告警。

### 4.7 F_SC 类型/COT 与确认类型 —— 已修复
- 文件命令统一 `F_SC_NA_1(122) + COT=FILE(13)`；`F_SC_NB_1(127)` 仅保留解码兼容。
- 主站不再发送 `F_FR_NB(128)/F_SR_NB(129)`；收到 `F_SR` 改发 SCQ=6，收到 `F_LS`
  按 LSQ 回 F_AF。
- **第三方复测（2026-11-07）**：lib60870-C 不再把确认当上传公告（无 `COT=44`），
  select → request → 2 节 → 完成；真机仍按 open_items 复测。

## 5. 已修（5.1~5.4 + CHS，本轮完成；提交 559636b / b61e6ff / 4f6ee97 / ee8ca58 / ed6584a）

### 5.1 LOF 改 24 位（3 字节）—— 已修（559636b）
`FileReady`/`SectionReady`/`FileReadyAck`/`SectionReadyAck`/`DirectoryEntry` 编解码两侧
改为 3 字节小端（`_encode_u24le`/`_decode_u24le`）；`ASDU.decode` 的信息体长度表
7/8/14 → 6/7/13 同步（**解码表是备份补丁曾遗漏的调用点**，e2e 由此暴露）。
黄金用例：`test_golden_f_fr_n1_120_body_6` 等 + `test_golden_decode_f_fr_24bit_lof_boundary`
（0xFFFFFF 上界）。

### 5.2 F_SG 去掉「段号」字节 —— 已修（559636b）
`FileSegment` 信息体 = `NOF(2)+NOS(1)+LOS(1)+数据`，`build_file_segment` 去掉
segment_number 形参；收发两侧调用点同步（接收侧改段计数，不再有段号语义）。

### 5.3 SCQ 取值表标准化 —— 已修（b61e6ff）
`SCQ_NAMES`（§2.5）+ `handle_file_request` 分支重写：SCQ=4（删除文件）移出缓存并回
F_AF_NA_1，**绝不触发上送**（旧实现把 4 当"选择文件"）；SCQ=1/2 上送流程不变；
SCQ=5 暂借为目录触发（开放项见 4.4）；SCQ=3/7、6 仅记录不推断。

### 5.4 LastSection 字段更名 —— 已修（4f6ee97）
`last_segment`/`status` → `lsq`/`chs`，`status_str` → `lsq_str`（复用 `types.LSQ_NAMES`）；
`build_last_section` 形参、`handle_last_section`、`_send_directory` 结束标记、
`io.py` 显示分支（LSQ=n(名称) CHS=n）一次闭环。

### 5.5（原 4.1）CHS 校验和 —— 已实现（ed6584a，见 §4.1）
发送侧按「算术和 mod 256」计算；接收侧校验不通过**记告警不丢弃**。

### 5.6 master 侧 SCQ 魔法数字 —— 已修（表修正后语义静默翻转的危险）
- `master_protocol.py::file_select` 曾发 `qualifier=4` —— 新表中 4=`DELETE_FILE`，
  "选择文件"会向真机发**删除命令**（破坏性）；`file_request` 曾发 1（新表=
  `SELECT_FILE`）；`file_call_directory` 曾发裸 5。三者全部改为带名常量
  `SCQ_SELECT_FILE` / `SCQ_REQUEST_FILE` / `SCQ_REQUEST_DIRECTORY`；
  `file_transfer.py::FileTransferMaster.request_file` 的 `qualifier=1`（# 请求读）
  同样常量化为 `SCQ_REQUEST_FILE`。
- 红线用例（`tests/test_file_transfer_fls.py` ⑥）：
  `test_master_file_commands_send_named_scq`（编码后 SCQ 字节 == 1/2/5）、
  `test_master_never_sends_scq_delete_file`（任何 F_SC 出帧 SCQ ≠ 4）、
  `test_master_manager_request_file_sends_scq_request_file`、
  `test_directory_request_closes_loop_master_to_slave`（目录内部闭环）。

### 测试状态
- `tests/test_file_transfer_fls.py`：原 5 处缺陷钉桩（F_FR/F_SR 长度、F_SG 布局、
  LastSection 字段名、SCQ 表、SCQ=4 分支）**全部翻转为标准断言**，docstring 同步；
  新增 CHS 专项 5 例与 SCQ=2/4 行为回归。
- `tests/test_file_transfer_golden.py`：新增，14 例（10 编码黄金帧 + 4 解码独立核对）。
- `tests/test_file_transfer_upload.py` / `test_commands.py` / `test_protocol_io.py` /
  `conftest.py`：按新布局/新表同步（无行为断言改动，仅布局与显示文案）。

### 遗留的小项（非阻塞）
- `FileReady.status_str`/`SectionReady.status` 的显示表仍是旧文案（`0=缺省`）——
  FRQ/SRQ 的精确取值语义两处来源略有出入（Schneider 手册「0=肯定/1=否定」vs
  lib60870「最高位 0x80=否定」），保持现状待真机确认，未臆测。

## 6. 真机联调验证建议（供后续执行）

1. 抓包抓一条 F_LS_NA_1，按 `type,vsq,cot,ca,ioa,nof(2),nos(1),lsq(1),chs(1)` 手工解一遍，
   确认末两字节确实是 LSQ（0-4）与校验和；
2. 请求一个**大于 2 段**的文件（>2×段长），观察对端 F_LS 的 LSQ 是否恒为 1/2；
3. 故意构造校验和错误，观察对端是否回 AFQ=2/4 及是否携带 FileError（验 4.1/4.2）；
4. 请求目录，记录对端所用 SCQ/NOF 组合（验 4.4）。
