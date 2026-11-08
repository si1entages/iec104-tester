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
13. [诊断包导出](#13-诊断包导出)

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
| 协议支持 | 72 种 ASDU 类型标识符，全部可构造/可解码 |
| 流控机制 | k/w 滑动窗口，符合标准要求 |
| 定时器 | t0/t1/t2/t3 四级超时管理 |
| 状态机 | STARTDT/STOPDT/TESTFR 完整生命周期 |
| 数据模拟 | 手动/自动遥信遥测变化 |
| 点表管理 | YAML 导入/导出，可视化编辑；**SCD/CID/ICD 导入**（IEC 61850-80-1 映射 + CDC 推断，预览后应用） |
| 报文录制 | 支持 .i104/.json 格式，可导出 **pcap/pcapng**（Wireshark 直接打开） |
| 透明桥 | `--mode bridge`：真实主站 ↔ 测试器 ↔ 真实子站，字节级透传 + 双向帧旁路解码/录制（现场排障不动既有系统） |
| 网络模拟 | 丢包、延迟、乱序、损坏等异常（Web 状态页卡片 + CLI `sim_tool.py`） |
| TLS 传输加密 | 证书/CA 校验、双向认证（mTLS）；**仅传输层加密，不等于 IEC 62351 合规**（见 [`tls.md`](tls.md)） |
| 历史库 | 默认开启（SQLite 按角色分库），保留期/条数/容量三重清理，`--no-history` 关闭；Web「历史」页可查询与导出 |
| 非标 TypeID | YAML 注册厂商私有类型即可编解码往返（未注册按标准回 COT=42） |
| 文件传输 | F_FR/F_SR/F_SC/F_LS/F_AF/F_SG/F_DR，字节级语义经多实现交叉核实（见 [`file_transfer_fls.md`](file_transfer_fls.md)） |
| 界面语言 | 中/英切换（头部「中 / EN」，记忆偏好）；**全站双语**（外壳、主站/子站/多站工作台、状态/日志/历史、网络模拟、认证），`npm run i18n:inventory` 清单为 0 |

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

不想装 Python 环境时，用 PyInstaller 打出的免安装产物。**主站/子站不再各打一个 exe**，
统一为一个 `iec104-tester`：

```bash
pip install pyinstaller
python build/build_all.py              # 含前端构建（需 node/npm），产出 dist/iec104-tester/
python build/build_all.py --skip-frontend   # 复用仓库内 webui/static/app 现有产物
python build/build_all.py --onefile    # 单文件形态 dist/iec104-tester.exe
```

运行方式：

- **双击 exe**：默认同时启动主站+子站，只打开**一个页面**；左侧「主站工作台 /
  子站工作台」两个菜单，点哪个就在同一页面显示哪个，按需使用；
- **命令行**：
  ```bash
  iec104-tester                         # 默认 both：单进程双角色、一个 8765 端口
  iec104-tester --mode master          # 只启动主站 UI，默认 8765
  iec104-tester --mode slave           # 只启动子站 UI，默认 8766
  iec104-tester --mode both            # 显式单进程双角色（一个 HTTP 端口）
  iec104-tester --mode master --no-browser --http-port 8765
  ```
- `--mode both` 只打开一个网页、只占一个 HTTP 端口；页内左侧菜单切换主站/子站，
  Ctrl+C 或关闭控制台统一停止进程。
- 单角色模式（`--mode master` / `--mode slave`）只创建该角色的引擎。
- `--no-gui` 无 `--mode` 时默认主站；其它非交互环境（CI/服务）无 `--mode` 时默认 both。

注意事项：

- Web 前端托管在 `/app/`（React/Vite 产物随 `webui/static` 打入包内）；
- 合并模式下主站 API 在 `/api/*`，子站 API/WS 挂在 `/slave/api/*`、`/slave/ws`；
  两个角色在同一进程内各持独立 `EngineBridge`（引擎/历史库/日志隔离），
  页面不再使用 iframe；
- 打包形态下历史库按角色分文件：onedir 为
  `dist/iec104-tester/_internal/data/history_<角色>.db`，onefile 为当前工作目录下的
  `data/history_<角色>.db`；`--no-history` / `--history-db` 照常可用；
- `--mode both` 若显式传 `--history-db`，会自动加 `_master` / `_slave`
  后缀，避免两个角色写同一个文件；
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

### 场景0：一键环回演示（推荐首次体验）

```bash
python app.py --demo
```

本机以单进程双角色启动（自动选空闲 HTTP 端口），自动完成
「子站监听 → 主站连接 → 总召」，并打开工作台。历史库在演示模式下关闭；
`Ctrl+C` 停止进程。

```bash
# 30 秒后自动停止（适合录屏/CI）
python app.py --demo --demo-seconds 30 --no-browser
```

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

### 场景3.5：透明桥排障（现场旁路观察，T73）

不动既有主站/子站的任何配置：桥监听一个口，**主站改连桥**，桥把流量字节级
透传给真实子站，同时旁路解码双向帧（每帧打点日志：方向 + APCI/ASDU 摘要），
可选 `--capture-file` 录制（支持 .json/.pcap，Wireshark 可开）：

```bash
python app.py --mode bridge --listen-port 2404 \
    --upstream-host 192.168.1.9 --upstream-port 2404 \
    --capture-file bridge.pcap --log-file bridge.log
```

- 转发永远优先于观察：帧解析失败只影响日志/录制完整性，**不影响透传**；
- 多主站可同时各占一条上游连接；上游不可达时客户端连接被立即关闭，
  由主站按既有重连逻辑重试；
- Web UI 桥接页（启停/实时视图）为后续迭代（T74）。

### 场景4：局域网访问与访问令牌（可选）

Web UI 默认只监听 `127.0.0.1`（仅本机可访问）。需要从其它主机（如平板/同事电脑）
打开时，显式改监听地址并**同时设置访问令牌**：

```bash
python app.py --mode master --http-host 0.0.0.0 --auth-token "change-me"
# 也可以用环境变量，避免令牌进入命令行历史：
set IEC104_AUTH_TOKEN=change-me        # Windows
export IEC104_AUTH_TOKEN=change-me     # Linux/macOS
python app.py --mode master --http-host 0.0.0.0
```

- 启用令牌后，除 `GET /api/auth` 外的所有 `/api/*` 与 `/ws` 都需要携带令牌；
  浏览器首次打开会弹出令牌输入框，也可用
  `http://<host>:<port>/app/?token=<token>` 一次性导入（随后令牌从地址栏移除，
  保存在浏览器 localStorage）。
- 令牌携带形态：`Authorization: Bearer <token>`、`X-Auth-Token: <token>`、
  `?token=<token>`（WS 必须用 query）。缺失/错误返回 401。
- **未设置令牌却监听非回环地址**时，启动日志会打印醒目告警：局域网内任何主机
  都能调用遥控/点表下发等接口。生产网络请勿如此部署。
- **HTTPS（推荐与令牌同时启用）**：`--web-tls-cert certs/server.pem --web-tls-key certs/server.key`
  让 Web UI 走 HTTPS（最低 TLS 1.2），避免令牌与遥控命令在局域网明文传输。
  所有响应同时带 CSP / X-Frame-Options / Referrer-Policy / Permissions-Policy 头。
- `--demo` 一键演示始终只监听 127.0.0.1，忽略 `--auth-token` / `--http-host`。

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
- **双击值直接发命令**：定义表中遥控（YK）、遥测/遥调（YC）、步位置（STEP）点的
  「值」单元格双击后弹出确认框，核对点位、方向/目标值后下发对应命令；YK 若配置
  SBO，仍由主站自动先选择、收到肯定确认后再执行，选择失败不会发送执行帧。
  遥信（YX）/遥脉（YM）为只监不控点，双击值不会产生命令。
- **报文查看器**：I/S/U 帧实时列表，TypeID 中文摘要，十万行虚拟滚动
- **趋势图**：只采样**被订阅**的点位（全量采样会打满内存），环形缓冲
- **冗余双通道**：连接面板可启用备用前置机（地址/端口/切换超时），运行中显示
  活动通道、主/备在线状态与切换次数；配置只在「连接」时生效
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
- **点表导入**（T72）：点表面板标题行「导入」按钮支持
  **SCD/CID/ICD**（IEC 61850-6 SCL）：按 IEC 61850-80-1 映射
  （`Private/Address(casdu,ioa,ti)` 精确映射优先，无映射按 DOType `cdc` 推断
  并自动分配 IOA）转换为 104 点表——**先预览**（分类计数 + 告警 + 可编辑 YAML）
  再应用；YAML/CSV/JSON 直接导入。多公共地址（ASDU）时缺省取出现最多者，
  其余信号剔除并在告警中列明，可用预览后手动调整。

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

界面按 **ISA-101 高性能 HMI**（ANSI/ISA-101.01、ISA-TR101.02 技术报告）中适用于**工程调试工具**的部分设计，
与西门子 TIA/WinCC、施耐德 Geo SCADA 等工程软件的风格一致；完整规则见
[`design_guidelines.md`](design_guidelines.md)。

| 范式 | 本工具落地 |
|------|-----------|
| 颜色是"例外"不是"装饰" | 彩色只用于状态（运行 / 停止 / 警告 / 错误）与信息类型标签，其余用灰阶 + 边框分层；状态同时有文字，不只靠颜色 |
| 数据用表格表达，不做花哨图形 | 点表全边框单元格、表头吸顶、数值右对齐 + 等宽数字（tabular-nums），小数点成列便于竖排比读 |
| 无渐变、无立体阴影、克制圆角 | 按钮/卡片扁平（圆角 6px），无阴影装饰 |
| 交互元素状态必须无歧义 | 禁用态显式灰化并说明原因，焦点框可见；按钮可用性由服务端状态驱动 |
| 字段必须带标签，避免歧义 | 状态栏形如"状态 运行中 / 报文 TX 3 / RX 9 / 序号 VS/VR 1/7 窗口 0/12 / 点数 7" |

- 主题：首次打开**跟随系统偏好**（系统无明确偏好时用深色）；可手动切换浅色（明亮环境/投屏），选择会被记住。
- 对齐约定：文本列左对齐；**数值列右对齐**并用等宽数字，保证小数点成列；IOA、HEX 用等宽字体左对齐。
- 点表的遥测值应带**单位与小数位**，品质位应解码为「无效/非当前/替代/封锁/溢出」
  （品质位掩码已按 IEC 60870-5-101 修复，见附录 A.2；界面标签仍是英文缩写，见 A.3）。

### 按钮状态说明

顶部按钮的可用状态**始终跟随服务端真实状态**（状态栏左侧也会显示"未连接 / 连接中 / 运行中"）：

- 未启动：只能点「连接」/「启动监听」，「断开」/「停止」为灰色
- 已启动（含连接中）：只能点「断开」/「停止」，「连接」/「启动监听」为灰色

因此**刷新页面、或换个浏览器打开同一服务**时，按钮会立刻与后端对齐，不会出现"服务在运行但断开按钮点不了"的情况（该问题已修复）。若点击「连接」提示 `already running`，说明该服务端的会话已启动，直接点「断开」即可。

### 实时刷新与缓存

- 主站/子站点值**自动实时刷新**：页面收到报文或事件后，通过 WebSocket 向服务端要一次快照（最快 4 次/秒节流），只修补变化的单元格，不重建整表（滚动位置与按钮焦点不丢）。不需要手动刷新页面。
- **主站/子站菜单同时刷新**（单页工作台内切换，后台页签也不会停）；单角色模式下同一服务多窗口打开同样保持实时。
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

1. 打开 "模拟控制" 面板，按需打开 "模拟遥信 YX" / "模拟遥测 YC"（可只开一类，至少开一类），点击 "启动模拟"
2. 按需设置：

| 参数 | 说明 |
|------|------|
| 模拟遥信 YX / 模拟遥测 YC | 两类可独立开启；关闭的类型不产生任何报文，对应参数置灰 |
| YX / YC 间隔 | 两类点的变化周期（秒） |
| YX 范围 | "全部点" 或 "选中点"（点表当前选中行，类型须为 YX） |
| YX 每周期翻转概率 | 0~1；每个周期对范围内每个遥信点独立判定，命中即翻转 |
| YC 范围 | "全部点" 或 "选中点"（类型须为 YC） |
| 无量程点浮动比例 | 仅对点表未声明量程的 YC 点生效（当前值 ± 比例浮动） |

3. 系统将自动产生随机数据变化。

> **YC 取值规则（第二批改造）**：点表声明了量程（`min_value`/`max_value`）的
> 遥测点在 `[min, max]` 内均匀随机；未声明量程的点回落为「当前值 ± 浮动比例」。
> 范围选 "选中点" 时，点表外的 IOA 会被跳过并记录 info 日志。

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

### Web UI（报文抓包页）

「报文抓包」页把录制/回放搬到浏览器：

- **开始录制 / 暂停 / 继续 / 停止并保存**：帧写入 `data/captures/<role>_<时间>.i104`；
- **文件表**：下载原始 `.i104`，或一键「导出 pcap」（同目录生成，Wireshark 可直接打开；
  网络层为合成头，说明见 [`pcap_export.md`](pcap_export.md)）；
- **回放**：加载文件后播放/暂停/停止/上一帧/下一帧/倍速；只做离线展示，
  **不会把帧注入实时链路**（避免破坏 VS/VR 序号）。

> 合并模式（默认 both）下主站/子站共用 `data/captures/` 目录，但文件表按角色隔离：
> 子站页只显示 `slave_*.i104`，主站页只显示 `master_*.i104`；手动放入且不带角色
> 前缀的文件（如 `manual_import.i104`）对两个工作台都可见，便于离线回放。

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

### Web UI（状态总览页）

主站/子站 Web 均可：**状态总览 → 网络异常模拟**卡片。

- 开关控制是否注入；引擎未启动也可启用——主站「连接」/子站「启动监听」时自动安装，
  停止时自动卸载，下次启动按启用状态自动重装。
- 预设下拉 +「应用预设」；或填写延迟/丢包/损坏/乱序/断线概率/限速与方向后
  「应用自定义」。
- 「断线」按钮手动触发一次断线（1–600 秒）；「重置统计」清零计数。
- 卡片实时展示 RX/TX 的总数、丢帧、重复、乱序、损坏与断线次数。
- REST：`GET/POST /api/simulation`、`POST /api/simulation/reset|disconnect`
  （见 [`api_contract.md`](../webui/api_contract.md) §2.12）。

> 注入点在**传输层回调**（TCP 客户端/服务端）：帧在进入协议处理前被延迟/丢弃/损坏，
> 被丢弃的帧也不会出现在报文查看器；引擎的 raw_frame_callback（UI 观测点）不被包装。

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

### Web 测试中心（自动化测试页）

「自动化测试」页列出 `tests/scripts/*.yaml`，勾选后在**独立子进程**中顺序运行：

- 实时日志与通过/失败汇总；同一时间只允许一个 run，可随时停止；
- 运行结束生成 HTML/JSON/TXT 报告，可在页面直接下载；
- 脚本会自行占用测试端口；若 Web 会话已连接 2404，请先断开再运行。

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

合并模式（单进程双角色）下两个角色仍各写自己的库文件；单角色模式也可分别启动
（主站 8765 / 子站 8766）。Web 模式与 headless/CLI 模式都会把收发报文落盘。

**Web「历史」页**（主站/子站均可）：按时间范围、点位类型（YX/YC/YM）、IOA 或报文
方向（RX/TX）过滤，分「数据 / 报文」两个页签展示；支持按当前过滤条件导出 CSV
（上限 20 万行）。REST 端点见 [`api_contract.md`](../webui/api_contract.md) §2.11：
`GET /api/history/stats|data|frames|export`。历史库未启用（`--no-history`）时
页面给出提示并禁用导出。

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

> 真机核实步骤与探针脚本见 [`file_transfer_open_items.md`](file_transfer_open_items.md)
> （5 项开放清单 + `tests/e2e/qa_file_transfer_probe.py`，当前环境无真机，结论待回填）。

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

## 13. 诊断包导出

Web 页面「状态」页的「运行状态」卡片提供 **「导出诊断包」** 按钮，也可直接访问：

```bash
curl -OJ http://127.0.0.1:8765/api/diagnostics/export
```

生成一个 zip（`iec104_<角色>_diagnostics_<时间>.zip`），包含：

| 文件 | 内容 |
|------|------|
| `manifest.json` | 版本、角色、平台、生成时间、条数、脱敏说明 |
| `status.json` | 当前 `/api/status` 快照 |
| `config.json` | 生效配置；`tls.keyfile` 脱敏为 `<redacted>` |
| `logs.json` | 最近 2000 条结构化日志 |
| `frames.json` / `events.json` | 最近收发帧 / 引擎事件 |
| `points.json` | 点表定义 + 实时值 |
| `history.json` | 历史库统计（未启用时 `enabled=false`） |
| `README.txt` | 文件说明与隐私提示 |

> ⚠ 诊断包可能包含现场 IOA/公共地址/业务值/文件路径；转发前请确认接收方，
> 不要上传到公开仓库或公共工单附件。

---

## 技术支持

- 项目地址：https://github.com/yourname/iec104-tester
- 问题反馈：https://github.com/yourname/iec104-tester/issues
