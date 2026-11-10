# 文件传输第三方探针报告 — lib60870.NET（2026-11-10）

> 对齐 [`file_transfer_third_party_probe_2026-11-07.md`](file_transfer_third_party_probe_2026-11-07.md)
> 的结构。本轮目标是 T50/C4 §2「目录请求」——lib60870-C v2.4.1 的文件服务目录分支
> 是 `/* TODO send directory */`（`file_server.c:851-855`，实测无任何回帧），必须换
> 有目录状态机的实现才能产生第三方证据。
>
> **仍然不是真机**：本报告所有结论归属「第三方」列；真机列保持「待复测」。

## 1. 环境

| 项 | 值 |
|---|---|
| 从站实现 | lib60870.NET（MZ Automation 官方 C# 实现，GPL-3.0），master 分支 @ 2026-11-10 clone |
| 示例 | `examples/cs104-server-file`（TargetFramework net8.0） |
| 构建 | .NET SDK 8.0.427（winget `Microsoft.DotNet.SDK.8`）；需 `dotnet nuget add source https://api.nuget.org/v3/index.json`（机器原本无 NuGet 源） |
| 测试改造 | **仅改测试从站**：IOA 30000 改为双节文件（600+425=1025B），IOA 30001 保持单节（上传白名单） |
| 被测主站 | 本项目 `app.py --mode master` 连 `127.0.0.1:2404`（CA=1） |
| 探针 | `python tests/e2e/qa_file_transfer_probe.py`（本轮新增 `--dir-cot/--dir-scq`，见 §5） |

## 2. §2 目录请求 — 组合矩阵（本轮核心增量）

我们主站原实现只有 `F_SC COT=13(FILE)+SCQ=5` 一种组合（项目约定值）。本轮给主站
加了可选 `cot/qualifier` 覆盖（默认行为不变），实测三种组合：

| 组合（COT/SCQ） | 从站回帧 | 结论 |
|---|---|---|
| **13 / 5**（项目约定） | **无任何回帧** | lib60870.NET 服务端 F_SC 分支只认 `COT==FILE_TRANSFER` 且 SCQ∈{1,2,3,6}；SCQ=5 无匹配 → 静默丢弃。与 lib60870-C 行为一致 |
| **5 / 0**（Ed.2/otfabric 口径） | `F_DR_TA_1 COT=5` | 服务端 `else if (asdu.Cot == CauseOfTransmission.REQUEST)` → `FilesAvailable.SendDirectoy`（`FileServices.cs:1699-1701`）。**SCQ 值不参与判断** |
| **5 / 5** | 同上（完全相同） | 证实 SCQ 与目录触发解耦 |

**F_DR_TA_1 回帧结构**（从站侧 SEND 日志逐字节核对，41B）：

```
68 27 | 00 00 04 00 | 7E 82 05 00 01 00 | ...
type=126(F_DR_TA_1) VSQ=0x82 → SQ=1(连续), num=2
COT=5(REQ) PN=0 T=0 OA=0 CA=1
条目1: IOA=30000 NOF=1 LOF=1025 SOF=0x00 + CP56Time2a(7B)
条目2: SQ=1 连续 → IOA 隐含 30001, NOF/LOF/SOF/CP56（无重复 IOA 字段）
```

三条硬结论：

1. **目录回帧形态 = `F_SC COT=REQUEST(5)` → `F_DR_TA_1 COT=REQUEST(5)`，SQ=1 连续多对象、
   末条目 SOF 携带 LFD**——与本仓「SCQ=5 项目约定」完全不同的路径，且被两个独立
   实现（otfabric 矩阵 + 本轮）一致采用，可认定为事实上的互操作口径。
2. **否定形态与 lib60870-C 不同**：对未知 NOF/IOA（select NOF=9），.NET 回
   **否定 F_SC 原样回显 + COT=47（UNKNOWN_INFORMATION_OBJECT_ADDRESS）**
   （从站日志 `7A-01-2F-00...`）；lib60870-C 回的是否定 F_FR（LOF=0, status=0x80）。
   两种都是标准允许的否定路径——主站两条都要能处理（当前都能：COT=47 走通用
   否定应答路径、F_FR status=0x80 走 FRQ 显示）。
3. **发现我方主站限制（真实缺陷，非本轮引入）**：`process_file_transfer` 只处理
   `asdu.objects[0]`（`master_protocol.py:563`）→ **SQ=1 多条目目录只见到第一条**。
   本仓从站逐条目分帧发送所以从未暴露；对端合并发送即丢条目。已记录
   `open_items.md` §2；修复建议：F_DR 分支遍历 `asdu.objects`。

## 3. §4 多节流程 — 第二实现交叉证据

IOA 30000 = 双节文件（600+425）。`select(1) → request(1)` 后主站自动链式完成
（探针 `--wait 1`；对齐 lib60870 家族 3s 文件会话超时，间隔过长会「Unexpected
FILE CALL」无回帧——与 2026-11-07 `--wait 1` 约束一致）：

```
F_FR  COT=13 NOF=1 LOF=1025 status=0        ← 选择正面
F_SR  NoS=1 size=600  status=0              ← SCQ=2 请求文件后
F_SG  NoS=1 ×3（236+236+128=600）
F_LS  NoS=1 LSQ=3 CHS=76                    ← 节 1 结束（section end）
F_SR  NoS=2 size=425 status=0               ← 服务器主动推下一节！
F_SG  NoS=2 ×2（236+189=425）
F_LS  NoS=2 LSQ=3 CHS=157                   ← 节 2 结束
F_LS  NoS=3 LSQ=1 CHS=233                   ← 文件结束哨兵（NoS 越界节号）
```

与 lib60870-C（2 节×400B，LSQ=3,3,1、CHS=184,72,0）**序列形态完全一致**：

- LSQ=3（section end）→ 服务器不等主站 F_AF/DEACT **主动推下一节 F_SR**
  → §3「WITH_DEACT 后续动作」再次实证：**该实现不使用 LSQ=2/4**，
  也不等待 COT=8（两个 lib60870 实现一致）。
- CHS 逐节校验（76/157/233）无告警 → 算法口径再次吻合。
- 我方主站的 F_AF（节确认/文件确认）按现有时序事后到达，未阻塞流程。

## 4. 其余观察

- **上传方向未测**：本仓主站无上传 API（file_action 仅 directory/select/request）；
  从站侧 `SetFileReadyHandler` 白名单 IOA=30001 接收上传的路径留待后续（otfabric
  矩阵已覆盖该方向，见第二步计划）。
- select 后等待过久（>3s）再 request → 服务器状态已超时复位 → 无回帧。
  探针本轮默认 `--wait 3` 会踩中，已实测确认需 `--wait 1`（与 C 轮一致）。

## 5. 本轮产品改动（最小、向后兼容）

| 文件 | 改动 |
|---|---|
| `core/protocol/asdu.py` | `build_call_directory` 增 `cot` 参数（默认 `COT.FILE` 不变），golden 用例锁死 3 组编码 |
| `core/engine/master_protocol.py` / `core/engine/master.py` | `file_call_directory` 透传 `cot/qualifier`（默认 = 项目约定，行为不变） |
| `webui/server.py` / `bridge.py` / `session.py` | `/api/master/file` 可选 `cot`（限 5/6/13）与 `qualifier`（0~7）字段，仅目录动作生效 |
| `tests/e2e/qa_file_transfer_probe.py` | 新增 `--dir-cot`（5/6/13）/`--dir-scq`（0~7），默认值 = 项目约定 |

## 6. 结论回填（对照 open_items 清单）

| 项 | 第三方列（本轮新增证据） | 真机列 |
|---|---|---|
| §1 NOF 语义 | +lib60870.NET：未知 NOF → 否定 F_SC COT=47（≠C 轮的否定 F_FR 0x80） | **待复测** |
| §2 目录 SCQ/NOF | **首次闭环**：COT=13/SCQ=5 无回帧；`COT=REQUEST(5)` 触发 F_DR_TA_1（SQ=1 多对象+LFD），SCQ 无关 | **待复测** |
| §3 WITH_DEACT | +.NET：仍仅 LSQ=3/1，不等 DEACT 主动推节（与 C 轮一致） | **待复测** |
| §4 多节流程 | +.NET：双节 600+425 全链路 LSQ=3,3,1、CHS 76/157/233，无告警 | **待复测** |
| §5 FRQ/SRQ 否定 | 未构造出否定 F_SR（.NET 服务端也无该路径）——待自定义注入 | **待复测** |

新发现的我方待办：**F_DR 多条目（SQ=1）主站只收第一条**（见 §2 结论 3）——
已加入 `open_items.md` 关联待核实项。
