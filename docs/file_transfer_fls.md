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
> 且在收端以 `CHS == 计算值` 判定节的肯定/否定确认。这是两个独立实现的一致做法，
> 但因未取得标准正文，仍**列为待核实**，本次不实现校验逻辑（保持发 0、不校验）。

## 2. 已核实（含依据）

### 2.1 类型标识

`F_FR_NA_1=120`、`F_SR_NA_1=121`、`F_SC_NA_1=122`、`F_LS_NA_1=123`、`F_AF_NA_1=124`、
`F_SG_NA_1=125`、`F_DR_TA_1=126` —— 与多份 PICS/互操作性文档一致，**本实现一致，无需修改**。

### 2.2 各类型信息体（不含 IOA）的字段顺序与长度

依据：lib60870 `FileObjects.cs` 的 `GetEncodedSize()` 与 `Encode()`（含逐字节 `SetNextByte` 顺序）。

| 类型 | 标准布局（依据：lib60870 `Encode()`） | 标准长度 | 本实现长度 | 结论 |
|---|---|---|---|---|
| F_FR_NA_1(120) | `NOF(2,LE) + LOF(3,LE) + FRQ(1)` | **6** | 7 | ❌ 见 5.1 |
| F_SR_NA_1(121) | `NOF(2) + NOS(1) + LOF(3) + SRQ(1)` | **7** | 8 | ❌ 见 5.1 |
| F_SC_NA_1(122) | `NOF(2) + NOS(1) + SCQ(1)` | **4** | 4 | ✅ 长度一致；SCQ 取值表见 5.3 |
| **F_LS_NA_1(123)** | **`NOF(2) + NOS(1) + LSQ(1) + CHS(1)`** | **5** | 5 | ✅ 长度一致；**末两字节角色本实现原先颠倒**，见 2.4 / 已修 |
| F_AF_NA_1(124) | `NOF(2) + NOS(1) + AFQ(1)` | **4** | 4 | ✅ 长度与 AFQ 取值均一致 |
| F_SG_NA_1(125) | `NOF(2) + NOS(1) + LOS(1) + 数据`（**无段号字段**） | 4+len | 5+len | ❌ 见 5.2 |
| F_DR_TA_1(126) | `NOF(2) + LOF(3) + SOF(1) + CP56Time2a(7)` | **13** | 14 | ❌ 见 5.1 |

`LOF`（length of file / section）为 **24 位（3 字节）**；本实现按 32 位写入，是 F_FR / F_SR /
F_DR 各多 1 字节的直接原因。`FRQ`/`SRQ` 的最高位（`0x80`）分别为
「否定确认 / 未就绪」标志。

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

### 2.5 FileError 取值表

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

### 4.1 CHS（本节校验和）算法 —— 未取得
- **开放问题**：CHS 是"本节所有段数据的按字节 XOR"、"累加和取低 8 位"，还是别的定义？
  起始/结束偏移如何界定（是否含 LOS/段头）？F_LS 的 CHS 与 F_FR/F_SR 中是否另有校验？
- **当前处置**：发送侧 CHS 固定为 `0`（占位），**接收侧不校验**；本项未做任何猜测性实现。
- **建议**：从可获得的 IEC 60870-5-101 正文（§ 文件传输 的 F_LS 定义与校验和说明）或
  真机抓包（对端在同一节上多次传输同一数据时 CHS 是否稳定、与数据的关系）确认后再实现。

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
- **开放问题**：目标装置用哪一版语义？目录召唤返回的 NOF 取值集合是什么？

### 4.4 目录传输的表达方式（SCQ 与 NOF 的组合）
- j60870 把 SCQ=5 定义为 `SELECT_SECTION`；而本实现用 SCQ=5 表示"请求目录"。
- **开放问题**：请求目录究竟走「SCQ=? + NOF=?」的哪种组合？（是否 `NOF=DEFAULT` +
  `REQUEST_FILE`？或规范另有 SCQ 值？）本实现与 SCQ 取值表一并待修（见 5.3）。

### 4.5 `WITH_DEACT` 的后续动作
- LSQ=2/4 语义上要求"随后去激活"。**开放问题**：主站收到后是否必须回
  `F_AF`（去激活确认）或发送 DEACT 命令？本实现不区分 WITH_DEACT，仅按完成处理，
  未做任何推断性补发。

### 4.6 多节（multi-section）流程
- 本管理器不支持真正的多节累积与逐节校验：段数据一律拼进 `_context.data`，
  且没有"节结束 → 等待下一节"的状态迁移。**开放问题**：对端按 LSQ=3/4 分节上送时，
  主站是否应逐节校验并按节回 `F_AF`（POS_ACK_SECTION）？—— 依赖 4.1 的校验和结论。

## 5. 待修（需授权，本次未改动）

### 5.1 F_FR / F_SR / F_DR 的 LOF 应为 3 字节（各多 1 字节）
- 落点：`core/protocol/types.py`（`FileReady`/`SectionReady`/`FileReadyAck`/
  `SectionReadyAck`/`DirectoryEntry` 的 `to_bytes`/`from_bytes`：`struct.pack('<I')`
  → 3 字节小端）与 `core/protocol/asdu.py`（`ASDUBuilder.build_file_ready` /
  `build_section_ready` / `build_directory_entry` / `build_file_ready_ack` /
  `build_section_ready_ack` 的文档与长度常量）。
- 影响：与真机/第三方栈对不上字节（对方按 6/7/13 解析，本实现发 7/8/14）。**双方都改**
  才能互通；本仓库自身收发自洽，故单测不会暴露。

### 5.2 F_SG 多出「段号」字节，且 LOS 位置被占用
- 落点：`core/protocol/types.py::FileSegment`（去掉 `segment_number` 字段或不再编码它，
  `LOS=len(data)` 放到第 4 字节）与 `asdu.py::build_file_segment` 的形参。
- 影响：段数据在真机上会整体偏移 1 字节，且对端读到的"LOS"是段序号而非长度。

### 5.3 F_SC_NA_1 的 SCQ 取值表与 `handle_file_request` 分支
- 落点：`core/protocol/types.py::FileSelectCallGet.qualifier_str`
  （改为 1=SELECT_FILE、2=REQUEST_FILE、3=DEACTIVATE_FILE、4=DELETE_FILE、
  5=SELECT_SECTION、6=REQUEST_SECTION、7=DEACTIVATE_SECTION）与
  `core/protocol/file_transfer.py::FileTransferSlave.handle_file_request` 的分支。
- 影响：真机发 SCQ=4（删除文件）会被本实现当作"选择文件"并开始上送。
- 注：本仓库现有测试（`tests/test_file_transfer_upload.py`）按旧表编写，改表需同步调整。

### 5.4 字段命名与显示文案
- `LastSection.last_segment`/`status` → `lsq`/`chs`（`types.py`）；
- `core/protocol/io.py:238` 的 "最后段=… 状态=…" 显示文案应按 LSQ/CHS 重写，
  否则现场排查时会把校验和当状态看。

## 6. 真机联调验证建议（供后续执行）

1. 抓包抓一条 F_LS_NA_1，按 `type,vsq,cot,ca,ioa,nof(2),nos(1),lsq(1),chs(1)` 手工解一遍，
   确认末两字节确实是 LSQ（0-4）与校验和；
2. 请求一个**大于 2 段**的文件（>2×段长），观察对端 F_LS 的 LSQ 是否恒为 1/2；
3. 故意构造校验和错误，观察对端是否回 AFQ=2/4 及是否携带 FileError（验 4.1/4.2）；
4. 请求目录，记录对端所用 SCQ/NOF 组合（验 4.4）。
