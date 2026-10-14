# IEC 60870-5-104 测试工具 — API 参考

## 目录

1. [协议层 API](#1-协议层-api)
2. [引擎层 API](#2-引擎层-api)
3. [传输层 API](#3-传输层-api)
4. [数据层 API](#4-数据层-api)
5. [Web UI API](#5-web-ui-api)

---

## 1. 协议层 API

### 1.1 APCI 帧编解码

```python
from core.protocol.apci import APCICodec, APCI

# 编码 I 格式帧
frame = APCICodec.encode_i_frame(
    send_seq=0,
    recv_seq=0,
    asdu_data=b'\x01\x03\x03\x00\x01\x00\x00\x00\x00'
)

# 解码帧
apci = APCICodec.decode(frame)
print(apci.frame_type)  # 'I', 'S', or 'U'
print(apci.send_seq)    # 发送序列号
print(apci.recv_seq)    # 接收序列号

# 编码 S 格式帧（确认）
s_frame = APCICodec.encode_s_frame(recv_seq=5)

# 编码 U 格式帧（控制）
u_frame = APCICodec.encode_u_frame(
    function=APCI.UFunction.STARTDT_ACT
)
```

### 1.2 ASDU 编解码

```python
from core.protocol.asdu import ASDU, ASDUBuilder
from core.protocol.types import TypeID, COT

# 构建 ASDU
asdu = ASDUBuilder.build(
    type_id=TypeID.M_SP_NA_1,  # 单点信息
    cot=COT.PERIODIC,
    common_addr=1,
    ioas=[...]
)

# 解码 ASDU
parsed = ASDU.decode(raw_bytes)
print(parsed.type_id)
print(parsed.cot)
print(parsed.ioas)

# 构建总召唤命令
gi_asdu = ASDUBuilder.build_general_interrogation(
    common_addr=1,
    qoi=20  # 站召唤
)
```

### 1.3 类型定义

```python
from core.protocol.types import (
    TypeID,        # 类型标识符枚举
    COT,           # 传送原因枚举
    SinglePoint,   # 单点信息
    DoublePoint,   # 双点信息
    ShortFloat,    # 短浮点数
    ScaledValue,   # 标度化值
    NormalizedValue,  # 归一化值
    CounterValue,  # 计数器值
    QualityDescriptor,  # 品质描述词
    CP56Time2a,    # 时间戳
    SingleCommand, # 单命令
    DoubleCommand, # 双命令
)

# 创建数据对象
sp = SinglePoint(ioa=1, value=True, quality=0)
sf = ShortFloat(ioa=1001, value=23.5, quality=0)
ts = CP56Time2a.now()
```

### 1.4 序列号管理

```python
from core.protocol.sequence import SequenceManager

seq = SequenceManager(k=12, w=8)

# 获取下一个发送序列号
send_seq = seq.next_send_seq()

# 检查是否需要确认
if seq.needs_acknowledgment():
    # 发送 S 帧确认
    pass

# 处理接收到的 I 帧
seq.on_i_frame_received(recv_seq)

# 获取未确认计数
unconfirmed = seq.unconfirmed_count
```

### 1.5 状态机

```python
from core.protocol.state_machine import ConnectionStateMachine, TimerType

def on_state_change(new_state):
    print(f"状态变更: {new_state}")

def on_timer_expired(timer_type):
    print(f"定时器超时: {timer_type}")

sm = ConnectionStateMachine(
    t0=30, t1=15, t2=10, t3=20,
    on_state_change=on_state_change,
    on_timer_expired=on_timer_expired
)

# 状态转换
sm.start()  # → CONNECTING
sm.on_connected()  # → ESTABLISHED
sm.startdt_sent()  # → STARTDT_PENDING
sm.startdt_received()  # → RUNNING
```

---

## 2. 引擎层 API

### 2.1 主站引擎

```python
from core.engine.master import MasterEngine, MasterEvent

# 创建引擎
engine = MasterEngine(
    host="192.168.1.100",
    port=2404,
    common_addr=1,
    k=12,
    w=8,
    t0=30,
    t1=15,
    t2=10,
    t3=20,
    auto_start=True,
    auto_gi=False,
    reconnect=True,
    reconnect_interval=5.0
)

# 设置回调
def on_event(event: MasterEvent, data: dict):
    print(f"事件: {event.value}, 数据: {data}")

def on_frame(data: bytes, direction: str):
    print(f"{'TX' if direction == 'tx' else 'RX'}: {data.hex()}")

engine.set_event_callback(on_event)
engine.set_raw_frame_callback(on_frame)

# 启动引擎
await engine.start()

# 发送命令
await engine.general_interrogation()
await engine.counter_interrogation()
await engine.clock_sync()
await engine.reset_process()
await engine.send_test_command()

# 发送控制命令
await engine.single_command(ioa=1, state=True, select=False, qu=0)
await engine.double_command(ioa=2, state=1, select=False, qu=0)
await engine.setpoint_shortfloat(ioa=1001, value=23.5, select=False)

# 停止引擎
await engine.stop()
```

### 2.2 子站引擎

```python
from core.engine.slave import SlaveEngine, SlaveEvent
from core.data.point_table import PointTable

# 加载点表
point_table = PointTable()
point_table.load_yaml("configs/demo_points.yaml")

# 创建引擎
engine = SlaveEngine(
    host="0.0.0.0",
    port=2404,
    common_addr=1,
    k=12,
    w=8,
    t0=30,
    t1=15,
    t2=10,
    t3=20,
    max_connections=16,
    point_table=point_table,
    spontaneous_enabled=True
)

# 设置回调
def on_event(event: SlaveEvent, data: dict):
    print(f"事件: {event.value}")

engine.set_event_callback(on_event)

# 启动引擎
await engine.start()

# 模拟数据变化
engine.simulate_yx_change(ioa=1, value=True)
engine.simulate_yc_change(ioa=1001, value=23.5)

# 自动模拟
await engine.start_simulation(
    yx_interval=5.0,
    yc_interval=2.0,
    yx_change_rate=0.1,
    yc_change_range=0.05
)
await engine.stop_simulation()

# 停止引擎
await engine.stop()
```

### 2.3 多站管理

```python
from core.engine.multi_station import MultiStationManager

# 创建管理器
manager = MultiStationManager()

# 添加站点
manager.add_station(
    station_id="station_a",
    port=2404,
    common_addr=1,
    point_table=point_table_a
)
manager.add_station(
    station_id="station_b",
    port=2405,
    common_addr=2,
    point_table=point_table_b
)

# 启动所有站点
await manager.start_all()

# 获取特定站点
station = manager.get_station("station_a")
await station.simulate_yx_change(ioa=1, value=True)

# 停止所有站点
await manager.stop_all()
```

---

## 3. 传输层 API

### 3.1 TCP 客户端

```python
from core.transport.connection import TCPClient

# 创建客户端
client = TCPClient(
    host="192.168.1.100",
    port=2404,
    timeout=10.0
)

# 设置回调
def on_connected():
    print("已连接")

def on_disconnected():
    print("已断开")

def on_data_received(data: bytes):
    print(f"收到数据: {data.hex()}")

client.set_connected_callback(on_connected)
client.set_disconnected_callback(on_disconnected)
client.set_data_callback(on_data_received)

# 连接
await client.connect()

# 发送数据
await client.send(b'\x68\x04\x01\x00\x00\x00')

# 断开
await client.disconnect()
```

### 3.2 TCP 服务端

```python
from core.transport.connection import TCPServer, TCPConnection

# 创建服务端
server = TCPServer(
    host="0.0.0.0",
    port=2404,
    max_connections=16
)

# 设置回调
def on_client_connected(conn: TCPConnection):
    print(f"客户端连接: {conn.remote_addr}")

def on_client_disconnected(conn: TCPConnection):
    print(f"客户端断开: {conn.remote_addr}")

def on_data_received(conn: TCPConnection, data: bytes):
    print(f"收到数据: {data.hex()}")
    # 回复
    await conn.send(b'\x68\x04\x01\x00\x00\x00')

server.set_client_connected_callback(on_client_connected)
server.set_client_disconnected_callback(on_client_disconnected)
server.set_data_callback(on_data_received)

# 启动服务
await server.start()

# 广播数据
await server.broadcast(b'\x68\x04\x01\x00\x00\x00')

# 停止服务
await server.stop()
```

---

## 4. 数据层 API

### 4.1 点表管理

```python
from core.data.point_table import PointTable, YxPointDef, YcPointDef

# 创建点表
pt = PointTable()
pt.station_name = "测试变电站"
pt.common_addr = 1

# 添加遥信点
pt.add_yx(YxPointDef(ioa=1, name="开关1状态"))
pt.add_yx(YxPointDef(ioa=2, name="开关2状态", initial_value=True))

# 添加遥测点
pt.add_yc(YcPointDef(ioa=1001, name="电压A", unit="V"))
pt.add_yc(YcPointDef(ioa=1002, name="电流A", unit="A"))

# 保存到 YAML
pt.save_yaml("point_table.yaml")

# 从 YAML 加载
pt2 = PointTable()
pt2.load_yaml("point_table.yaml")

# 自动生成演示点表
pt.generate_demo_points(yx_count=100, yc_count=50)
```

### 4.2 实时数据库

```python
from core.data.data_store import RealtimeDB

# 创建数据库
db = RealtimeDB(event_buffer_size=10000)

# 从点表初始化
db.init_from_point_table(point_table)

# 更新遥信值
db.update_yx(ioa=1, value=True, quality=0)

# 更新遥测值
db.update_yc(ioa=1001, value=23.5, quality=0)

# 获取数据
yx_data = db.get_yx(ioa=1)
yc_data = db.get_yc(ioa=1001)

# 获取所有数据
all_yx = db.get_all_yx()
all_yc = db.get_all_yc()

# 获取统计信息
stats = db.stats
print(f"遥信数: {stats['yx_count']}")
print(f"遥测数: {stats['yc_count']}")
```

---

## 5. Web UI API

Web 界面为**纯浏览器形态**（aiohttp REST + WebSocket + 前端静态页），后端由以下模块组成：

| 模块 | 职责 |
|------|------|
| [`webui/api_contract.md`](../webui/api_contract.md) | **REST/WS 契约表**（约 35 个端点，含请求/响应与 WS 消息形状） |
| [`webui/server.py`](../webui/server.py) | aiohttp 路由装配：`create_app()` / `run_server()` |
| [`webui/bridge.py`](../webui/bridge.py) | `EngineBridge` 门面（组合 session/points/events，保持对外 API 形状） |
| [`webui/session.py`](../webui/session.py) | `EngineSession`：主站/子站启停与协议命令门面 |
| [`webui/points.py`](../webui/points.py) | `PointService`：点表快照/批量/导入导出，同步引擎 |
| [`core/logging_manager.py`](../core/logging_manager.py) | 结构化日志（内存环形缓冲 + JSONL 轮转 + 订阅推送），供「日志」面板使用 |

```python
from webui.bridge import EngineBridge
from webui.server import create_app, run_server

bridge = EngineBridge(role="master")  # 或 "slave"
app = create_app(bridge)
run_server(role="master", host="127.0.0.1", port=8765)
# 瘦入口: apps/web_master.py / apps/web_slave.py
```

### REST 摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/master/start\|stop\|gi\|clock\|ci\|reset\|test\|read\|param\|file\|yk\|setpoint` | 主站操作 |
| POST | `/api/slave/start\|stop\|yx\|yc\|response\|sim` | 子站操作 |
| GET/POST | `/api/points`、`/api/points/yaml`、`/api/points/batch` | 点表 |
| GET | `/api/export/points.csv`、`/api/export/session.json` | 导出 |
| GET | `/api/logs`、`/api/logs/export` | 日志查询 / JSONL 导出 |

### WebSocket

| 路径 | 说明 |
|------|------|
| `/ws` | 先推 `snapshot` 快照，再增量推送 `frame` / `event` / `log` 消息 |

> 完整契约见 [`webui/api_contract.md`](../webui/api_contract.md)。本工具整体架构与任务分解见 [`architecture_plan.md`](architecture_plan.md)。

---

## 6. 配置 API

```python
from core.config import AppConfig, load_config

# 从文件加载配置
config = load_config("config.yaml")

# 手动创建配置
config = AppConfig()
config.mode = "master"
config.connection.host = "192.168.1.100"
config.connection.port = 2404
config.connection.common_addr = 1
config.timers.t0 = 30
config.timers.t1 = 15
config.flow_control.k = 12
config.flow_control.w = 8

# 保存配置
config.save("config.yaml")
```

---

## 7. 测试 API

```python
from core.testing import TestRunner, ReportGenerator

# 创建测试运行器
runner = TestRunner(report_dir="test_reports")

# 加载测试脚本
script = runner.load_script("tests/scripts/basic_test.yaml")

# 运行测试
result = await runner.run(script)

# 生成报告
ReportGenerator.save(result, "report.txt", format="text")
ReportGenerator.save(result, "report.json", format="json")
ReportGenerator.save(result, "report.html", format="html")
```

---

## 8. 录制 API

```python
from core.capture import CaptureRecorder, CapturePlayer

# 录制
recorder = CaptureRecorder("session.i104")
recorder.start()
# ... 通信过程 ...
recorder.stop()

# 回放
player = CapturePlayer("session.i104")
player.set_speed(2.0)
await player.play()

# 分析
from core.capture import CaptureAnalyzer
analyzer = CaptureAnalyzer("session.i104")
stats = analyzer.get_statistics()
print(f"总帧数: {stats.total_frames}")
print(f"I帧: {stats.i_frames}")
print(f"S帧: {stats.s_frames}")
print(f"U帧: {stats.u_frames}")
```

---

## 9. 网络模拟 API

```python
from core.simulation import NetworkSimulator

# 创建模拟器
simulator = NetworkSimulator(
    loss_rate=0.1,
    delay_ms=50,
    corrupt_rate=0.05
)

# 应用到连接
simulator.apply_to(client)

# 使用预设
from core.simulation import PresetNetwork
PresetNetwork.POOR_WIFI.apply_to(client)
```
