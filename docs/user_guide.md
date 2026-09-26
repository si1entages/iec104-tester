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
11. [常见问题](#11-常见问题)

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
| 报文录制 | 支持 .i104/.json 格式 |
| 网络模拟 | 丢包、延迟、乱序、损坏等异常 |

---

## 2. 安装

### 环境要求

- Python 3.10 或更高版本
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

子站模式的界面与主站类似，但功能面板包含：

- **模拟面板**：手动/自动数据变化
- **响应配置**：配置对主站命令的响应行为
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
# GUI 中点击工具栏 "录制" 按钮
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
```

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
```

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

## 11. 常见问题

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
1. GUI 中点击工具栏 "录制" 按钮
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
