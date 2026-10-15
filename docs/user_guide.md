# IEC 60870-5-104 测试工具 — 用户手册

## 目录

1. [简介](#1-简介)
2. [安装](#2-安装)
3. [快速开始](#3-快速开始)
4. [主站模式](#4-主站模式)
5. [子站模式](#5-子站模式)
6. [报文录制与回放](#6-报文录制与回放)
7. [网络异常模拟](#7-网络异常模拟)
8. [自动化测试](#8-自动化测试)
9. [配置说明](#9-配置说明)
10. [快捷键](#10-快捷键)
11. [已知限制与待核实项](#11-已知限制与待核实项)
12. [常见问题](#12-常见问题)

---

## 1. 简介

IEC 60870-5-104 测试工具是一款面向电力系统 SCADA 调试和测试的专业软件，支持：

- **主站模拟**：作为主站连接子站设备
- **子站模拟**：作为子站响应主站召唤
- **多站并发**：同时运行多个子站实例
- **报文分析**：实时解析和显示 IEC 104 报文
- **一致性测试**：符合 IEC 60870-5-104 Annex A 测试规范

### 功能特性

| 功能 | 说明 |
|------|------|
| 协议支持 | 59 种 ASDU 类型标识符，100% 覆盖 |
| 流控机制 | k/w 滑动窗口，符合标准要求 |
| 定时器 | t0/t1/t2/t3 四级超时管理 |
| 状态机 | STARTDT/STOPDT/TESTFR 完整生命周期 |
| 数据模拟 | 手动/自动遥信遥测变化 |
| 点表管理 | YAML 导入/导出，可视化编辑 |
| 报文录制 | 支持 .i104/.json 格式，可导出 **pcap/pcapng**（Wireshark 直接打开） |
| 网络模拟 | 丢包、延迟、乱序、损坏等异常 |
| TLS 传输加密 | 证书/CA 校验、双向认证（mTLS）；**仅传输层加密，不等于 IEC 62351 合规**（见 [`tls.md`](tls.md)） |
| 历史库 | 默认开启（SQLite 按角色分库），保留期/条数/容量三重清理，`--no-history` 关闭 |
| 非标 TypeID | YAML 注册厂商私有类型即可编解码往返（未注册按标准回 COT=42） |
| 文件传输 | F_FR/F_SR/F_SC/F_LS/F_AF/F_SG/F_DR，字节级语义经多实现交叉核实（见 [`file_transfer_fls.md`](file_transfer_fls.md)） |

---

## 2. 安装

### 环境要求

- Python 3.11 或更高版本
- 操作系统：Windows / Linux / macOS

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/yourname/iec104-tester.git
cd iec104-tester

# 安装依赖
pip install -r requirements.txt

# 开发环境（可选）
pip install pytest pytest-asyncio
```

### 打包产物（免安装 exe，可选）

不想装 Python 环境时，用 PyInstaller 打出的免安装目录：

```bash
pip install pyinstaller
python build/build_all.py              # 含前端构建（需 node/npm）
python build/build_all.py --skip-frontend   # 复用仓库内 webui/static/app 现有产物
python build/build_all.py --onefile    # 单文件形态
```

产物为 `dist/iec104-master/` 与 `dist/iec104-slave/` 两个目录（含前端、configs、
resources），双击其中 exe 即启动对应角色的 Web 服务（保留控制台查看启动提示）。
注意事项：

- Web 前端托管在 `/app/`（React/Vite 产物随 `webui/static` 打入包内）；
- 打包形态下历史库落在 **`dist/<角色>/_internal/data/history_<角色>.db`**
  （`_internal` 即打包后的"项目根"），`--no-history` / `--history-db` 照常可用；
- `run_multi_station.py` / `capture_tool.py` / `sim_tool.py` 等 CLI 工具**不在打包产物内**，
  需在源码环境运行。

### 验证安装

```bash
# 检查版本
python app.py --help

# 运行测试
python -m pytest tests/ -v
```

---

## 3. 快速开始

### 场景1：本地测试（主站+子站）

**终端1 — 启动子站：**

```bash
python app.py --mode slave --port 2404
```

**终端2 — 启动主站：**

```bash
python app.py --mode master --host 127.0.0.1 --port 2404
```

### 场景2：连接实际设备

```bash
# 连接子站设备
python app.py --mode master --host 192.168.1.100 --port 2404

# 使用自定义点表
python app.py --mode slave --point-table configs/demo_points.yaml
```

### 场景3：CLI 模式（无界面）

```bash
# 后台运行子站
python app.py --mode slave --no-gui --log-level DEBUG --log-file slave.log
```

---

## 4. 主站模式

### 界面布局

```
┌─────────────────────────────────────────────────────────────┐
│  工具栏：连接 | 断开 | 总召 | 累计召 | 时钟 | 复位 | 测试    │
├──────────┬──────────────────────────────────────────────────┤
│          │  数据表格                                        │
│  侧边栏  │  ┌──────┬──────┬──────┬──────┐                  │
│          │  │ 遥信 │ 遥测 │ 遥控 │ 遥脉 │                  │
│  连接状态 │  └──────┴──────┴──────┴──────┘                  │
│  通信统计 │                                                 │
│  序列号   ├──────────────────────────────────────────────────┤
│          │  底部面板                                        │
│          │  ┌──────────┬──────────┬──────────┐              │
│          │  │ 控制面板 │ 监控面板 │ 日志/报文 │              │
│          │  └──────────┴──────────┴──────────┘              │
└──────────┴──────────────────────────────────────────────────┘
```

### 主站工作台（新前端 `/app/`）

T10 起前端迁移到 React/Vite（托管于 `/app/`），主站工作台要点：

- **十万行虚拟滚动**：定义表用 `virtual` + 固定 `scroll.y`，只渲染可视窗口内的行，
  十万级点表不掉帧；过滤输入走低优先级更新
- **命令面板**：系统命令（STARTDT/总召/时钟/复位/测试…）、遥控（SBO 两段式/直发）、
  设点、读命令、参数、文件命令集中在一个面板
- **报文查看器**：I/S/U 帧实时列表，TypeID 中文摘要，十万行虚拟滚动
- **趋势图**：只采样**被订阅**的点位（全量采样会打满内存），环形缓冲
- 点值由 WebSocket 增量补丁/快照驱动，不做全量轮询

### 操作流程

1. **建立连接**
   - 点击工具栏 "连接" 或按 `F2`
   - 等待状态变为 "已连接"

2. **启动数据传输**
   - 自动发送 STARTDT（如果配置了 auto_start）
   - 或手动点击 "STARTDT"

3. **发送总召唤**
   - 点击 "总召" 或按 `F6`
   - 子站将上报所有数据

4. **查看数据**
   - 在数据表格中查看遥信/遥测值
   - 右键可导出为 CSV

5. **发送控制命令**
   - 切换到 "控制" 面板
   - 输入 IOA、状态等参数
   - 点击 "发送单命令" / "发送双命令"

### 命令说明

| 命令 | 快捷键 | 说明 |
|------|--------|------|
| STARTDT | F2 | 启动数据传输 |
| STOPDT | F3 | 停止数据传输 |
| 总召唤 | F6 | 召唤所有数据 |
| 累计量召唤 | F7 | 召唤累计量 |
| 时钟同步 | F8 | 同步时钟 |
| 复位进程 | F9 | 复位远端进程 |
| 测试命令 | F10 | 发送测试帧 |

---

## 5. 子站模式

### 界面布局

子站模式的界面与主站类似，但功能面板包含（新前端 `/app/`）：

- **手动置数**（ManualSetPanel）：按点位手动设置遥信/遥测/累计量值
- **应答行为**（ResponsePanel）：配置对主站命令的应答行为（见下文「响应注入」）
- **模拟面板**（SimulationPanel）：手动/自动数据变化
- **点表编辑**：可视化编辑点表

### 响应注入

侧栏「响应注入」卡片的选项会经 `POST /api/slave/response` 应用到 `SlaveEngine`（未启动时暂存，启动时生效）：

| 选项 | 效果 |
|------|------|
| GI 延迟 / 命令延迟 | 拉长总召唤、命令应答的响应时间（秒） |
| 丢帧率 | 按概率丢弃发出的帧；>0 即开启丢帧 |
| 不响应 | 对业务请求完全不回帧（文件传输除外） |
| 损坏帧 | 翻转发出帧的最后一个字节 |
| 返回错误COT | 应答的传送原因整体 **+1**（如 ACTCON 7→8、ACTTERM 10→11），用于验证主站对 COT 的严格校验与超时中止；自发上送与 COT 42/43/44 错误应答不受影响 |

例如：对点表中的遥控点下发命令，勾选「返回错误COT」后子站不再回合法确认，主站应在 t1 内判定选择失败并**不发送执行帧**。

### 界面设计依据（工业软件范式）

界面按 **ISA-101 高性能 HMI**（ANSI/ISA-101.01、ISA-TR101.02 技术报告）的通行做法设计，与西门子 TIA/WinCC、施耐德 Geo SCADA 等工程调试软件的风格一致：

| 范式 | 本工具落地 |
|------|-----------|
| 中性浅灰底 + 深色文字 | 窗口 `#f2f4f6`、面板白、文字 `#1f2933`；深色主题只适合低照度控制室，工程调试一律浅色 |
| 颜色是"例外"不是"装饰" | 彩色只用于状态（运行绿 / 停止红 / 警告橙）与信息类型标签，其余用灰阶 + 边框分层 |
| 数据用表格表达，不做花哨图形 | 点表全边框单元格、表头吸顶、数值等宽字体（tabular-nums）便于竖排比读 |
| 无渐变、无立体阴影、克制圆角 | 按钮/卡片扁平（圆角 3px），无阴影装饰 |
| 交互元素状态必须无歧义 | 禁用态显式灰化（不是只调透明度），焦点框可见；按钮可用性由服务端状态驱动 |
| 字段必须带标签，避免歧义 | 状态栏形如"状态 运行中 / 报文 TX 3 / RX 9 / 序号 VS/VR 1/7 窗口 0/12 / 点数 7" |

对齐约定：表头与单元格统一左对齐；数值列用等宽字体保证位数对齐。

### 按钮状态说明

顶部按钮的可用状态**始终跟随服务端真实状态**（状态栏左侧也会显示"未连接 / 连接中 / 运行中"）：

- 未启动：只能点「连接」/「启动监听」，「断开」/「停止」为灰色
- 已启动（含连接中）：只能点「断开」/「停止」，「连接」/「启动监听」为灰色

因此**刷新页面、或换个浏览器打开同一服务**时，按钮会立刻与后端对齐，不会出现"服务在运行但断开按钮点不了"的情况（该问题已修复）。若点击「连接」提示 `already running`，说明该服务端的会话已启动，直接点「断开」即可。

### 实时刷新与缓存

- 主站/子站点值**自动实时刷新**：页面收到报文或事件后，通过 WebSocket 向服务端要一次快照（最快 4 次/秒节流），只修补变化的单元格，不重建整表（滚动位置与按钮焦点不丢）。不需要手动刷新页面。
- **两个页面同时刷新**（双窗口联调必需，后台标签页也不会停）。
- 前端唯一入口是 `/app/`（React/Vite 产物；JS/CSS 为内容 hash 文件名，自带缓存破坏），
  服务端另对页面与资源返回 `Cache-Control: no-cache, must-revalidate` 协商缓存——
  前端改动重启服务后即可生效；若仍异常，先按 Ctrl+F5 强刷一次。

### 命令联动（真机语义）

子站按真实装置行为反映命令执行结果，无需额外配置：

| 命令 | 联动效果 | 上送类型 |
|------|----------|----------|
| 单命令（遥控） | 同 IOA 遥信变位（合/分） | `M_SP_TB_1`，COT=3（带时标突发） |
| 双命令（遥控） | 同 IOA 双点遥信变位（1=分/2=合） | `M_DP_TB_1`，COT=3 |
| 设点（遥调） | 同 IOA 遥测更新为目标值 | `M_ME_TF_1`，COT=3 |
| 升降（调节步） | 不联动（点表未建模档位点） | — |

说明：只有**点表里存在同 IOA 的被控点**时才联动；值未发生变化时不上送（与真机一致，不做无变化冗余上送）。上送类型由点表声明决定：遥信点 `type: double` → 双点上送，`type: single` → 单点上送。因此做"遥控 → 遥信变位"联调时，请把受控遥信与遥控点配成**同一 IOA**。

### 数据模拟

#### 手动模拟

1. 在 "模拟" 面板中输入 IOA
2. 点击 "置 ON" 或 "置 OFF" 改变遥信
3. 输入遥测值并点击 "设置遥测值"

#### 自动模拟

1. 勾选 "启用自动模拟"
2. 设置变化间隔和概率
3. 系统将自动产生随机数据变化

### 点表编辑

1. 切换到 "点表编辑" 面板
2. 添加/删除/修改点定义
3. 支持的点类型：
   - 遥信 (YX)：单点/双点
   - 遥测 (YC)：归一化/标度化/短浮点
   - 遥控 (YK)：单命令/双命令
   - 遥脉 (YM)：累计量

---

## 6. 报文录制与回放

### 录制报文

```bash
# Web UI 中点击工具栏 "录制" 按钮
# 或使用命令行：
python capture_tool.py record --mode master --host 127.0.0.1 -o session.i104
```

### 回放报文

```bash
# 原速回放
python capture_tool.py play session.i104

# 2倍速回放
python capture_tool.py play session.i104 --speed 2.0

# 单步模式
python capture_tool.py play session.i104 --step
```

### 分析报文

```bash
# 统计信息
python capture_tool.py analyze session.i104

# 显示帧内容
python capture_tool.py show session.i104 --limit 100 --filter "frame_type=I"

# 格式转换
python capture_tool.py convert session.i104 -o session.json

# 导出 Wireshark 可直接打开的 pcap/pcapng
python capture_tool.py convert session.i104 -o session.pcap
python capture_tool.py convert session.i104 -o session.pcapng
python capture_tool.py convert session.i104 -o session_raw.pcap --raw   # 裸 APDU(LINKTYPE_USER0)
```

> pcap 导出默认**合成以太网/IP/TCP 头**（目的端口 2404；IP 恒为 TEST-NET-1
> 192.0.2.0/24）以便 Wireshark 原生解析——该头部是**合成信息，非真实网络层数据**。
> 细节见 [`pcap_export.md`](pcap_export.md)。

---

## 7. 网络异常模拟

### 预设场景

| 预设 | 说明 |
|------|------|
| `clean` | 正常网络 |
| `poor_wifi` | WiFi 丢包，延迟 30ms±20ms，5% 丢包 |
| `congested` | 网络拥塞，延迟 100ms±50ms，10% 丢包 |
| `satellite` | 卫星链路，延迟 500ms±100ms，2% 丢包 |
| `unreliable` | 高丢包，30% 丢包，5% 损坏 |
| `intermittent` | 间歇性断连，5% 断连概率 |
| `slow_link` | 低带宽，1KB/s 限速 |
| `stress` | 综合压力测试 |

### 使用方法

```bash
# 使用预设
python sim_tool.py --preset poor_wifi --mode master --host 127.0.0.1

# 自定义参数
python sim_tool.py --loss 0.1 --delay 50 --corrupt 0.05 --mode master
```

### 参数说明

| 参数 | 说明 | 范围 |
|------|------|------|
| `--loss` | 丢包率 | 0.0 - 1.0 |
| `--delay` | 延迟(ms) | 0 - 1000 |
| `--corrupt` | 损坏率 | 0.0 - 1.0 |
| `--duplicate` | 重复率 | 0.0 - 1.0 |
| `--reorder` | 乱序率 | 0.0 - 1.0 |

---

## 8. 自动化测试

### 测试脚本格式

```yaml
name: basic_test
description: "基础连接和总召唤测试"
config:
  role: master
  timeout: 30
  connection: { host: "127.0.0.1", port: 2404 }

steps:
  - action: connect
    assert:
      - type: state
        params: { expected: "connected" }

  - action: wait_state
    params: { state: running, timeout: 10 }

  - action: general_interrogation
    assert:
      - type: frame_count
        params: { direction: tx, frame_type: I, min: 1 }

  - action: disconnect
```

### 运行测试

```bash
# 运行单个脚本
python run_tests.py tests/scripts/basic_connection_gi.yaml

# 运行目录下所有脚本
python run_tests.py tests/scripts/ -v

# 运行一致性测试
python tests/conformance/test_conformance.py
```

---

## 9. 配置说明

### 配置文件格式

```yaml
mode: master
connection:
  host: "192.168.1.100"
  port: 2404
  common_addr: 1
  reconnect: true
  reconnect_interval: 5.0
timers:
  t0: 30.0    # 连接建立超时
  t1: 15.0    # 发送/测试超时
  t2: 10.0    # 无数据确认超时
  t3: 20.0    # 空闲测试超时
flow_control:
  k: 12       # 最大未确认 I 帧数
  w: 8        # 确认阈值
master:
  auto_start: true   # 连接后自动 STARTDT
  auto_gi: false     # STARTDT 后自动总召
slave:
  spontaneous_enabled: true  # 启用突发上送
display:
  theme: dark
  refresh_interval_ms: 500
point_table:
  file: "configs/demo_points.yaml"
  auto_generate: true
  yx_count: 100
  yc_count: 50
  yk_count: 20
  ym_count: 10
history:              # 历史库，默认开启
  enabled: true       # false = 不建库（等价 --no-history）
  dir: ""             # 空 = <项目根>/data
  retention_days: 7   # 保留天数，<=0 不按时间清理
  max_size_mb: 512    # 容量上限(MB)，超出按最旧优先淘汰
  flush_interval: 5.0 # 后台批量落盘间隔(秒)
custom_types: []      # 非标准厂商私有 TypeID，见 configs/custom_types_example.yaml
tls:                  # TLS 传输层加密，默认关闭
  enabled: false
  certfile: ""        # 本端证书 (PEM)
  keyfile: ""         # 私钥；空 = 与证书同文件
  cafile: ""          # 受信 CA；空 = 系统信任库
  verify: true        # 主站是否校验服务端证书
  verify_client: false  # 子站是否要求客户端证书（双向认证）
  server_hostname: "" # 主站主机名校验用域名
```

### TLS 加密

子站启用 TLS：

```bash
python app.py --mode slave \
  --tls --tls-cert certs/server.pem --tls-key certs/server.key
```

主站严格校验服务端证书：

```bash
python app.py --mode master --tls --tls-ca certs/ca.pem --tls-hostname iec104.local
```

自签证书联调可加 `--no-verify` 跳过校验（**生产禁用**）。

> ⚠ **覆盖边界**：本功能**只做 TLS 传输层加密**，**不是"IEC 62351 合规"**。
> IEC 62351 的应用层认证、安全关联、访问控制、证书吊销等**均未实现**。
> 证书生成、常见错误排查与完整边界清单见 [`docs/tls.md`](tls.md)。

### 历史库

历史库**默认开启**，落盘到 `<项目根目录>/data/history_<角色>.db`
（主站 `history_master.db` / 子站 `history_slave.db`，避免两个角色共用同一目录时
数据混淆与互相清理）；`--no-history` 可临时关闭，`--history-db <path>` 可指定文件。

主站 Web 8765 与子站 Web 8766 可同时运行，各自写自己的库文件。
Web 模式与 headless/CLI 模式都会把收发报文落盘。

清理策略：保留期（`retention_days`）+ 记录条数 + 容量上限（`max_size_mb`），
刷盘间隔由 `flush_interval` 控制。

容量/写放大实测：**写放大约 3.4×~4.3×，单条记录约 96 B，100 万条 ≈ 91 MiB**，
默认 512 MB 上限约可容纳 550 万条。并发写实测：**8 个进程共享同一库文件写
2.4 万条，零失败零丢失**。完整数据、结论与复现脚本见
[`docs/history.md`](history.md)。

### 非标准厂商私有 TypeID

现场设备的私有 TypeID 默认会触发 `COT=42`（未知类型标识）错误应答。
在配置里登记其数据结构后即可正常编解码往返：

```yaml
custom_types:
  - type_id: 130          # 须是标准 72 类型之外的空闲 ID
    name: VendorAlarm
    fields:
      - {name: level, type: u8}
      - {name: value, type: i16}
      - {name: qds,   type: qds}     # 品质描述词(1B)
      - {name: ts,    type: cp56}    # CP56Time2a 时标(7B)
```

完整字段类型表、写法说明与可用 ID 区间见
[`configs/custom_types_example.yaml`](../configs/custom_types_example.yaml)。

### 多站配置

```yaml
stations:
  - station_id: "substation_a"
    station_name: "110kV 变电站 A"
    port: 2404
    common_addr: 1
    auto_generate: true
    yx_count: 100
    yc_count: 50

  - station_id: "substation_b"
    station_name: "35kV 变电站 B"
    port: 2405
    common_addr: 2
    auto_generate: true
    yx_count: 50
    yc_count: 30
```

---

## 10. 快捷键

### 文件操作

| 快捷键 | 功能 |
|--------|------|
| Ctrl+O | 加载配置 |
| Ctrl+S | 保存配置 |
| Ctrl+Q | 退出 |

### 编辑操作

| 快捷键 | 功能 |
|--------|------|
| Ctrl+L | 清空日志 |
| Ctrl+Shift+L | 清空报文 |
| Ctrl+F | 搜索 |

### 视图操作

| 快捷键 | 功能 |
|--------|------|
| Ctrl+B | 切换侧边栏 |
| F5 | 刷新 |

### 主站命令

#### 点位自学习（自动补点）

主站收到数据报文（突发/召唤/SOE 等）后，会把**报文里出现、定义表里没有的 IOA 自动补进定义表**：

- 单点/双点遥信（`M_SP_*` / `M_DP_*`）→ 遥信点位，命名 `遥信<IOA>`
- 归一化/标度化/短浮点遥测（`M_ME_*`）→ 遥测点位，命名 `遥测<IOA>`
- 累计量（`M_IT_*`）→ 遥脉点位，命名 `遥脉<IOA>`

因此**不需要预先手工配置对端全部点位**——连上真机做一次总召唤，点位和值就会出现在主站定义表中。补点行为默认开启（`MasterEngine(auto_add_points=True)`），关闭后只入实时库、不显示。

#### 周期总召唤

主站页顶部有「周期总召(秒)」输入框（连接时生效，0=关闭）。部分装置**从不自发上送遥测**——实测某真机静默 70 秒内只有遥信与 SOE，零遥测帧，只有收到总召唤时才回遥测数据。这类装置必须靠周期总召刷新遥测值。

- 开启后主站按设定间隔自动发总召唤（仅在 Running 状态，异常不影响连接）
- 实测：设 20 秒后，80 个遥测点在 45 秒内全部刷新（如 16385: 49 → -35）
- 若装置对总召唤应答不稳定（只回 ACTCON 或回"初始化结束"），可加大间隔

#### IOA 写法注意事项

全工具的 IOA 一律按**十进制**表示（点表 YAML、界面、实时库）。IEC 104 标准本身**不规定**遥信/遥测的地址范围——IOA 是 24 位整数（0～16777215），如何分段是各项目/厂家的约定（常见做法：遥信低段、遥测/累计量高段）。写点表时注意进制：

- 设备报文里 IOA=0x4001，对应十进制 **16385**；在点表里写 `4001` 是十进制四千零一（0x0FA1），两者不是同一个点
- YAML 点表也支持十六进制字面量 `0x4001`（解析为 16385），与设备侧文档对照时务必确认进制

### 主站命令

| 快捷键 | 功能 |
|--------|------|
| F2 | STARTDT |
| F3 | STOPDT |
| F6 | 总召唤 |
| F7 | 累计量召唤 |
| F8 | 时钟同步 |
| F9 | 复位进程 |
| F10 | 测试命令 |

---

## 11. 已知限制与待核实项

### 文件传输（详见 [`file_transfer_fls.md`](file_transfer_fls.md)）

以下开放项**未臆测实现**，待标准正文或真机联调确认：

- **NOF 语义**：Ed.1「文件名」vs Ed.2「文件类型」，目标装置用哪版未知；
- **目录请求的 SCQ/NOF 组合**：本实现用 **SCQ=5 触发目录上送，是项目约定值**
  （标准表 5=`SELECT_SECTION`），主/子站内部已闭环，真机联调后定夺（§4.4）；
- **`WITH_DEACT` 后续动作**：LSQ=2/4 是否必须回去激活确认，未实现；
- **多节流程**：管理器把整个文件按单节发送，真正的多节累积/逐节校验未实现；
- **FRQ/SRQ 显示表**：`FileReady`/`SectionReady` 的状态显示文案仍是旧表
  （两处依据有出入：Schneider「0=肯定/1=否定」vs lib60870「最高位 0x80=否定」），待真机确认。

### 平台与打包

- ~~`run_multi_station.py` 在 Windows 上不可用~~ **已修复**：信号处理按平台守卫
  （Windows 上 `add_signal_handler` 未实现 → 回退 `signal.signal` +
  `call_soon_threadsafe`），Ctrl+C 优雅停止、退出码 0、端口正常回收，
  Windows 实测通过；多站能力本身（`MultiStationManager`）与 Web 多站页不受影响；
- 打包形态下历史库落在 `dist/<角色>/_internal/data/`（见 §2「打包产物」）；
- CLI 工具（run_multi_station/capture_tool/sim_tool）不在打包产物内，需源码环境运行。

### 冗余双通道（主站）

主站支持**冗余双通道**（T21）：主/备两条独立 TCP 连接指向两个冗余前置机，同一时刻
仅一条活动收发；主用断链自动切换到已预连接（TCP+STARTDT）的备用通道，进入 Running
后自动补发总召唤；原主用恢复后自动降为新备用（不抢占）。应用层按 ASDU 摘要在切换
窗口内去重（传输层 I 帧序列号照常）。

```yaml
redundancy:
  enabled: true
  standby_host: "192.168.1.101"   # 备用前置机
  standby_port: 2404
  switch_timeout: 10.0            # 切换后等待 Running 的超时（秒）
  dedup_window: 5.0               # 切换窗口去重时长（秒）
```

配置无效（备用地址空/端口非法/备用=主用）构造即抛 `ValueError`，不做静默降级。
模型与未覆盖部分详见 [`redundancy.md`](redundancy.md)。

---

## 12. 常见问题

### Q: 连接失败怎么办？

A: 检查以下项：
1. 确认 IP 地址和端口正确
2. 确认网络可达（ping 测试）
3. 确认防火墙未阻止
4. 查看日志中的错误信息

### Q: 数据不更新？

A: 可能原因：
1. 未发送总召唤
2. 点表配置错误
3. 公共地址不匹配

### Q: 如何录制报文？

A: 两种方式：
1. Web UI 中点击工具栏 "录制" 按钮
2. 命令行使用 `capture_tool.py record`

### Q: 如何模拟网络异常？

A: 使用 `sim_tool.py`：
```bash
python sim_tool.py --preset poor_wifi --mode master
```

### Q: 测试脚本如何编写？

A: 参考 `tests/scripts/` 目录下的示例，使用 YAML 格式定义测试步骤和断言。

---

## 技术支持

- 项目地址：https://github.com/yourname/iec104-tester
- 问题反馈：https://github.com/yourname/iec104-tester/issues
