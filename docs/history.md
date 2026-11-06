# 历史库（T17：默认开启）

历史库把变化数据（遥信/遥测/遥脉变化）、报文记录（收/发原始帧）持久化到本地
SQLite 文件，供查询、CSV 导出与事后复盘使用。**默认开启**：不传任何参数启动即建库。

## 1. 默认行为

| 项 | 默认值 |
| --- | --- |
| 是否建库 | 是 |
| 落盘路径 | `<项目根目录>/data/history_master.db`（主站）<br>`<项目根目录>/data/history_slave.db`（子站） |
| 保留期 | 7 天 |
| 容量上限 | 512 MB |
| 批量落盘间隔 | 5 秒 |

启动日志会打印实际生效参数：

```
08:19:11 [iec104] INFO: History DB: data\history_slave.db (retention=7d, max_size=512MB, flush_interval=5.0s)
```

> **为什么默认文件名带角色后缀？** 主站（HTTP 8765）与子站（HTTP 8766）
> 按 README 的用法可**同时运行**且共用同一默认目录。若两者写同一个库文件：
> ① `frame_history` 没有角色列，两边的帧混在一起无法区分；
> ② 任一进程的保留期/容量清理会把对方的记录当「最旧数据」删掉。
> 故默认按角色分文件。显式 `--history-db <path>` 时以用户指定为准，不加后缀
> （此时如有并发需要，请自行保证是同一个进程或接受共享语义）。

## 2. 配置

`configs/slave_config.yaml` / `configs/master_config.yaml` 已给出示例段：

```yaml
history:
  enabled: true          # false = 不建库（等价于 --no-history）
  dir: ""                # 空 = <项目根目录>/data；也可写绝对路径
  retention_days: 7      # 保留天数；<=0 表示不按时间清理
  max_size_mb: 512       # 库文件容量上限(MB)；<=0 表示不限制
  flush_interval: 5.0    # 后台批量落盘间隔(秒)；<=0 表示仅手动/退出时刷盘
```

### 命令行开关

| 开关 | 说明 |
| --- | --- |
| `--no-history` | 关闭历史库（优先级最高，覆盖 `--history-db` 与配置） |
| `--history-db <path>` | 指定落盘文件；即使配置里 `enabled: false` 也会建库 |

优先级：`--no-history` > `--history-db` > `config.history.enabled`。

### 关闭方式

```bash
# 临时关闭（本次运行）
python app.py --mode slave --no-history

# 永久关闭（写入配置）
# history: {enabled: false}
```

## 3. 清理策略

`flush()` 之后按顺序执行三条**相互独立**的策略（各自未启用即跳过）：

1. **保留期** `retention_days`：删除 `timestamp < now - retention_days*86400` 的记录。
2. **记录条数** `max_records`：每张表最多保留的条数（代码默认 100 万，未暴露到 YAML）。
3. **容量上限** `max_size_mb`：按最旧优先分批淘汰，直到低于上限或表已空。

容量判定使用 SQLite 的**逻辑占用** `(page_count - freelist_count) × page_size`：
删除行后 SQLite 只把页标记为空闲（freelist）而不会立刻收缩文件，用逻辑占用衡量
可保证清理循环必然收敛；清理结束后执行 `wal_checkpoint(TRUNCATE)` 收口 WAL，
磁盘占用随之回落。

清理失败（如连接中断、并发读者占锁）只记 warning，不影响写入路径。

## 4. 容量估算与写放大实测

### 4.1 实测方法与结果

在临时目录建库，写入 10 万条报文记录 + 10 万条变化记录，每 5000 条 `flush()` 一次，
最后 `wal_checkpoint(TRUNCATE)`，统计 `history.db` + `-wal` + `-shm` 的磁盘占用，
与"原始数据量"对比。原始数据量定义为：报文 = 帧字节数（典型 I 帧 6B APCI + 20B
ASDU = 26B），变化数据 = 24B 逻辑载荷。

| 场景 | 记录数 | 原始数据 | 落盘占用 | **写放大** | 单条占用 | 100 万条估算 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 报文记录（26B/帧） | 100,000 | 2.60 MB | 11.13 MB | **4.28×** | 111 B | ≈ 106 MiB |
| 变化数据（24B/条） | 100,000 | 2.40 MB | 8.09 MB | **3.37×** | 81 B | ≈ 77 MiB |
| 合计（各 10 万） | 200,000 | 5.00 MB | 19.15 MB | **3.83×** | 96 B | ≈ 91 MiB |

吞吐（本机：Python 3.14 / SQLite WAL / `synchronous=NORMAL`）：

- 报文记录 ≈ 24 万条/秒
- 变化数据 ≈ 19 万条/秒

### 4.2 结论

- **写放大 ≈ 3.4× ~ 4.3×，可由单条占用 ≈ 96 B 外推容量**：
  100 万条 ≈ 91 MiB，默认 `max_size_mb: 512` 约可容纳 **550 万条**，
  按 7 天保留期折算可支撑约 **9 条/秒** 的持续落盘。
- 放大来源（按贡献排序）：
  1. **十六进制文本编码**——`frame_history.hex_data` 以 `hex().upper()` 存字符串，
     1 字节 → 2 个字符（UTF-8 下 2 字节），仅此一项即 2×；
  2. **SQLite 行开销**——每行约 40~50 B 的页头/记录头/空闲空洞；
  3. **索引**——`frame_history` 维护 2 个索引（`timestamp`、`direction`），
     这也是报文记录单条占用（111 B）高于变化数据（81 B）的主要原因。
- **优化方向（本次未实施，避免改动既有导出/查询契约）**：
  把 `hex_data` 改存 `BLOB`（原始字节）可把该列压回 1×，预计报文记录
  单条占用从 111 B 降到约 70 B（写放大 4.28× → 约 2.7×）；
  或按需关闭 `direction` 索引。若后续确需支撑更高写入率可再评估。
- **写入路径开销可忽略**：单条写入只入内存缓冲（deque），实际落盘由批量
  `executemany` 完成，19~24 万条/秒的吞吐远高于 104 链路常见报文率，
  故历史库持续写入**不构成性能瓶颈**；真正的成本是磁盘占用而非 CPU。

### 4.3 复现方式

```python
import shutil, tempfile, time
from pathlib import Path
from core.data.history import HistoryDB

N, FRAME, DATA = 100_000, 26, 24
def disk(p):
    return sum(Path(str(p) + s).stat().st_size
               for s in ("", "-wal", "-shm") if Path(str(p) + s).exists())

tmp = Path(tempfile.mkdtemp())
db = HistoryDB(tmp / "history.db", retention_days=0, max_size_mb=0,
               buffer_size=1_000_000)
db.open()
for i in range(N):
    db.record_frame("rx", bytes(FRAME), frame_type="I", parsed="p" * 8,
                    client_id="c1", timestamp=1.7e9 + i)
    if (i + 1) % 5000 == 0:
        db.flush()
db.flush()
with db._lock:
    db._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
raw, used = N * FRAME, disk(tmp / "history.db")
print(f"写放大 = {used / raw:.2f}x, 单条 = {used / N:.0f} B")
db.close(); shutil.rmtree(tmp, ignore_errors=True)
```

## 5. 缓冲区与丢记录告警

写入先进入内存缓冲区（默认上限 5 万条/表），由 `flush()` 批量落盘。历史库默认
开启后，写入速率可能远高于刷盘频率，因此：

- 缓冲区上限**可配置**（构造函数 `buffer_size`，默认 50000）；超限时丢弃**最旧**
  记录，并把丢弃数累加到 `get_stats()["dropped_records"]`，同时按水位打印 warning，
  避免静默丢数据。
- `flush_interval` 配合 `auto_flush=True` 时由后台守护线程定时刷盘；
  该线程用 `threading.Event` 等待，`close()` 可立即唤醒，不会拖延退出。
  默认 `auto_flush=False`，保持"仅显式 `flush()` 落盘"的既有语义。

`get_stats()` 还提供 `db_size_bytes`（逻辑占用），可用于自建监控。

## 7. 其他已知限制

- 默认落盘目录 `<项目根目录>/data/` 已在 `.gitignore` 中以 `/data/` 排除
  （前导斜杠锚定仓库根，避免连 `core/data/` 源码包一起忽略）。若需入库示例数据，
  请放到明确的示例目录而不是 `data/`。
- 容量上限只保证**逻辑占用**回落到上限内；实际文件大小需靠
  `wal_checkpoint(TRUNCATE)`（已自动执行）与 SQLite 的 freelist 复用逐步收敛，
  不会立刻等于上限值。
- 若上限小于建表本身的开销（约数十 KB），清理会把表删空——这是策略的必然结果，
  不是缺陷；请勿把 `max_size_mb` 设得比空库还小。

## 6. 并发写与多会话

### 6.1 结论

**「同角色单实例 + 跨进程共享同一库文件」是安全的：WAL + `busy_timeout` 把并发写
串行化，实测零失败零丢失。默认按角色分文件，避免跨角色语义混淆。**

### 6.2 实测（非推测）

用真实独立进程（`subprocess` 拉起 N 个 Python 进程）同时向同一个库文件写入
报文 + 变化数据，每 200 条 flush 一次：

| 并发进程数 | 每进程记录数 | 期望总帧 | 实际总帧 | 期望总数据 | 实际总数据 | 异常/锁告警 | 耗时 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 2,000 | 4,000 | **4,000** | 4,000 | **4,000** | 0 | 0.7s |
| 4 | 2,000 | 8,000 | **8,000** | 8,000 | **8,000** | 0 | 0.9s |
| 8 | 3,000 | 24,000 | **24,000** | 24,000 | **24,000** | 0 | 1.3s |

- **零 `database is locked`、零记录丢失。** 保障来自：
  `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000`（连接建立时显式设置）
  —— 写冲突时等待而非直接报错；SQLite 的 WAL 允许「多读单写」并发。
- **同进程内**：一个 `HistoryDB` 只有一条连接，所有读写经 `threading.Lock`
  （`flush` / 查询 / 建表 / 统计 / 导出分批）串行化，天然安全。
- **跨进程**：`check_same_thread=False` 仅作用于进程内；跨进程靠 SQLite
  文件锁 + `busy_timeout` 串行化。

### 6.3 已实测的边界与限制

- 若把 `busy_timeout` 降为 0，高并发下会立刻出现 `database is locked`
  （当前实现为 5000ms，未做压测到持续超时的场景）。
- 容量上限清理会执行 `wal_checkpoint(TRUNCATE)`，多进程同时清理会互相等待，
  实测（4 进程 + 极小容量上限）未出现异常，但该路径**依赖 `busy_timeout`**。
- **未做**：网络文件系统（NFS/SMB）上的 SQLite 锁语义未验证，不建议把库放到
  网络盘。
- **未做**：跨进程「共享一个库并由任一方清理」的**语义**是危险的——清理按
  `timestamp` 全局淘汰，会删掉其他角色/其他客户端的数据。这正是默认按角色
  分文件的原因；显式 `--history-db` 共享时需自行接受该语义。

### 6.4 Web 模式的接线

Web 模式下所有收发帧的唯一汇聚点是 `webui/bridge.py:EngineBridge._on_raw_frame()`
（`webui/events.py` 的 `EventBus` 只有 asyncio.Queue 订阅、无监听器 hook，
故接线落在此处）。`run_server` / `_run` / `run_web` 均新增**向后兼容的可选
关键字参数** `history_db=None`：

- 不传 → 不记录，行为与改动前完全一致；
- 传入已 `open()` 的 `HistoryDB` → Web 模式把收发报文落盘；
- 历史库写失败只记 warning，**不影响报文主路径与 WS 推送**；
- WS `frame` 消息结构不变（`direction/len/hex/client`），前端契约不受影响。

端到端验证见 `tests/test_web_history_wiring.py::TestWebModeEndToEnd`：
真 TCP 起子站 → 真 `MasterEngine` 连接并完成 STARTDT → 断言库中确有双向帧。

## 8. Web 历史查询页（T32）

历史库的浏览器查询入口（主站/子站导航「历史」）：

- **过滤**：时间范围（`RangePicker`，含时分秒）、点位类型（YX/YC/YM）、IOA（数据页签）、
  报文方向 RX/TX（报文页签）；「查询」按钮触发，不做自动轮询（历史是存量数据）。
- **展示**：数据 / 报文两个页签，按时间戳新→旧；顶部统计标签展示记录数、待落盘数、
  丢记录累计、库占用与最早/最新数据日期。
- **导出**：按当前过滤条件导出 CSV（数据 6 列 / 报文 6 列，上限 20 万行）。
- **未启用**：`--no-history` 启动时页面显示提示、导出按钮禁用。

REST 契约见 [`webui/api_contract.md`](../webui/api_contract.md) §2.11 / §4.9：

```
GET /api/history/stats     # 统计
GET /api/history/data      # point_type / ioa / start / end / limit
GET /api/history/frames    # direction / start / end / limit
GET /api/history/export    # type=data|frames + 同上过滤参数 → text/csv
```

后端接线测试 `tests/test_webui_history_endpoints.py`（4 例：未启用 / 过滤与统计 /
参数校验 400 / CSV 导出），前端 `HistoryPage.test.tsx`（3 例：渲染 / 页签切换 / 未启用态）。
