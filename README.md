<p align="center">
  <img src="resources/icon.svg" width="128" height="128" alt="IEC 104 Tester Logo">
</p>

<h1 align="center">IEC 60870-5-104 Tester</h1>

<p align="center">
  <a href="README_eng.md">English</a> | <a href="README.md">中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/WebUI-aiohttp-41CD52" alt="Web UI">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/IEC--104-Complete-brightgreen.svg" alt="IEC 104">
  <img src="https://img.shields.io/badge/Tests-405-brightgreen.svg" alt="Tests">
</p>

---

工业级 IEC 60870-5-104 协议测试工具：主站/子站**浏览器 Web UI**（纯 web 形态，浏览器作为唯一界面，可同时开两个标签页联调），协议引擎完整，附多站并发、报文录制回放、网络异常模拟、YAML 自动化测试。

## ✨ 功能特性

### 协议实现（`core/protocol`）

- 59 种 ASDU 类型标识；APCI I/S/U 帧；k-w 流控；t0/t1/t2/t3 定时器
- STARTDT/STOPDT/TESTFR 状态机；CP24Time2a / CP56Time2a；品质描述词
- 文件传输；参数命令；时标与品质

### 主站（Web UI + `core/engine/master.py`）

- 连接管理、断线重连
- 总召唤 / **组召唤（QOI 0–23）**、累计量召、时钟同步、复位进程、测试命令
- 单/双命令、设点（短浮点/归一化/标度化）、读命令、参数命令、文件目录/选择/请求
- 定义表（YX/YC/YK/YM 分页）、批量改组/启用禁用、YAML 导入导出、CSV/会话 JSON 导出
- 实时报文列表（U/S/I + TypeID 摘要）、事件日志

### 子站（Web UI + `core/engine/slave.py`）

- TCP 多客户端监听；系统命令响应；DEACT；SOE/自发上送
- 可编辑点表（点 YX 切换、改 YC 自发上送）
- **响应注入**（延迟、丢帧、损坏、不响应、品质、**错误 COT**）
- 数据模拟（手动/自动）；YAML 点表

### 多站 / 录制 / 模拟（CLI）

- `run_multi_station.py` — 多子站并发，端口/公共地址/点表独立
- `capture_tool.py` — 录制/回放/分析 `.i104`/`.json`
- `sim_tool.py` — 延迟/丢包/损坏/乱序/断线预设

### 测试

- 单元 + 集成：`pytest tests/`（**405**，含 Web API 与协议符合性用例）
- 一致性：`tests/conformance/test_conformance.py`（42 用例）
- 脚本：`run_tests.py tests/scripts/`（YAML 动作 + 断言）

## 🚀 快速开始

```bash
pip install -r requirements.txt

# 启动主站 / 子站 Web 服务（各自自动打开浏览器）
python app.py --mode master    # 主站，默认 http://127.0.0.1:8765/
python app.py --mode slave     # 子站，默认 http://127.0.0.1:8766/

# 或使用瘦入口脚本（等价）
python apps/web_master.py
python apps/web_slave.py

# 无窗口/服务器场景：不自动开浏览器，仅打印地址
python app.py --mode master --no-browser --http-port 8765
```

服务启动后会在默认浏览器自动打开对应页面；用 `--no-browser` 可关闭自动打开。
联调：开两个终端分别启动主站与子站 → 子站页「启动监听」→ 主站页「连本地」→「立即总召」。

## 📦 安装

```bash
git clone https://github.com/yourname/iec104-tester.git
cd iec104-tester
python -m venv venv
# Windows:
venv\Scripts\pip install -r requirements.txt
# Linux/macOS:
pip install -r requirements.txt
```

依赖：`PyYAML`、`aiohttp`。开发测试另需 `pytest`、`pytest-asyncio`。

## 💻 命令行

```bash
# 兼容入口（启动 Web 服务）
python app.py --mode master
python app.py --mode slave --port 2404

# 无界面引擎
python app.py --mode slave --no-gui --log-level DEBUG

# 自动化测试脚本
python run_tests.py tests/scripts/

# 一致性测试
python tests/conformance/test_conformance.py

# 报文录制
python capture_tool.py record --mode master --host 127.0.0.1 -o session.i104
python capture_tool.py play session.i104 --speed 2.0
python capture_tool.py analyze session.i104

# 多站
python run_multi_station.py --stations 3

# 网络异常
python sim_tool.py --preset poor_wifi --mode master --host 127.0.0.1
```

### 主要参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `--mode` | master / slave | master |
| `--host` / `--port` | TCP | 127.0.0.1:2404 |
| `--point-table` | 点表 YAML | — |
| `--no-gui` | 仅 CLI | false |
| `--test` | 测试脚本文件/目录 | — |
| `--log-level` | DEBUG…ERROR | INFO |

Web UI 入口另支持 `--http-port`（默认主站 8765、子站 8766）与 `--no-browser`（不自动打开浏览器）。

## ⚙️ 配置

```bash
cp resources/config_template.yaml config.yaml
```

```yaml
mode: master
connection: { host: "192.168.1.100", port: 2404, common_addr: 1, reconnect: true }
timers: { t0: 30, t1: 15, t2: 10, t3: 20 }
flow_control: { k: 12, w: 8 }
```

多站配置见 `configs/multi_station_example.yaml`。

## 🧪 测试脚本

```bash
python run_tests.py tests/scripts/basic_connection_gi.yaml
python run_tests.py tests/scripts/ -v
python -m pytest tests/ -q
```

脚本动作包括：`connect`、`general_interrogation`、`single_command`、`slave_set_yx`、`apply_network_condition` 等（完整列表见 `core/testing/actions.py`）。

## 📡 报文录制 / 网络模拟 / 多站

```bash
python capture_tool.py record|play|analyze|show|convert ...
python sim_tool.py --preset poor_wifi|congested|satellite|unreliable|stress
python run_multi_station.py --stations 5
```

## 🏗 项目结构

```
iec104-tester/
├── app.py                 # CLI/Web 兼容入口
├── apps/                  # 瘦入口 web_master / web_slave
├── webui/                 # aiohttp REST+WS + 静态工业深色 UI
│   ├── bridge.py          # 引擎桥
│   ├── server.py
│   └── static/
├── core/
│   ├── protocol/          # APCI/ASDU/类型/流控/文件传输
│   ├── engine/            # master / slave / multi_station
│   ├── transport/         # TCP asyncio
│   ├── data/              # 点表、实时库
│   ├── capture/           # 录制回放
│   ├── simulation/        # 网络异常
│   └── testing/           # YAML 脚本引擎
├── run_tests.py / run_multi_station.py / capture_tool.py / sim_tool.py
├── configs/ resources/ tests/ build/
└── requirements.txt
```

## 🤝 贡献 / 许可

MIT — 见 [LICENSE](LICENSE)。

## 🙏 致谢

- [IEC 60870-5-104](https://webstore.iec.ch/en/publication/6270)
- [aiohttp](https://docs.aiojs.org/)

---

<p align="center">Made for the power systems community</p>
