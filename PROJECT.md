# IEC 60870-5-104 Tester

## 项目用途
IEC 60870-5-104 协议测试工具，支持主站/子站模拟、报文录制回放、
网络异常模拟、一致性测试。面向电力系统 SCADA 调试和测试场景。

## 技术栈
Python 3.11+, PySide6, asyncio, struct（协议编解码）

## 架构分层
入口层: app.py / run_tests.py / run_multi_station.py / capture_tool.py / sim_tool.py
↓
GUI层: gui/ （PySide6）
  ├── main_window.py  # 纯UI容器（精简）
  ├── views/          # 主站/子站视图分离
  │   ├── base_view.py    # 共享基类
  │   ├── master_view.py  # 主站视图
  │   └── slave_view.py   # 子站视图
  ├── dialogs/        # 对话框管理
  ├── widgets/        # 通用组件
  ├── master/         # 主站专用组件
  └── slave/          # 子站专用组件
↓
引擎层: core/engine/ （主站/子站/多站）
↓
协议层: core/protocol/ （APCI/ASDU/类型/流控/状态机/文件传输）
↓
传输层: core/transport/ （TCP async）
↓
数据层: core/data/ （点表、实时数据模型）


## 核心模块速查

| 模块 | 职责 | 修改频率 |
|------|------|---------|
| core/protocol/asdu.py | ASDU 编解码，TypeIdentifier → 解析逻辑映射 | 高 |
| core/protocol/types.py | 59 种 TypeID 枚举定义 | 低 |
| core/protocol/apci.py | APCI 帧头编解码（I/S/U 格式） | 低 |
| core/protocol/sequence.py | k/w 流控计数器 | 中 |
| core/protocol/state_machine.py | START/STOP/TEST 状态机 | 中 |
| core/protocol/file_transfer.py | IEC 104 文件传输（目录/读/写） | 低 |
| core/engine/master.py | 主站引擎（发送命令、处理响应） | 高 |
| core/engine/slave.py | 子站引擎（响应召唤、上报数据） | 高 |
| core/engine/multi_station.py | 多站并发管理 | 中 |
| core/transport/ | TCP 异步连接管理 | 低 |
| core/data/ | 点表模型、实时数据存储 | 中 |
| core/testing/ | YAML 测试脚本执行引擎 | 中 |
| core/capture/ | 报文录制/回放 | 低 |
| core/simulation/ | 网络异常模拟（丢包/延迟/乱序） | 低 |
| core/config.py | 配置管理（JSON/YAML） | 低 |

## 关键设计约定

### 协议层
- APCI: I 格式（信息）、S 格式（确认）、U 格式（控制）
- ASDU 结构: TypeID(1B) + SQ(1B) + Cause(2B) + CommonAddr(2B) + IOBs + 数据体
- 59 种 TypeID 在 types.py 用枚举定义，asdu.py 按 TypeID 分发解析
- k/w 流控: k=12（未确认上限）, w=8（确认间隔）

### 编码风格
- 协议层: 纯同步 struct.pack/unpack，无 async，无 GUI 依赖
- 引擎层: asyncio，通过 core/transport 管理 TCP 连接
- GUI 层: PySide6 信号槽通信，不直接调用 protocol 层
- 后台任务: 引擎层统一用 `_spawn()` 创建，保留任务引用并记录异常

### 测试
- 单元测试: tests/test_*.py（协议各层）
- 一致性测试: tests/conformance/test_conformance.py（42 个用例）
- 脚本测试: tests/scripts/（YAML 定义的场景测试）
- Mock 策略: 引擎层测试用 Mock 传输层，不建真连接

## 当前开发重点
<!-- 每次开工前更新这里，AI 就知道上下文 -->
- [x] 接入未使用的 GUI 面板：SimPanel、PointEditor、CapturePanel、TrendChart、MultiStationPanel
- [x] 修复 SlaveView.get_point_editor 空引用、点表批量添加列表处理
- [x] 引擎层 _spawn 安全任务调度（保留引用 + 异常日志）
- [x] README 双语链接修复、补充 requirements.txt
- [x] 响应配置面板 config_changed 应用到 SlaveEngine（ResponseBehavior）
- [x] master↔slave 真连接端到端联调（tests/test_e2e_master_slave.py）
- [x] MultiStationManager 共享事件循环稳定性验证
- [x] 修复 slave/master/transport stop 时 wait_closed 挂起（加超时）
- [x] 双应用界面：gui/master_app + gui/slave_app，入口 apps/master_main.py、apps/slave_main.py
- [x] app.py 默认新界面；--legacy-ui 保留旧一体化 GUI
- [x] PyInstaller 脚本 build/build_all.py（iec104-master / iec104-slave）
- [ ] wrong_cot 注入尚未完全落到 ASDU 构建（预留字段）
- [ ] GUI 关闭时多站管理器资源清理
- [ ] 主站定义表双击值直接发命令（需选中行后用右侧命令面板）

## 双应用入口

| 产品 | Web UI（推荐） | PySide6 桌面 | 可执行名 |
|------|----------------|--------------|----------|
| IEC104 主站 | `python apps/web_master.py` | `python apps/master_main.py` | iec104-master |
| IEC104 子站 | `python apps/web_slave.py` | `python apps/slave_main.py` | iec104-slave |
| 联调双窗 | `python apps/web_lab.py` | 分别启动两个桌面进程 | — |

Web 架构：`webui/bridge.py` 引擎桥 + `webui/server.py` aiohttp REST/WS + `webui/static` 工业深色页。
共享：`core/` 引擎。旧 `app.py` 仍可用。
