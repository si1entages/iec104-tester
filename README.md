<p align="center">
  <img src="resources/icon.svg" width="128" height="128" alt="IEC 104 Tester Logo">
</p>

<h1 align="center">IEC 60870-5-104 Tester</h1>

<p align="center">
  <a href="README_eng.md">English</a> | <a href="README.md">中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/WebUI-aiohttp-41CD52" alt="Web UI">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/IEC--104-Complete-brightgreen.svg" alt="IEC 104">
  <img src="https://img.shields.io/badge/Tests-1151-brightgreen.svg" alt="Tests">
</p>

---

工业级 IEC 60870-5-104 协议测试工具：主站/子站**浏览器 Web UI**（纯 web 形态，浏览器作为唯一界面，可同时开两个标签页联调），协议引擎完整，附多站并发、报文录制回放、网络异常模拟、YAML 自动化测试、TLS 传输加密与历史库。

## ✨ 功能特性

### 协议实现（`core/protocol`）

- 59 种标准 ASDU 类型标识 + **非标厂商私有 TypeID 注册**（YAML 声明字段即可编解码往返，未注册仍按标准回 COT=42）
- APCI I/S/U 帧；k-w 流控；t0/t1/t2/t3 定时器；STARTDT/STOPDT/TESTFR 状态机
- CP24Time2a / CP56Time2a；品质描述词
- **文件传输**（F_FR/F_SR/F_SC/F_LS/F_AF/F_SG/F_DR）字节级语义已按多个独立参考实现逐字节核实（详见 [`docs/file_transfer_fls.md`](docs/file_transfer_fls.md)）
- **TLS 传输层加密**（证书/CA 校验、双向认证 mTLS；⚠ 仅传输层加密，**不等于 IEC 62351 合规**，边界见 [`docs/tls.md`](docs/tls.md)）

### Web UI（浅色工业风，按 ISA-101 高性能 HMI 惯例设计）

- **主站工作台**：十万行点表虚拟滚动（只渲染可视窗口）、命令面板（系统命令/遥控/设点/文件命令）、实时报文查看器、点位趋势图（只采样被订阅点位）
- **子站工作台**：手动置数、**应答行为配置**（延迟/丢帧/损坏/不响应/品质/错误 COT）、数据模拟（手动/自动）
- **多站页**：多子站卡片管理与聚合状态
- **日志页**：历史库报文查询（含过滤与订阅）
- 点值经 WebSocket 实时刷新；按钮可用性由服务端状态驱动；数据表表头吸顶、数值等宽（tabular-nums）

### 主站（`core/engine/master.py`）

- 连接管理、断线重连；**冗余双通道**（主备自动切换 + 切换窗口去重，见 `docs/redundancy.md`）
- 总召唤 / **组召唤（QOI 0–23）**、累计量召唤、时钟同步、复位进程、测试命令
- 单/双命令（SBO 两段式/直发）、设点（短浮点/归一化/标度化）、读命令、参数命令、文件目录/选择/请求/确认
- 点位自学习（报文中出现而定义表没有的 IOA 自动补点）、周期总召唤、定义表批量改组/启用禁用、YAML 导入导出、CSV/会话 JSON 导出
- 实时报文列表（U/S/I + TypeID 摘要）、事件日志

### 子站（`core/engine/slave.py`）

- TCP 多客户端监听；系统命令响应；DEACT；SOE/自发上送
- 可编辑点表（点 YX 切换、改 YC 自发上送）
- **响应注入**（延迟、丢帧、损坏、不响应、品质、错误 COT）
- **命令联动**（真机语义：遥控→同 IOA 遥信变位、遥调→同 IOA 遥测更新，带时标 COT=3 上送）
- 数据模拟（手动/自动）；YAML 点表

### 数据与运维

- **历史库默认开启**（SQLite，按角色分库），`--no-history` 可关闭；保留期/条数/容量三重清理
- **报文导出**：`.i104` / `.json` / **pcap / pcapng**（Wireshark 可直接打开）
- 多站并发（`run_multi_station.py`）、网络异常模拟（`sim_tool.py`）、YAML 自动化测试（`run_tests.py`）

### 打包产物

- `python build/build_all.py` 一键产出 **`dist/iec104-master` / `dist/iec104-slave`** 两个免安装目录（含 Web 前端、配置、资源），双击 exe 即用（详见 [`docs/user_guide.md`](docs/user_guide.md)）

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

### 一键环回演示（推荐首次体验）

```bash
python app.py --demo
```

一条命令在本机同时启动子站与主站（不同 HTTP 端口），自动完成「子站监听 → 主站连接 →
总召」，并打开主站页面；历史库自动关闭，Ctrl+C 停止全部进程。

### 手动联调示例（两个终端）

```bash
# 终端 1：子站（默认生成演示点表，历史库开启）
python app.py --mode slave --port 2404 --no-browser

# 终端 2：主站（连接后自动 STARTDT，手动点总召；或 --mode master --no-browser 后看日志）
python app.py --mode master --host 127.0.0.1 --port 2404 --no-browser
```

主站页面连接成功后点「立即总召」，子站演示点表的遥信/遥测即出现在主站定义表。

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

运行依赖：`PyYAML`、`aiohttp`。开发测试另需 `pytest`、`pytest-asyncio`、`ruff`；打包另需 `pyinstaller>=6.0`（见 `pyproject.toml` 可选依赖组）。

## 💻 命令行

```bash
# 兼容入口（启动 Web 服务）
python app.py --mode master
python app.py --mode slave --port 2404

# 一键环回演示（本机子站+主站，自动连接并总召）
python app.py --demo
python app.py --demo --demo-seconds 30 --no-browser   # 30s 后自动停止

# 无界面引擎
python app.py --mode slave --no-gui --log-level DEBUG

# 关闭历史库
python app.py --mode slave --no-history

# TLS（测试证书见 tests/certs/，生成方式见该目录 README）
python app.py --mode slave --tls --tls-cert tests/certs/server.pem --tls-key tests/certs/server.key
python app.py --mode master --tls --tls-ca tests/certs/ca1.pem --host 127.0.0.1

# 自动化测试脚本
python run_tests.py tests/scripts/

# 报文录制 / 导出 pcap
python capture_tool.py record --mode master --host 127.0.0.1 -o session.i104
python capture_tool.py convert session.i104 -o session.pcap

# 多站
python run_multi_station.py --stations 3

# 网络异常
python sim_tool.py --preset poor_wifi --mode master --host 127.0.0.1
```

### 主要参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `--mode` | 运行模式 master / slave | master |
| `--config` | 配置文件路径 (YAML) | — |
| `--host` / `--port` | 目标 TCP 地址 / 端口 | 127.0.0.1 / 2404 |
| `--point-table` | 点表文件路径 (YAML) | — |
| `--log-level` / `--log-file` | 日志级别 / 日志文件 | INFO / — |
| `--history-db` | 历史数据库路径 (SQLite) | — |
| `--no-history` | 关闭历史库（默认开启） | false |
| `--no-gui` | headless CLI 模式（仅日志输出） | false |
| `--test` | 运行自动化测试脚本 (YAML 文件或目录) | — |
| `--http-port` | Web UI HTTP 端口 | 主站 8765 / 子站 8766 |
| `--no-browser` | 启动 Web 服务时不自动打开浏览器 | false |
| `--demo` | 一键环回演示：本机子站+主站并自动连接 | false |
| `--demo-seconds` | 演示运行 N 秒后自动停止（0=直到 Ctrl+C） | 0 |
| `--tls` | 启用 TLS 传输加密 | false |
| `--tls-cert` / `--tls-key` | 本端证书 / 私钥 (PEM) | — |
| `--tls-ca` | 受信 CA (PEM) | — |
| `--no-verify` | 主站跳过服务端证书校验（仅自签联调，生产禁用） | false |
| `--verify-client` | 子站要求并校验客户端证书（mTLS） | false |
| `--tls-hostname` | 主站 TLS 主机名校验域名 | — |

> 共 22 个参数，与 `python app.py --help` 一致。`--http-port` / `--no-browser` / `--demo` 仅 Web UI 入口生效。

## ⚙️ 配置

```bash
cp resources/config_template.yaml config.yaml
```

```yaml
mode: master
connection: { host: "192.168.1.100", port: 2404, common_addr: 1, reconnect: true }
timers: { t0: 30, t1: 15, t2: 10, t3: 20 }
flow_control: { k: 12, w: 8 }
history:   { enabled: true, retention_days: 7, max_size_mb: 512 }
tls:       { enabled: false }
custom_types: []   # 非标厂商私有 TypeID 注册
```

完整字段说明见 [`docs/user_guide.md`](docs/user_guide.md) 第 9 节；多站配置见 `configs/multi_station_example.yaml`。

## 🧪 测试

```bash
python -m pytest tests/ -q              # 单元 + 集成（1281 例；性能基准默认排除）
python -m pytest tests/ -m perf -q      # 性能基准（解码/10 万点/20 客户端并发/环回 soak）
python run_tests.py tests/scripts/      # YAML 脚本
python tests/e2e/qa_full_flow.py        # 全流程验收
python tools/mutation_smoke.py          # 协议层变异冒烟（12/12 必须被杀死）
```

- 互操作语料库：`tests/fixtures/frames/`（合成基线 + `real/` 真机目录），
  `tests/test_frame_corpus_replay.py` 做 golden 解码与主站回放回归；
- 协议 fuzz：`tests/test_protocol_fuzz.py`（Hypothesis；畸形输入只允许 `ValueError`）；
- 诊断包：Web 状态页「导出诊断包」或 `GET /api/diagnostics/export`。

## 🏗 项目结构

```
iec104-tester/
├── app.py                 # CLI/Web 兼容入口
├── apps/                  # 瘦入口 web_master / web_slave（打包入口）
├── webui/                 # aiohttp REST+WS + React 前端（构建产物在 webui/static/app/）
│   ├── bridge.py          # 引擎桥
│   ├── server.py
│   └── static/
├── core/
│   ├── protocol/          # APCI/ASDU/类型/流控/文件传输/自定义类型
│   ├── engine/            # master / slave / multi_station
│   ├── transport/         # TCP / TLS
│   ├── data/              # 点表、实时库、历史库
│   ├── capture/           # 录制回放（.i104/.json/pcap/pcapng）
│   ├── simulation/        # 网络异常
│   └── testing/           # YAML 脚本引擎
├── build/build_all.py     # PyInstaller 打包（产出 dist/iec104-master|slave）
├── run_tests.py / run_multi_station.py / capture_tool.py / sim_tool.py
├── configs/ resources/ tests/ docs/
└── requirements.txt
```

## 📖 文档

- 用户手册：[`docs/user_guide.md`](docs/user_guide.md)（含 Web UI 各工作台、TLS、历史库、配置参考、已知限制）
- TLS 边界与排查：[`docs/tls.md`](docs/tls.md)
- 文件传输字节语义核实：[`docs/file_transfer_fls.md`](docs/file_transfer_fls.md)
- pcap 导出：[`docs/pcap_export.md`](docs/pcap_export.md)
- 历史库实测数据：[`docs/history.md`](docs/history.md)

## 🤝 贡献 / 许可

MIT — 见 [LICENSE](LICENSE)。

## 🙏 致谢

- [IEC 60870-5-104](https://webstore.iec.ch/en/publication/6270)
- [aiohttp](https://docs.aiojs.org/)

---

<p align="center">Made for the power systems community</p>
