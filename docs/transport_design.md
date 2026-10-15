# 传输层设计说明（core/transport）

> 状态：`core/transport/connection.py` 为**唯一权威实现**；
> `client.py` / `server.py` 为 DEPRECATED 兼容 shim（兼容期至 2026-12-31）。
> 本文档描述三者职责、`close()` 幂等与超时契约，以及 shim 的存废策略。

## 1. 模块与类

| 类 | 文件 | 角色 |
| --- | --- | --- |
| `TCPConnection` | `connection.py` | 单个已建立 TCP 连接的封装：字节流分帧（`0x68` 起始符 + 长度域）、完整 APDU 提取、异步读写、连接级统计 |
| `TCPServer` | `connection.py` | 子站侧监听服务：接受多客户端连接、连接上限、广播 / 定向发送 |
| `TCPClient` | `connection.py` | 主站侧主动连接：连接/重连循环、生命周期与状态回调 |
| `ConnectionStats` | `connection.py` | 连接统计数据结构（收发字节/帧计数、错误、重连次数等） |

`TCPClient` 在内部**组合**一个 `TCPConnection`；`TCPServer` 为每个接入客户端
各创建一个 `TCPConnection` 并以 `conn_id`（`host:port`）索引。上层引擎
（`core.engine.master` / `core.engine.slave`）只依赖这三个类，不直接操作
`asyncio` 的 `StreamReader` / `StreamWriter`。

## 2. 关闭语义契约

### 2.1 `TCPConnection.close()` — 幂等、非阻塞

```python
def close(self) -> None:
    writer = self._writer
    try:
        if not writer.is_closing():
            writer.close()
    except Exception:
        logger.debug(...)
```

- **幂等**：以 `writer.is_closing()` 守卫，重复调用只关闭一次，可安全地在
  读循环 `finally`、`stop()`、异常处理路径中重复调用。
- **非阻塞**：只发起关闭请求，不等待底层传输真正关闭（等待由 `stop()` 负责）。
- **不抛异常**：关闭阶段的异常一律降级为 `debug` 日志。

### 2.2 `TCPConnection.stop()` — 取消读循环 + 等待关闭（1.0s 上限）

1. `self._running = False`
2. 取消并 `wait_for` 读任务（超时 1.0s，忽略 `CancelledError`/`TimeoutError`）
3. 调用 `close()`（幂等）
4. `await wait_for(self._writer.wait_closed(), timeout=1.0)`，吞掉异常

### 2.3 `TCPServer.stop()` — 逐连接停止 + 等待 server 关闭（2.0s 上限）

1. `self._running = False`
2. 对每个连接 `await wait_for(conn.stop(), timeout=2.0)`，随后 `clear()`
3. `self._server.close()` → `await wait_for(self._server.wait_closed(), timeout=2.0)`

### 2.4 为什么必须保证 `close()` 一定被调用（Python 3.13+ 陷阱）

> 历史缺陷：只「断开逻辑连接」而不关闭底层 socket 时，Python 3.13+ 的
> `Server.wait_closed()` 会等待**所有连接真正关闭**，未关闭的连接会让
> `TCPServer.stop()` 阻塞到超时，并泄漏文件描述符。

因此 `TCPConnection._read_loop()` 的 `finally` 分支**无条件**调用
`self.close()`，无论读循环因对端 EOF、异常还是取消而退出。`stop()` 亦调用
`close()`。二者共同保证：只要连接生命周期结束，底层 transport 必被关闭。

### 2.5 超时值一览

| 位置 | 超时 | 说明 |
| --- | --- | --- |
| 读循环 `reader.read` | 1.0s | 周期性超时以便检查 `_running` |
| `TCPConnection.stop` 取消读任务 | 1.0s | 防止卡死 |
| `TCPConnection.stop` `wait_closed` | 1.0s | 防止对端不响应导致挂起 |
| `TCPServer.stop` 单连接 stop | 2.0s | 上层批量关闭的每连接上限 |
| `TCPServer.stop` `wait_closed` | 2.0s | 防止 server 关闭挂起 |

**一致性结论（T06 核查）**：实现已统一遵循「幂等关闭 + 有界等待」语义，
`TCPConnection.close()` / `stop()` 与 `TCPServer.stop()` 的行为一致，无需改动；
新增本契约文档以避免后续回归（尤其 `close()` 绝不可改为阻塞等待）。

## 3. 兼容 shim 的由来与存废

- `core/transport/client.py`、`core/transport/server.py` 是早期按「主站/子站」
  拆分的两个薄模块，各仅数行 `from .connection import ...` 的 re-export。
- 现状：**仓库内已无任何对这两个 shim 的 import**（`core/`、`webui/`、
  `tests/`、顶层脚本均改为从 `core.transport.connection` 导入）。
- 保留原因：避免破坏仓库外部（下游脚本/用户代码）可能存在的历史导入路径。
- 删除时机：**兼容期 2026-12-31 之后的下一个主版本**；删除前应先确认外部
  引用已清零。删除操作即移除 `client.py` / `server.py` 两个文件，无需改动
  其它代码（`core/transport/__init__.py` 未再导出它们）。

## 4. 新增代码约定

- 传输层实现一律写在 `core/transport/connection.py`。
- **不要**新增对 `client` / `server` shim 的 import（除非修改 shim 自身）。
- 上层若需连接统计，使用 `ConnectionStats`（从 `connection` 导入）。

## 5. TLS / IEC 62351 传输层加密（T20）

### 5.1 接入方式

`TCPClient` / `TCPServer` 各新增一个**可选** `ssl_context` 参数（默认 `None`
= 明文，行为与改动前完全一致），并提供 `set_ssl_context()` 用于构造后注入、
`tls_enabled` 只读属性用于观测：

```python
server = TCPServer(host, port, ssl_context=ctx)      # 构造时
client = TCPClient(host, port)
client.set_ssl_context(ctx, "iec104.local")          # 或构造后、start() 之前
```

- `TCPServer.start()` → `asyncio.start_server(..., ssl=ctx)`。
- `TCPClient._connect_loop()` → `asyncio.open_connection(..., ssl=ctx,
  server_hostname=...)`。注意 `ssl is None` 时**不得**传 `server_hostname`
  （asyncio 会抛错），实现中已按此分支处理。
- 上下文构造与配置映射集中在 `build_server_context()` /
  `build_client_context()` / `build_context_from_config()` /
  `configure_engine_tls()`，校验失败抛 `TlsConfigError`。

### 5.2 关闭语义契约不变

TLS **不改变** §2 的契约：`TCPConnection.close()` 依旧幂等非阻塞、读循环
`finally` 依旧无条件调用 `close()`、`stop()` 的 `wait_closed` 依旧 1.0s 有界。
SSL transport 的 `wait_closed()` 同样受该超时保护；`tests/test_tls_transport.py`
中有专门用例断言 TLS 下 `close()` 可重复调用且 `stop()` 在 3s 内返回。

### 5.3 引擎注入路径

`MasterEngine` / `SlaveEngine` 构造函数接受可选 `ssl_context`（主站另有
`server_hostname`），在构造期传给内部创建的 `TCPClient` / `TCPServer`——这是
**唯一**注入路径。`configure_engine_tls()` 保留为兼容入口：内部经引擎公开方法
`set_ssl_context()` 走同一条传输层注入路径，行为与构造参数完全一致（须在引擎
`start()` 之前调用）。详见 `docs/tls.md` §5。

### 5.4 覆盖边界

**只做 TLS 传输层加密**，IEC 62351 的应用层认证、安全关联、访问控制等
**未实现**——完整清单见 `docs/tls.md` §覆盖边界。请勿表述为"支持 IEC 62351"。
