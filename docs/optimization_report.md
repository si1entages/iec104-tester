# IEC104 Tester 项目优化报告

> 生成时间：2026-09-24 | 代码总量：~21,195 行 Python | 371 测试用例

---

## 一、P0 严重问题（影响性能/正确性/安全）

### 1. asdu.py 字典每次调用重建（性能瓶颈）

**位置**: `core/protocol/asdu.py:181-358` — `_decode_object_data()` 方法

**问题**: 每次解码一个 ASDU 对象时，在方法内部重新构造 3 个字典（`handlers` 约 100 条目、`timed_types` 24 条目、`cp56_types` 12 条目），共计约 136 个条目。在高吞吐场景（数千帧/秒）下是严重性能瓶颈。

**修复方案**:
```python
# 将字典提升为类属性或模块级常量
class ASDU:
    _DECODERS: dict[TypeID, tuple] = None  # lazy init
    
    @classmethod
    def _get_decoders(cls):
        if cls._DECODERS is None:
            cls._DECODERS = {
                TypeID.M_SP_NA_1: (1, lambda d: SinglePoint.from_bytes(d)),
                # ...
            }
        return cls._DECODERS
```

**预期收益**: 帧解码性能提升 3-5x。

---

### 2. history.py 同步 SQLite 阻塞事件循环

**位置**: `core/data/history.py:153-181` — `flush()` 方法

**问题**: `HistoryDB.flush()` 使用 `sqlite3` 同步 API，但被 asyncio 引擎层调用（`master.py:247`、`slave.py:400`），会阻塞事件循环。在 1000+ 帧/秒场景下卡住主循环。

**修复方案**:
```python
# 方案 A: 用 asyncio.to_thread 包装
await asyncio.to_thread(self._history_db.flush)

# 方案 B: 后台线程 + 队列
# 启动独立线程消费写入队列，主循环只做 put_nowait
```

---

### 3. config.py 配置 roundtrip bug

**位置**: `core/config.py:184-188` — `load_config()` 方法

**问题**: `save()` 保存了 `hex_view_bytes_per_line` 和 `table_page_size` 两个字段（行 124-125），但 `load_config()` 加载时遗漏了这两个字段，导致用户保存的配置值被丢弃。

**修复方案**: 在 `load_config()` 的 display 加载段补充：
```python
cfg.display.hex_view_bytes_per_line = disp.get('hex_view_bytes_per_line', cfg.display.hex_view_bytes_per_line)
cfg.display.table_page_size = disp.get('table_page_size', cfg.display.table_page_size)
```

---

### 4. webui/server.py API 无输入校验

**位置**: `webui/server.py` — 12 处 API 端点（行 36, 59, 67, 83, 87, 93, 116, 126, 130, 137, 148, 152）

**问题**: 每个端点直接 `body = await request.json()` 后立即访问 `body["ioa"]` 等字段，无 try/except，JSON 格式错误或字段缺失会抛 500 而非 4xx。

**修复方案**:
```python
async def api_yk(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    ioa = body.get("ioa")
    if not isinstance(ioa, int) or ioa < 0:
        return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
    ...
```

---

### 5. simulation/proxy.py TX 拦截未实现

**位置**: `core/simulation/proxy.py:99-106` — `install_on_engine()`

**问题**: `install_on_engine` 只是赋值 `self._engine = engine`，没有实际安装 TX 拦截。`wrap_tx_callback` 从未被调用，TX 方向的丢包/延迟/损坏完全不工作。同时乱序功能 `_reorder_buffer` 定义了但从未使用。

**修复方案**: 在 `install_on_engine` 中实际安装 TX 拦截回调；实现 `_reorder_buffer` 的消费逻辑。

---

### 6. assertions.py 遮蔽内置 AssertionError

**位置**: `core/testing/assertions.py:13`

**问题**: `class AssertionError(Exception)` 与 Python 内置 `AssertionError` 同名，遮蔽了内置异常。如果其他代码使用 `assert` 语句失败，异常处理会混淆。

**修复方案**: 重命名为 `AssertionFailed` 或 `TestAssertionError`。

---

## 二、P1 中等问题（影响可维护性/可扩展性）

### 7. master.py 命令发送样板重复（~315 行重复代码）

**位置**: `core/engine/master.py:268-582` — 15 个命令方法

**问题**: `general_interrogation`、`single_command`、`double_command` 等 15 个方法都重复相同的样板：状态检查 → 构造 ASDU → 获取序列号 → 编码帧 → 发送。

**修复方案**: 抽取通用方法：
```python
async def _send_command_asdu(self, asdu_data: bytes) -> None:
    if not self._state_machine.is_running:
        raise RuntimeError("Not in running state")
    tx_seq = self._seq.get_send_seq()
    rx_seq = self._seq.get_recv_seq()
    frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)
    self._state_machine.on_i_frame_sent()
    await self._send_frame(frame)
```

---

### 8. slave.py 命令处理重复

**位置**: `core/engine/slave.py:955-1325` — 6 个命令处理方法

**问题**: `_handle_single_command`、`_handle_double_command` 等 6 个方法重复"选择-执行-否定确认-DEACTCON"逻辑，仅 type_id 不同。

**修复方案**: 抽取 `_build_command_ack(asdu, type_id, cot, obj)` 助手方法。

---

### 9. God Class 需拆分

| 文件 | 行数 | 方法数 | 建议拆分 |
|------|------|--------|---------|
| `slave.py` | 1740 | ~60 | SlaveEngine + CommandHandler + InterrogationHandler + SimulationService + ClientManager |
| `master.py` | 1326 | ~50 | MasterEngine + CommandSender + AsduProcessor + ConnectionManager |
| `asdu.py` | 1167 | — | ASDU + ASDUBuilder(独立模块) + APDU |
| `types.py` | 1505 | — | 按类别拆为 enums/points/commands/time/file_transfer |

---

### 10. build/ 引用未声明 PySide6

**位置**: `build/build.py:18-22`、`build/build_linux.py:25-29`、`build/build_windows.py:29-33`

**问题**: 打包脚本添加了 `--hidden-import PySide6.*` 和 `--collect-all PySide6`，但项目实际使用 aiohttp + pywebview，不是 PySide6。这些隐藏导入是死代码，增加数百 MB 打包体积。

**修复方案**: 删除所有 PySide6 相关的 hidden-import 和 collect-all 行；替换为 pywebview 相关导入。

---

### 11. 多处访问私有属性破坏封装

| 位置 | 问题 |
|------|------|
| `core/testing/actions.py:85,89` | `engine._host`、`engine._port` |
| `app.py:192-193` | `runner._on_step_complete = on_step` |
| `core/simulation/manager.py:99` | `getattr(engine, '_raw_frame_callback')` |

**修复方案**: 添加公共 property 暴露所需信息。

---

### 12. buffer 无上限增长（内存泄漏风险）

**位置**: `core/engine/master.py` / `slave.py` — `_rx_buffer` / `_tx_buffer`

**问题**: 使用普通 `list` 存储帧缓冲，无 maxlen 限制。Web UI 每 500ms 调用一次，长时间运行内存持续增长。

**修复方案**: 使用 `collections.deque(maxlen=1000)` 替换 list。

---

## 三、P2 低风险问题

### 13. print 替代 logging
- `core/data/history.py:184` — `print(f"History flush error: {e}")` → 改为 `logger.error()`
- `core/data/history.py:213` — `except Exception: pass` → 至少 `logger.warning()`

### 14. 硬编码值
- `app.py:151` — Web UI 端口硬编码 8765/8766
- `core/engine/slave.py:725-728` — 帧批次大小定义在方法内部
- `core/engine/master.py:900` — `asyncio.sleep(0.5)` 自动总召唤延迟
- `core/engine/slave.py:1294` — `delay_ms = 100`

### 15. 已弃用 API
- `core/simulation/proxy.py:148` — `asyncio.get_event_loop()` → `asyncio.get_running_loop()`
- `core/simulation/manager.py:172` — `__import__('time')` → 正常 `import time`

### 16. 配置文件重复
- `master_config.yaml` 和 `slave_config.yaml` 大量重复 → 抽取公共基础 + 角色覆盖

### 17. pyproject.toml 与 requirements.txt 不同步
- pyproject.toml 把 dev/build 放 `[project.optional-dependencies]`
- requirements.txt 把 dev/build 注释掉
- 建议统一使用 `pyproject.toml` 作为单一真相源

---

## 四、测试覆盖缺口

### 完全无单元测试的 22 个核心模块

| 优先级 | 模块 | 行数 | 风险 |
|--------|------|------|------|
| 高 | `core/data/data_store.py` | 470 | 实时数据库核心 |
| 高 | `core/data/point_table.py` | 439 | 点表管理 |
| 高 | `core/data/history.py` | 396 | SQLite 持久化 |
| 高 | `core/config.py` | 198 | 配置管理(已有roundtrip bug) |
| 高 | `core/capture/recorder.py` | 323 | 报文录制 |
| 高 | `core/capture/player.py` | 341 | 报文回放 |
| 高 | `core/testing/runner.py` | 338 | 测试运行器 |
| 高 | `core/testing/actions.py` | 416 | 动作注册表 |
| 高 | `core/testing/assertions.py` | 285 | 断言引擎 |
| 中 | `core/protocol/io.py` | 242 | IO 处理 |
| 中 | `core/protocol/file_transfer.py` | 381 | 文件传输 |
| 中 | `core/capture/analyzer.py` | 344 | 报文分析 |
| 中 | `core/capture/format.py` | 315 | 录制格式 |
| 中 | `core/capture/filter.py` | 184 | 帧过滤 |
| 中 | `core/testing/context.py` | 203 | 测试上下文 |
| 中 | `core/testing/script.py` | 158 | 脚本加载器 |
| 中 | `core/testing/report.py` | 239 | 报告生成器 |
| 中 | `core/simulation/manager.py` | 176 | 模拟管理器 |
| 中 | `core/simulation/proxy.py` | 270 | 网络代理 |
| 中 | `core/simulation/conditions.py` | 183 | 网络条件 |
| 中 | `core/engine/scheduler.py` | 247 | 调度器 |
| 低 | `core/protocol/constants.py` | — | 常量定义 |

**总计**: 约 6,000+ 行核心代码无测试覆盖。

### 测试文件过短
- `tests/test_state_machine.py` (22 行) — 状态机只有 4 个测试
- `tests/test_sequence.py` (40 行) — 流控核心测试不足
- `tests/test_integration.py` (25 行) — 几乎为空

---

## 五、其他发现

### 帧类型判断的内联字节操作重复
4 处出现相同的 `frame[2] & 0x01` 位操作判断帧类型，应在 `apci.py` 添加 `APCICodec.frame_type_of(frame)` 静态方法。

### `_spawn` 方法重复
master.py 和 slave.py 各有相同的 `_spawn` 方法定义（~18 行），应抽取到基类。

### ASDUBuilder 40+ 静态方法重复
`asdu.py:365-1122` 的 `ASDUBuilder` 有 40+ 个 `build_X` 方法，大量样板可抽取工厂方法 `_build_single_object(type_id, common_addr, ioa, data, cot, with_time)`。

### capture/player.py 的 stop() 取消错误任务
`player.py:186` 使用 `asyncio.current_task()` 而非新创建的任务引用，`stop()` 会取消错误的任务。

### capture/recorder.py 回调签名不兼容
`recorder.py:247` 的 `make_frame_callback` 回调只接受 `data` 参数，但 slave 引擎期望 `(data, direction, client_id)` 三参数。

---

## 六、推荐优化路线图

### 阶段 1：性能与正确性修复（1-2 天）
1. asdu.py 字典提升为模块级常量
2. history.py 改用 `asyncio.to_thread()` 包装 SQLite 操作
3. config.py roundtrip bug 修复
4. webui/server.py API 输入校验
5. assertions.py 重命名 `AssertionError`
6. simulation/proxy.py 实现 TX 拦截

### 阶段 2：代码重复消除（2-3 天）
7. master.py 抽取 `_send_command_asdu()`
8. slave.py 抽取 `_build_command_ack()`
9. `_spawn` 抽取到基类
10. `APCICodec.frame_type_of()` 替换内联位操作
11. ASDUBuilder 工厂方法抽取
12. buffer 改用 `deque(maxlen=N)`

### 阶段 3：架构重构（3-5 天）
13. slave.py 拆分为 5 个模块
14. master.py 拆分为 4 个模块
15. types.py 按类别拆分
16. 清理 build/ 脚本的 PySide6 死代码
17. 公开属性替代私有属性访问

### 阶段 4：测试补全（3-5 天）
18. 为 data_store / point_table / history 补充单元测试
19. 为 config.py 补充 roundtrip 测试
20. 为 capture/ 模块补充测试
21. 为 testing/ 模块补充测试
22. 为 simulation/ 模块补充测试
23. 扩充 state_machine 和 sequence 测试

### 阶段 5：低风险清理（1 天）
24. print → logging
25. 硬编码值移入配置
26. 弃用 API 替换
27. 配置文件去重
28. pyproject.toml 与 requirements.txt 统一
