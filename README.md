# IEC 60870-5-104 协议测试工具

工业级 IEC 60870-5-104 通信协议测试软件，支持主站（Master）和子站（Slave）双模式。

## 功能特性

### 协议实现（完整覆盖 IEC 60870-5-104）

- **APCI 层**: I帧/S帧/U帧 完整编解码
- **ASDU 层**: 40+ 类型标识完整支持
- **状态机**: STARTDT/STOPDT/TESTFR 全生命周期
- **流控**: k-w 滑动窗口机制
- **定时器**: t0/t1/t2/t3 四级超时管理
- **时标**: CP24Time2a / CP56Time2a 编解码
- **品质描述词**: OV/BL/NT/IV 完整解析

### 支持的 ASDU 类型

| 方向 | 类型 | 说明 |
|------|------|------|
| 监控 | M_SP_NA_1/TB_1 | 单点遥信（带/不带时标） |
| 监控 | M_DP_NA_1/TB_1 | 双点遥信 |
| 监控 | M_ME_NA_1/TD_1 | 归一化遥测 |
| 监控 | M_ME_NB_1/TE_1 | 标度化遥测 |
| 监控 | M_ME_NC_1/TF_1 | 短浮点遥测 |
| 监控 | M_IT_NA_1/TB_1 | 累计量/电度 |
| 监控 | M_ST_NA_1/TB_1 | 步位置信息 |
| 监控 | M_BO_NA_1/TB_1 | 32比特串 |
| 控制 | C_SC_NA_1 | 单命令（遥控） |
| 控制 | C_DC_NA_1 | 双命令（遥控） |
| 控制 | C_RC_NA_1 | 升降命令 |
| 控制 | C_SE_NA_1/NB_1/NC_1 | 设点命令（遥调） |
| 系统 | C_IC_NA_1 | 总召唤/组召唤 |
| 系统 | C_CI_NA_1 | 累计量召唤 |
| 系统 | C_CS_NA_1 | 时钟同步 |
| 系统 | C_RP_NA_1 | 复位进程 |
| 系统 | C_TS_NA_1/TA_1 | 测试命令 |
| 参数 | P_ME_NA_1/NB_1/NC_1 | 参数命令 |
| 文件 | F_FR/SR/SC/LS/AF/SG/DR | 文件传输 |

### GUI 功能

- **高性能表格**: 虚拟滚动，支持 10 万+ 数据点
- **实时刷新**: 可配置刷新频率（默认 500ms）
- **报文查看器**: HEX + 协议解析，颜色区分收发方向
- **日志系统**: 分级过滤，自动滚动
- **状态面板**: 连接状态/序列号/定时器/通信统计
- **深色/浅色主题**: Catppuccin 风格配色

### 主站功能

- 连接管理（STARTDT/STOPDT）
- 总召唤 / 组召唤（1-16组）
- 累计量召唤
- 时钟同步
- 复位进程
- 单命令/双命令（选择-执行）
- 设点命令（归一化/标度化/短浮点）
- 断线自动重连
- 自动总召唤

### 子站功能

- TCP 服务端（多客户端）
- 响应总召唤/组召唤
- 响应时钟同步
- 响应遥控/遥调命令
- 自发上送变化数据（突发）
- SOE 事件上送
- 数据模拟器（手动/自动）
- 点表管理（YAML 导入导出）

## 安装

```bash
# 基础依赖
pip install PySide6 PyYAML

# 开发依赖
pip install pytest pytest-asyncio
```

## 运行

```bash
# 主站模式
python app.py --mode master --host 127.0.0.1 --port 2404

# 子站模式
python app.py --mode slave --port 2404

# 使用配置文件
python app.py --config configs/master_config.yaml

# 使用自定义点表
python app.py --mode slave --point-table configs/demo_points.yaml

# 调试模式
python app.py --mode master --log-level DEBUG
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mode` | 运行模式 (master/slave) | master |
| `--config` | 配置文件路径 (YAML) | - |
| `--host` | 连接地址 | 127.0.0.1 |
| `--port` | 端口号 | 2404 |
| `--log-level` | 日志级别 | INFO |
| `--log-file` | 日志文件路径 | - |
| `--point-table` | 点表文件路径 | - |

## 项目结构

```
iec104-tester/
├── app.py                      # 应用入口
├── pyproject.toml              # 项目配置
├── core/                       # 协议核心层（无GUI依赖）
│   ├── protocol/               # IEC 60870-5-104 协议
│   │   ├── constants.py        # 协议常量
│   │   ├── types.py            # 类型定义/枚举
│   │   ├── apci.py             # APCI 帧编解码
│   │   ├── asdu.py             # ASDU 报文编解码
│   │   ├── sequence.py         # 序列号/流控管理
│   │   └── state_machine.py    # 连接状态机
│   ├── transport/              # TCP 异步传输层
│   │   └── connection.py       # Server/Client/连接管理
│   ├── engine/                 # 协议引擎
│   │   ├── master.py           # 主站引擎
│   │   └── slave.py            # 子站引擎
│   ├── data/                   # 数据模型
│   │   ├── point_table.py      # 点表管理
│   │   └── data_store.py       # 实时数据库
│   └── config.py               # 配置管理
├── gui/                        # PySide6 界面层
│   ├── main_window.py          # 主窗口
│   ├── themes.py               # 深色/浅色主题
│   ├── widgets/                # 通用控件
│   │   ├── point_table.py      # 虚拟滚动表格
│   │   ├── hex_viewer.py       # 报文查看器
│   │   └── status_panel.py     # 状态/日志面板
│   ├── master/                 # 主站界面
│   │   └── control_panel.py    # 命令栏/控制面板
│   └── slave/                  # 子站界面
│       └── sim_panel.py        # 数据模拟面板
├── tests/                      # 测试
│   └── test_protocol.py        # 协议一致性测试
├── configs/                    # 配置文件
│   ├── master_config.yaml      # 主站配置
│   ├── slave_config.yaml       # 子站配置
│   └── demo_points.yaml        # 演示点表
└── build/                      # 打包脚本
    └── build.py                # PyInstaller 打包
```

## 打包

### Windows (exe)

```bash
pip install pyinstaller
python build/build.py
# 输出: dist/IEC104Tester/
```

### Linux (可执行文件)

```bash
pip install pyinstaller
python build/build.py
# 输出: dist/iec104-tester
```

## 协议测试

```bash
python tests/test_protocol.py
```

测试覆盖:
- APCI 帧编解码 (U/S/I)
- 所有信息对象类型
- CP56Time2a 时标
- ASDU 报文构造/解析
- 序列号管理
- 连接状态机
- 完整 APDU 往返

## 点表配置

YAML 格式:

```yaml
station_name: "My Substation"
common_addr: 1

yx:
  - ioa: 1
    name: "开关位置"
    group: 1
    type: single

yc:
  - ioa: 1001
    name: "电压"
    group: 1
    type: short_float
    unit: "kV"

yk:
  - ioa: 2001
    name: "开关控制"
    type: single
    sbo: true

ym:
  - ioa: 3001
    name: "电度"
    group: 1
```

## 性能指标

- 表格渲染: 10万行虚拟滚动，500ms 刷新周期
- 报文处理: asyncio 异步 I/O，无阻塞
- 内存占用: 环形缓冲区，自动清理旧数据
- 连接支持: 单实例最多 16 个并发连接

## 技术栈

- Python 3.10+
- PySide6 (Qt 6)
- asyncio (TCP 异步通信)
- PyYAML (配置管理)
- PyInstaller (打包)
