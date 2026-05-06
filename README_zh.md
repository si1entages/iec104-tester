<p align="center">
  <img src="resources/icon.svg" width="128" height="128" alt="IEC 104 Tester Logo">
</p>

<h1 align="center">IEC 60870-5-104 Tester</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Qt-6-41CD52?logo=qt&logoColor=white" alt="Qt 6">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/IEC--104-Complete-brightgreen.svg" alt="IEC 104">
</p>

---

工业级 IEC 60870-5-104 协议测试工具，支持主站/子站双模式、实时数据监控、报文录制/回放、网络异常模拟、自动化测试脚本，以及现代化 Qt GUI 界面。

## ✨ 功能特性

### 协议实现

- **完整 IEC 60870-5-104 覆盖** — 59 种 ASDU 类型标识
- **APCI 层** — I/S/U 帧编解码
- **流控机制** — k-w 滑动窗口
- **定时器** — t0/t1/t2/t3 四级超时管理
- **状态机** — STARTDT/STOPDT/TESTFR 全生命周期
- **时标** — CP24Time2a / CP56Time2a
- **品质描述词** — OV/BL/NT/IV

### 主站功能

- 连接管理（STARTDT/STOPDT）
- 总召唤 / 组召唤（1–23 组）
- 累计量召唤、时钟同步、复位进程
- 单命令 / 双命令（选择-执行）
- 设点命令（归一化 / 标度化 / 短浮点）
- 断线自动重连

### 子站功能

- TCP 服务端（多客户端）
- 响应全部系统命令
- 自发上送、SOE 事件上报
- 数据模拟器（手动 / 随机 / 脚本化）
- 点表管理（YAML 导入导出）

### GUI 界面

- **高性能表格** — 虚拟滚动，支持 10 万+ 数据点
- **报文查看器** — HEX + 协议解析，颜色区分收发方向
- **深色/浅色主题** — Catppuccin 风格

### 高级功能

- **📡 报文录制/回放** — 录制会话到 `.i104`/`.json`，支持变速回放
- **🔧 网络异常模拟** — 延迟、丢包、损坏、重复、乱序、断线
- **🧪 自动化测试脚本** — YAML 驱动的测试序列 + 断言
- **📊 分析统计** — 帧统计、异常检测、协议解析

## 🚀 快速开始

```bash
pip install PySide6 PyYAML

# 终端 1 — 启动子站（服务端）
python app.py --mode slave --port 2404

# 终端 2 — 启动主站（客户端）
python app.py --mode master --host 127.0.0.1 --port 2404
```

## 📦 安装

```bash
git clone https://github.com/yourname/iec104-tester.git
cd iec104-tester
pip install PySide6 PyYAML
```

## 💻 使用

```bash
# 主站模式
python app.py --mode master --host 192.168.1.100 --port 2404

# 子站模式 + 自定义点表
python app.py --mode slave --point-table configs/demo_points.yaml

# 无界面 CLI 模式
python app.py --mode slave --no-gui --log-level DEBUG

# 运行自动化测试脚本
python run_tests.py tests/scripts/

# 报文录制
python capture_tool.py record --mode master --host 127.0.0.1 -o session.i104
python capture_tool.py play session.i104 --speed 2.0
python capture_tool.py analyze session.i104

# 网络异常模拟
python sim_tool.py --preset poor_wifi --mode master --host 127.0.0.1
python sim_tool.py --loss 0.1 --delay 50 --mode master
```

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mode` | `master`（主站）或 `slave`（子站） | `master` |
| `--host` | 远程地址 | `127.0.0.1` |
| `--port` | TCP 端口 | `2404` |
| `--config` | YAML 配置文件 | — |
| `--point-table` | 点表 YAML 文件 | — |
| `--no-gui` | 无界面模式 | `false` |
| `--test` | 运行测试脚本（文件或目录） | — |
| `--log-level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |

## ⚙️ 配置

```bash
cp resources/config_template.yaml config.yaml
```

```yaml
mode: master
connection:
  host: "192.168.1.100"
  port: 2404
  common_addr: 1
  reconnect: true
timers:
  t0: 30.0    # 连接建立超时
  t1: 15.0    # 发送确认超时
  t2: 10.0    # 无数据确认超时
  t3: 20.0    # 空闲测试超时
flow_control:
  k: 12       # 未确认 I 帧上限
  w: 8        # 确认触发阈值
```

## 🧪 自动化测试脚本

```bash
# 运行单个脚本
python run_tests.py tests/scripts/basic_connection_gi.yaml

# 运行全部脚本
python run_tests.py tests/scripts/ -v
```

脚本格式（YAML）：

```yaml
name: basic_test
description: "基础连接与总召测试"
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

### 内置动作

| 类别 | 动作 |
|------|------|
| 连接 | `connect`, `disconnect` |
| 协议 | `send_startdt`, `send_stopdt`, `general_interrogation`, `counter_interrogation`, `clock_sync`, `reset_process` |
| 控制 | `single_command`, `double_command`, `setpoint_normalized`, `setpoint_shortfloat` |
| 等待 | `wait`, `wait_state`, `wait_frames`, `wait_asdu` |
| 子站 | `slave_set_yx`, `slave_set_yc`, `slave_start_sim`, `slave_stop_sim` |
| 模拟 | `apply_network_condition`, `remove_network_condition`, `network_disconnect` |
| 辅助 | `set_variable`, `clear_buffers`, `log` |

## 📡 报文录制与回放

```bash
# 录制
python capture_tool.py record --mode master --host 127.0.0.1 -o session.i104

# 回放（原始速度）
python capture_tool.py play session.i104

# 回放（2 倍速）
python capture_tool.py play session.i104 --speed 2.0

# 单步模式
python capture_tool.py play session.i104 --step

# 分析
python capture_tool.py analyze session.i104

# 查看帧
python capture_tool.py show session.i104 --limit 100 --filter "frame_type=I"

# 格式转换
python capture_tool.py convert session.i104 -o session.json
```

## 🔧 网络异常模拟

```bash
# 使用预设
python sim_tool.py --preset poor_wifi       # 差 WiFi 环境
python sim_tool.py --preset congested       # 网络拥塞
python sim_tool.py --preset satellite       # 卫星链路（高延迟）
python sim_tool.py --preset unreliable      # 高丢包
python sim_tool.py --preset stress          # 综合压力测试

# 自定义条件
python sim_tool.py --loss 0.1 --delay 50 --corrupt 0.05 --mode master
```

### 预设列表

| 预设 | 说明 |
|------|------|
| `clean` | 正常网络 |
| `poor_wifi` | 延迟 30ms±20ms，丢包 5% |
| `congested` | 延迟 100ms±50ms，丢包 10% |
| `satellite` | 延迟 500ms±100ms，丢包 2% |
| `unreliable` | 丢包 30%，损坏 5% |
| `intermittent` | 5% 概率断线 5 秒 |
| `slow_link` | 带宽限制 1KB/s |
| `stress` | 全部异常叠加 |

## 🏗 项目结构

```
iec104-tester/
├── app.py                          # 应用入口
├── run_tests.py                    # 测试脚本运行器 CLI
├── capture_tool.py                 # 报文录制/回放 CLI
├── sim_tool.py                     # 网络异常模拟 CLI
├── core/                           # 协议核心层（无 GUI 依赖）
│   ├── protocol/                   # IEC 60870-5-104 协议实现
│   ├── transport/                  # TCP 异步传输层
│   ├── engine/                     # 主站/子站引擎
│   ├── data/                       # 数据模型（点表、实时库）
│   ├── testing/                    # 自动化测试脚本引擎
│   ├── capture/                    # 报文录制/回放引擎
│   ├── simulation/                 # 网络异常模拟引擎
│   └── config.py                   # 配置管理
├── gui/                            # PySide6 GUI 层
│   ├── main_window.py              # 主窗口
│   ├── themes.py                   # 深色/浅色主题
│   ├── widgets/                    # 通用控件
│   ├── master/                     # 主站界面
│   └── slave/                      # 子站界面
├── configs/                        # 预置配置
├── resources/                      # 图标、样式、模板
├── tests/                          # 协议测试 + 测试脚本
└── build/                          # 打包脚本（Windows/Linux）
```

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| 表格渲染 | 10 万行虚拟滚动 |
| 刷新周期 | 500ms（可配置） |
| 报文处理 | asyncio 非阻塞 I/O |
| 内存管理 | 环形缓冲区，自动清理 |
| 并发连接 | 最多 16 个 |

## 🤝 贡献

1. Fork 本仓库
2. 创建功能分支（`git checkout -b feature/amazing-feature`）
3. 提交更改（`git commit -m 'Add amazing feature'`）
4. 推送分支（`git push origin feature/amazing-feature`）
5. 提交 Pull Request

## 📄 许可证

本项目基于 MIT 许可证 — 详见 [LICENSE](LICENSE) 文件。

## 🙏 致谢

- [IEC 60870-5-104](https://webstore.iec.ch/en/publication/6270) — 国际远动通信协议标准
- [PySide6](https://wiki.qt.io/Qt_for_Python) — Qt for Python
- [Catppuccin](https://github.com/catppuccin/catppuccin) — 配色方案灵感

---

<p align="center">
  Made with ⚡ for the power systems community
</p>
