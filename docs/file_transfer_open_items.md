# 文件传输 —— 真机核实清单（C4）

> 本文把 [`file_transfer_fls.md`](file_transfer_fls.md) §4 与
> [`user_guide.md`](user_guide.md) §11「已知限制」中的开放项收敛为**可执行的真机核实步骤**。
> **真机尚未到位；2026-11-07 已用第三方 lib60870-C v2.4.1 完成一轮实测并回填（见下），
> 真机窗口仍需按本清单复测。实现默认行为未据第三方单点证据改动。**
>
> 配套探针：`python tests/e2e/qa_file_transfer_probe.py`（只读；默认仅目录召唤）。
> 探针假定主站已 `--mode master` 连接真机并处于 Running。
>
> ## 2026-11-07 第三方实测（非真机）
>
> 环境：**lib60870-C v2.4.1** `cs104_server_files` 示例（Windows x64，zig cc 构建），
> 文件提供者 CA=1 / IOA=30000 / NOF=1（TRANSPARENT_FILE）/ LOF=800 / 2 节×400B。
> 目的：在无真机窗口时用独立实现获得字节级行为；完整原始记录见
> [`file_transfer_third_party_probe_2026-11-07.md`](file_transfer_third_party_probe_2026-11-07.md)。
> **真机结论仍需按本清单复测**。
>
> 修复前：本项目默认 `F_SC_NB_1(127)+COT=ACT(6)` 被 lib60870 静默忽略；
> 节流程只回 `F_SR_NB`、不发 SCQ=6，无法驱动多节。上述 3 个兼容性问题已在
> 2026-11-07 修复（见文末“已修复项”），**默认代码复测通过**：
> select/request → 2 节 × 400B → 文件接收完成（size=800）。
>
> **2026-11-07 v1.3.0 回归复测（第三方，非真机）**：前端依赖大版本升级后，
> 用同一 lib60870 从站重跑探针，回帧与首次一致（10 条 / 2 节×400B /
> LSQ 3,3,1 / CHS 184,72,0）；主站日志 `File received: name=1 size=800`，
> 无 CHS mismatch 告警。**真机仍未到位，本清单 5 项的真机结论保持“待复测”。**
>
> **2026-11-10 第二实现实测（lib60870.NET，非真机）**：改用 MZ Automation 官方
> C# 实现（`examples/cs104-server-file`，net8.0 + .NET SDK 8）补齐 lib60870-C
> 缺失的**目录状态机**，重点核实 §2 目录组合（本轮核心增量）+ §4 双节交叉验证；
> 完整记录见
> [`file_transfer_third_party_probe_2026-11-10_lib60870_net.md`](file_transfer_third_party_probe_2026-11-10_lib60870_net.md)。
> 要点：**目录口径 = `F_SC COT=REQUEST(5)` → `F_DR_TA_1 COT=5`（SQ=1 连续多对象 +
> SOF 携带 LFD），SCQ 值无关**；项目约定 `COT=13+SCQ=5` 对两个独立实现均无回帧；
> 未知 NOF 的否定形态为否定 F_SC + COT=47（≠C 轮的否定 F_FR 0x80）；双节
> 600+425 全链路 LSQ=3,3,1、CHS 76/157/233，节间不等 DEACT 主动推下一节
> （与 C 轮一致）。**新发现我方限制：主站 F_DR 多条目（SQ=1）只收第一条**
> （`process_file_transfer` 取 `objects[0]`），见文末关联待核实项。
> **真机仍未到位，本清单 5 项的真机结论保持“待复测”。**
>
> **2026-11-11 跨栈互操作基线就位（Docker 矩阵，非真机）**：WSL2 部署 Docker
> Engine 29.9.3 + [otfabric/iec104-interop](https://github.com/otfabric/iec104-interop)
> v0.6.0 已发布镜像（5 个独立栈：lib60870-C v2.4.1 / OpenMUC j60870 1.8.0 /
> wendy512 v1.0.4 / cB-Sigma v0.3.0 / part5 v0.3.0）。自测结果：
> 容器契约冒烟 5 适配器全绿；**跨栈全矩阵 25 客户端×服务端配对
> 3071 passed / 0 failed / 0 infra-error**（44 条已知上游差异、583 条能力未声明
> 跳过），覆盖文件下载/上传/目录（F_SC SCQ=0 COT=5 → F_DR_TA_1 + LFD）、
> 否定确认（COT 44~47）、未知 CA、非法 QOI/QCC、TLS(62351-3)、62351-5 应用层安全。
> 该矩阵是「全面功能测试」的常驻外部对端基线；本仓作为 consumer 接入
> （复用其镜像 + cases.tsv 向量映射为本仓断言）为后续工作。
> **真机仍未到位，本清单 5 项的真机结论保持“待复测”。**

## 0. 通用准备

1. 启动主站并连接被测装置：`python app.py --mode master --host <装置IP> --port 2404 --no-browser`
2. Wireshark 过滤（IEC 104 dissector）：
   - 文件类 ASDU：`iec60870_asdu.typeid >= 120 && iec60870_asdu.typeid <= 129`
   - 或按类型：`iec60870_asdu.typeid == 126 || iec60870_asdu.typeid == 123`
3. 运行探针：`python tests/e2e/qa_file_transfer_probe.py --ioa <IOA>`
4. 记录下表；每项结论写入「观察」列，并回填到 `file_transfer_fls.md` §4 对应小节。

## 1. NOF 语义（Ed.1「文件名」 vs Ed.2「文件类型」）

| 项 | 内容 |
|----|------|
| 当前实现 | `file_name` 当任意 16 位标识使用，内部自洽；语义未知 |
| 风险 | 若装置按 Ed.2 枚举解释（0=DEFAULT、1=TRANSPARENT、2=DISTURBANCE…），选择/请求的 NOF 取值需匹配其枚举，否则装置回否定 |
| 验证步骤 | 探针目录召唤 → 记录返回的 NOF 集合；对照装置手册/Ed.2 枚举 |
| 判定标准 | NOF 是否落在 {0,1,2,3,4}；是否连续/按文件递增；文档注明装置采用的版本 |
| 代码位置 | `core/protocol/types.py::FileReady/SectionReady/DirectoryEntry.file_name`；`core/protocol/file_transfer.py` |

**观察记录**：lib60870-C v2.4.1（第三方，非真机）；NOF=1（正选）/ 9（负选）。
- 正选 NOF=1 → `F_FR COT=13 file_name=1 file_length=800 status=0`；
- 负选 NOF=9 → `F_FR COT=13 file_name=9 file_length=0 status=128(0x80)`。
**结论**：该实现按 Ed.2 枚举解释 NOF（1=TRANSPARENT_FILE），选择时 NOF 必须与提供者一致；
本项目把 NOF 当任意 16 位标识可以传 1，但未做枚举校验/提示。真机需对照手册确认版本。

## 2. 目录请求的 SCQ/NOF 组合（本实现用 SCQ=5，项目约定）

| 项 | 内容 |
|----|------|
| 当前实现 | 主站发 `F_SC_NA_1 SCQ=5` 请求目录（`SCQ_REQUEST_DIRECTORY`），子站按 5 回目录；**标准表中 5 = SELECT_SECTION**，故为项目约定 |
| 风险 | 真机可能把 SCQ=5 理解为「选择节」而拒绝目录请求 |
| 验证步骤 | 探针目录召唤 → 看装置是否回 `F_DR_TA_1`（126）+ `F_LS_NA_1 LSQ=0` 终止标记；若回 `F_AF` 否定，记录 AFQ 值 |
| 判定标准 | 收到 ≥1 条 126 + 1 条 123(LSQ=0) = 组合可用；否则需改 `SCQ_REQUEST_DIRECTORY` 常量并重测 |
| 代码位置 | `core/protocol/types.py::SCQ_NAMES`；`file_transfer.py` 的 `SCQ_REQUEST_DIRECTORY` |

**观察记录**：lib60870-C v2.4.1；SCQ=5 目录召唤（无论 COT=6 还是 COT=13）**均无任何回帧**
（无 F_DR/F_LS/F_AF）；该实现的 file service 只处理 SCQ=1/2/3/6，**没有目录处理器**。
**结论**：SCQ=5 不是可移植的目录约定；第三方无法验证目录上送。select=1 / request=2 正常。
目录方式（SCQ/NOF/COT 组合）仍需真机确认，不能据第三方推断。

**观察记录 2（lib60870.NET，2026-11-10）**：目录触发的充分必要条件是
**`COT=REQUEST(5)`**（`FileServices.cs:1699`，SCQ 值不参与判断）；实测
COT=13/SCQ=5 无回帧（与 C 轮一致）、COT=5/SCQ=0 与 COT=5/SCQ=5 均回
`F_DR_TA_1 COT=5`（SQ=1 连续多对象、末条目 SOF 携带 LFD、条目带 CP56Time2a）。
**判定**：本实现已支持标准口径——探针 `--dir-cot 5`（`/api/master/file` body
`cot: 5`）即可触发；默认 `SCQ=5+COT=13` 保持不变（真机核实后再决定是否切默认值）。

## 3. WITH_DEACT 后续动作（LSQ=2/4 之后）

| 项 | 内容 |
|----|------|
| 当前实现 | 接收侧只按 LSQ 判定完成，不发送去激活（DEACT）；LSQ=1/3 视为无 DEACT |
| 风险 | 部分装置在 LSQ=2/4 后等待主站去激活，否则不释放文件句柄/不再响应后续请求 |
| 验证步骤 | 请求一个**整文件**（LSQ 预期=2）或**本节最后**（LSQ=4）的传输；观察装置在 LSQ 回帧后的行为：是否等待 COT=8（DEACT）？后续再发目录是否仍响应？ |
| 判定标准 | 「不发送 DEACT 也能继续对话」= 当前实现可接受；否则需补发 DEACT 流程 |
| 代码位置 | `core/protocol/file_transfer.py::handle_last_section`；`MasterEngine` 文件状态机 |

**观察记录**：lib60870-C v2.4.1；实测节结束 `F_LS LSQ=3`、文件结束 `F_LS LSQ=1`（未出现 2/4）；
主站回 `F_AF POS_ACK_SECTION(3)` 后，装置继续下一节并最终结束；**未观察到等待 COT=8 DEACT**。
**结论**：该实现不要求 DEACT；当前实现不补发 DEACT 可继续对话（针对 lib60870）。真机需按 LSQ=2/4 复测。

## 4. 多节流程（真正的多节累积/逐节校验）

| 项 | 内容 |
|----|------|
| 当前实现 | 管理器把整个文件按**单节**发送；多节累积/逐节校验未实现 |
| 风险 | 大文件（LOF 超过单节上限）的真实装置会分多节发送 `F_SR`/`F_SG`，当前实现无法完整接收/校验 |
| 验证步骤 | 请求大文件（如故障录波，LOF 较大）；观察 `F_SR`(121) 的 NOS 序列、`F_SG`(125) 的 LOS 长度、`F_LS`(123) 的 LSQ 序列与 CHS |
| 判定标准 | 若装置只发单节 → 当前实现可用；若多节 → 记录节数/每节长度/LSQ 组合，作为实现需求 |
| 代码位置 | `core/protocol/file_transfer.py`；`docs/file_transfer_fls.md` §5 |

**观察记录**：lib60870-C v2.4.1；LOF=800，2 个数据节×400B；每节 2 段（236B+164B）；
LSQ 序列：节1=3(CHS=184) → 节2=3(CHS=72) → 文件结束节3 LSQ=1(CHS=0)。
**结论（已修复）**：多节真实存在；主站现已自动执行
「F_SR → SCQ=6 → F_SG… → F_LS → F_AF(1/3)」，并按**本节**数据校验 CHS；
第三方 800B 文件默认代码复测 `File received: name=1 size=800`、无 CHS 告警。
从站侧仍按单节发送（多节分包未实现，非本次清单项）。

## 5. FRQ/SRQ 显示表（否定标志的位语义）

| 项 | 内容 |
|----|------|
| 当前实现 | 显示表用「最高位 0x80 = 否定 / 未就绪」（lib60870 口径）；Schneider 资料为「0=肯定 / 1=否定」 |
| 风险 | 否定场景下界面文案可能把「否定」显示成「肯定」 |
| 验证步骤 | 构造否定场景（请求不存在的 NOF，或目录/选择被拒）；记录 `F_FR`(120) 的 FRQ / `F_SR`(121) 的 SRQ 原始字节 |
| 判定标准 | 原值为 0x01 还是 0x80？据此统一显示表（`FRQ_NAMES`/`SRQ_NAMES`） |
| 代码位置 | `core/protocol/types.py::FRQ_NAMES/SRQ_NAMES`（如存在）；`docs/file_transfer_fls.md` §2.6 |

**观察记录**：lib60870-C v2.4.1；否定选择 NOF=9 → `F_FR status=128`，肯定 → `status=0`；
未构造出否定 F_SR，SRQ 未直接观察。
**结论**：该实现用 **最高位 0x80 = 否定**，与当前 `FRQ_NAMES/SRQ_NAMES` 的 lib60870 口径一致；
SRQ 可按同源处理，真机再补一次否定节场景。

## 附：关联待核实项（同源，非用户清单 5 项）

- **[2026-11-10 新增→已修复 `4bdb2c1`] 主站 F_DR 多条目只收第一条**：lib60870.NET
  目录回帧为 SQ=1 连续多对象（num=2，IOA 30000/30001），`process_file_transfer`
  只处理 `asdu.objects[0]` → 第二条目丢失。**已修复**：F_DR 分支遍历
  `asdu.objects`，回归用例以 lib60870.NET 实测帧为 golden（双条目全部上报）；
  同批修复：否定节就绪（F_SR SRQ=0x80）按标准中止（旧实现忽略 SRQ 继续请求
  不存在的节）；新增子站注入钩子（`inject_lsq`/`inject_srq_negative`，默认关闭）
  合成 §3 LSQ=2/4 与 §5 否定 F_SR 场景（两个 lib60870 实现均不产生这些路径），
  见 `tests/test_file_transfer_inject.py`。

- **CHS 校验和算法**：已按「本节所有段数据算术和 mod 256」实现（两个独立实现一致），
  真机验证方法见 `file_transfer_fls.md` §4.1；构造错误校验和观察对端是否回 AFQ=2/4。
- **否定确认是否携带 FileError**：见 §4.2；记录对端否定帧的信息体字节数即可判定。

## 结论回填模板

| 日期 | 装置型号/固件 | 项目 | 观察 | 结论 | 是否需要改代码 |
|------|---------------|------|------|------|----------------|
| 2026-11-07 | lib60870-C v2.4.1（第三方，非真机） | 1 NOF | 正选 NOF=1 → F_FR len=800 status=0；负选 NOF=9 → len=0 status=0x80 | Ed.2 枚举；NOF 必须匹配提供者 | 待真机（可加枚举提示） |
| 2026-11-07 | 同上 | 2 SCQ | SCQ=5 目录无回帧；select=1/request=2 正常 | SCQ=5 非可移植目录约定；第三方无目录处理器 | 待真机 |
| 2026-11-07 | 同上 | 3 DEACT | 节 LSQ=3 / 文件 LSQ=1；回 F_AF(3) 后继续；无 COT=8 等待 | 不要求 DEACT（针对 lib60870） | 否（对 lib60870） |
| 2026-11-07 | 同上 | 4 多节 | 800B / 2 节×400B / 每节 2 段（236+164）/ LSQ=3,3,1 / CHS=184,72,0 | 多节真实存在；已补 SCQ=6 节请求与逐节 CHS；默认代码复测接收完成 | ✅ 已改（主站） |
| 2026-11-07 | 同上 | 5 FRQ/SRQ | 否定 F_FR status=128(0x80)；肯定 0；SRQ 未观察 | 0x80=否定，与当前显示表一致 | 否 |

### 本轮已修复项（第三方实测暴露，默认代码已改）

1. ✅ **F_SC 类型/COT**：文件 select/request/directory 统一为
   `F_SC_NA_1(122)+COT=FILE(13)`；`F_SC_NB_1(127)` 仅保留解码兼容。
2. ✅ **多节驱动**：收到 `F_SR` 自动发 `F_SC(SCQ=6, NOS)`；`F_LS` 按 LSQ 回
   `F_AF(POS_ACK_FILE=1 / POS_ACK_SECTION=3)`；CHS 按本节段数据校验。
3. ✅ **旧确认类型**：主站不再发送 `F_FR_NB(128)/F_SR_NB(129)`（仍可接收旧对端）；
   lib60870 复测不再出现 `F_FR_NB COT=44`。

> 真机仍建议按本清单复测；若目标装置只认 127/旧 NB 语义，再评估兼容模式。
