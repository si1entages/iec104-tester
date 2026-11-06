# 文件传输 —— 真机核实清单（C4）

> 本文把 [`file_transfer_fls.md`](file_transfer_fls.md) §4 与
> [`user_guide.md`](user_guide.md) §11「已知限制」中的开放项收敛为**可执行的真机核实步骤**。
> **当前环境无真机，以下结论均为「待核实」，实现未臆测改动。**
>
> 配套探针：`python tests/e2e/qa_file_transfer_probe.py`（只读；默认仅目录召唤）。
> 探针假定主站已 `--mode master` 连接真机并处于 Running。

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

**观察记录**：装置型号/固件 ______；NOF 集合 ______；结论 ______

## 2. 目录请求的 SCQ/NOF 组合（本实现用 SCQ=5，项目约定）

| 项 | 内容 |
|----|------|
| 当前实现 | 主站发 `F_SC_NA_1 SCQ=5` 请求目录（`SCQ_REQUEST_DIRECTORY`），子站按 5 回目录；**标准表中 5 = SELECT_SECTION**，故为项目约定 |
| 风险 | 真机可能把 SCQ=5 理解为「选择节」而拒绝目录请求 |
| 验证步骤 | 探针目录召唤 → 看装置是否回 `F_DR_TA_1`（126）+ `F_LS_NA_1 LSQ=0` 终止标记；若回 `F_AF` 否定，记录 AFQ 值 |
| 判定标准 | 收到 ≥1 条 126 + 1 条 123(LSQ=0) = 组合可用；否则需改 `SCQ_REQUEST_DIRECTORY` 常量并重测 |
| 代码位置 | `core/protocol/types.py::SCQ_NAMES`；`file_transfer.py` 的 `SCQ_REQUEST_DIRECTORY` |

**观察记录**：装置响应 COT______；F_DR 条数 ______；终止标记 LSQ ______；AFQ（如有）______

## 3. WITH_DEACT 后续动作（LSQ=2/4 之后）

| 项 | 内容 |
|----|------|
| 当前实现 | 接收侧只按 LSQ 判定完成，不发送去激活（DEACT）；LSQ=1/3 视为无 DEACT |
| 风险 | 部分装置在 LSQ=2/4 后等待主站去激活，否则不释放文件句柄/不再响应后续请求 |
| 验证步骤 | 请求一个**整文件**（LSQ 预期=2）或**本节最后**（LSQ=4）的传输；观察装置在 LSQ 回帧后的行为：是否等待 COT=8（DEACT）？后续再发目录是否仍响应？ |
| 判定标准 | 「不发送 DEACT 也能继续对话」= 当前实现可接受；否则需补发 DEACT 流程 |
| 代码位置 | `core/protocol/file_transfer.py::handle_last_section`；`MasterEngine` 文件状态机 |

**观察记录**：末帧 LSQ ______；装置是否等待 DEACT ______；再发目录是否正常 ______

## 4. 多节流程（真正的多节累积/逐节校验）

| 项 | 内容 |
|----|------|
| 当前实现 | 管理器把整个文件按**单节**发送；多节累积/逐节校验未实现 |
| 风险 | 大文件（LOF 超过单节上限）的真实装置会分多节发送 `F_SR`/`F_SG`，当前实现无法完整接收/校验 |
| 验证步骤 | 请求大文件（如故障录波，LOF 较大）；观察 `F_SR`(121) 的 NOS 序列、`F_SG`(125) 的 LOS 长度、`F_LS`(123) 的 LSQ 序列与 CHS |
| 判定标准 | 若装置只发单节 → 当前实现可用；若多节 → 记录节数/每节长度/LSQ 组合，作为实现需求 |
| 代码位置 | `core/protocol/file_transfer.py`；`docs/file_transfer_fls.md` §5 |

**观察记录**：文件 LOF ______；节数 ______；每节段数 ______；LSQ 序列 ______

## 5. FRQ/SRQ 显示表（否定标志的位语义）

| 项 | 内容 |
|----|------|
| 当前实现 | 显示表用「最高位 0x80 = 否定 / 未就绪」（lib60870 口径）；Schneider 资料为「0=肯定 / 1=否定」 |
| 风险 | 否定场景下界面文案可能把「否定」显示成「肯定」 |
| 验证步骤 | 构造否定场景（请求不存在的 NOF，或目录/选择被拒）；记录 `F_FR`(120) 的 FRQ / `F_SR`(121) 的 SRQ 原始字节 |
| 判定标准 | 原值为 0x01 还是 0x80？据此统一显示表（`FRQ_NAMES`/`SRQ_NAMES`） |
| 代码位置 | `core/protocol/types.py::FRQ_NAMES/SRQ_NAMES`（如存在）；`docs/file_transfer_fls.md` §2.6 |

**观察记录**：否定时 FRQ=______；SRQ=______；最终采用口径 ______

## 附：关联待核实项（同源，非用户清单 5 项）

- **CHS 校验和算法**：已按「本节所有段数据算术和 mod 256」实现（两个独立实现一致），
  真机验证方法见 `file_transfer_fls.md` §4.1；构造错误校验和观察对端是否回 AFQ=2/4。
- **否定确认是否携带 FileError**：见 §4.2；记录对端否定帧的信息体字节数即可判定。

## 结论回填模板

| 日期 | 装置型号/固件 | 项目 | 观察 | 结论 | 是否需要改代码 |
|------|---------------|------|------|------|----------------|
| | | 1 NOF | | | |
| | | 2 SCQ | | | |
| | | 3 DEACT | | | |
| | | 4 多节 | | | |
| | | 5 FRQ/SRQ | | | |
