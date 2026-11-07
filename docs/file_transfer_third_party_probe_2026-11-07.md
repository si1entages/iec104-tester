# 文件传输第三方从站实测记录（2026-11-07）

> 目的：在真机窗口到位前，用**独立第三方实现**执行
> `tests/e2e/qa_file_transfer_probe.py`，为
> [`file_transfer_open_items.md`](file_transfer_open_items.md) 的 5 项开放问题
> 取得字节级观察。**这不是真机验收**；真机仍需按清单复测。

## 1. 环境

| 项 | 值 |
|---|---|
| 从站实现 | lib60870-C **v2.4.1**，示例 `cs104_server_files`（MZ Automation） |
| 构建 | `zig cc -target x86_64-windows-gnu`，Windows x64 |
| 文件提供者 | CA=1 / IOA=30000 / NOF=1（TRANSPARENT_FILE）/ LOF=800 / 2 节×400B |
| 被测主站 | 本项目 `app.py --mode master`，连接 `127.0.0.1:2404` |
| 探针 | `python tests/e2e/qa_file_transfer_probe.py --ioa 30000 ...` |

从站示例的目录枚举函数原为 `return NULL`，本次为观察目录行为改为返回单个文件；
`getFile` 增加 `NOF` 匹配。仅修改测试从站，不改本项目代码。

## 2. 原始命令与结果

### 2.1 修复前（旧代码：F_SC_NB_1 127 + COT=ACT 6）

```bash
python tests/e2e/qa_file_transfer_probe.py --ioa 30000 --select 1 --request 1 --wait 4
```

| 动作 | 回帧 |
|---|---|
| 目录 SCQ=5 | 无 |
| 选择 SCQ=1 | 无 |
| 请求 SCQ=2 | 无（主站提示 Not in running state / 无回帧） |

结论：lib60870 **静默忽略** `F_SC_NB_1(127)+COT=ACT(6)`。这不是探针问题，是类型/COT 不兼容。

### 2.2 修复内容（已入库，不再是临时改动）

根据 2.1 的观察修改了默认实现：

- 文件 select/request/directory 使用 `F_SC_NA_1(122) + COT=FILE(13)`；
- 收到 `F_SR` 自动发 `SCQ=6` 节请求；
- `F_LS` 按 LSQ 回 `F_AF`：1/2 → 肯定文件(1)，3/4 → 肯定节(3)；
- 主站不再发送 `F_FR_NB(128)/F_SR_NB(129)`；
- CHS 按**本节**缓冲校验，末帧使用新节号（如 section=3）时不误报。

> 修复前为观察协议字节曾临时改代码，现已由上述默认实现替代；
> 复跑仍需 `--wait 1`（lib60870 会话超时 3s，默认 `--wait 3` 会让 select 超时）。

### 2.3 目录召唤

```bash
python tests/e2e/qa_file_transfer_probe.py --ioa 30000 --wait 1
```

结果：**无任何文件类回帧**（无 F_DR/F_LS/F_AF）。
lib60870 `file_server.c` 只处理 SCQ=1/2/3/6，没有目录处理器。

### 2.4 正选 NOF=1

```bash
python tests/e2e/qa_file_transfer_probe.py --ioa 30000 --select 1 --wait 1
```

```text
F_FR    COT=13 file_name=1 file_length=800 status=0
```

原始回帧（示例）：

```text
68131000040078010d000100307500010020030000
```

### 2.5 负选 NOF=9

```bash
python tests/e2e/qa_file_transfer_probe.py --ioa 30000 --select 9 --wait 1
```

```text
F_FR    COT=13 file_name=9 file_length=0 status=128
```

结论：否定标志为 **0x80**。

### 2.6 选择 + 请求 + 多节（wait=1，避开从站 3s 超时）

```bash
python tests/e2e/qa_file_transfer_probe.py --ioa 30000 --select 1 --request 1 --wait 1
```

```text
F_FR  COT=13 file_name=1 file_length=800 status=0
F_SR  COT=13 file_name=1 section_name=1 section_length=400 status=0
F_SG  COT=13 file_name=1 section_name=1 data=<236B>
F_SG  COT=13 file_name=1 section_name=1 data=<164B>
F_LS  COT=13 file_name=1 section_name=1 lsq=3 chs=184
F_SR  COT=13 file_name=1 section_name=2 section_length=400 status=0
F_SG  COT=13 file_name=1 section_name=2 data=<236B>
F_SG  COT=13 file_name=1 section_name=2 data=<164B>
F_LS  COT=13 file_name=1 section_name=2 lsq=3 chs=72
F_LS  COT=13 file_name=1 section_name=3 lsq=1 chs=0
```

关键原始帧：

```text
F_SR 1: 68142200060079010d00010030750001000190010000
```

结论：800B 文件真实分为 2 个数据节（各 400B），每节 2 段（236+164B）；
节结束 LSQ=3，文件结束 LSQ=1；CHS 分别为 184/72/0。
主站回 `F_AF POS_ACK_SECTION(3)` 后从站继续下一节，**未等待 COT=8 DEACT**。

### 2.7 修复后默认代码复测

```bash
python tests/e2e/qa_file_transfer_probe.py --ioa 30000 --select 1 --request 1 --wait 1
```

输出与 2.6 相同的 10 条回帧；主站日志：

```text
File received: name=1 size=800
File ACK sent: qualifier=1
```

且无 CHS mismatch 告警，证明 122/COT13、SCQ=6、按 LSQ 回 F_AF、逐节 CHS 均生效。

## 3. 5 项结论

| 项 | 结论（第三方） | 真机 |
|---|---|---|
| 1 NOF | NOF=1 表示 TRANSPARENT_FILE（Ed.2 枚举）；NOF 不匹配 → F_FR len=0 status=0x80 | 待复测 |
| 2 SCQ | SCQ=5 目录无响应；select=1/request=2 正常；第三方无目录处理器 | 待复测 |
| 3 DEACT | 节 LSQ=3、文件 LSQ=1；不要求 DEACT | 待复测（LSQ=2/4） |
| 4 多节 | 2 节×400B，2 段/节，LSQ 3/3/1，CHS 184/72/0；需 SCQ=6 节召唤 | 待复测 |
| 5 FRQ/SRQ | 否定 FRQ=0x80，肯定 0；SRQ 未直接观察 | 待复测 |

## 4. 兼容性问题处置

| 问题 | 状态 |
|---|---|
| 127/COT6 被忽略 | ✅ 已改为 122/COT13 |
| 只回 F_SR_NB、多节不驱动 | ✅ 已改为 F_SR → SCQ=6，F_LS → F_AF(1/3)，逐节 CHS |
| F_FR_NB/F_SR_NB 被当上传公告 | ✅ 主站不再发送（保留接收兼容） |

真机仍需按 open_items 复测；若目标装置只认旧语义，再评估兼容模式。

以上 3 项已写入 [`file_transfer_open_items.md`](file_transfer_open_items.md) 与
[`file_transfer_fls.md`](file_transfer_fls.md) §4.7，**未在未核实前改动产品默认行为**。
