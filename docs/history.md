# 历史库（T17：默认开启）

历史库把变化数据（遥信/遥测/遥脉变化）、报文记录（收/发原始帧）持久化到本地
SQLite 文件，供查询、CSV 导出与事后复盘使用。**默认开启**：不传任何参数启动即建库。

## 1. 默认行为

| 项 | 默认值 |
| --- | --- |
| 是否建库 | 是 |
| 落盘路径 | `<项目根目录>/data/history.db` |
| 保留期 | 7 天 |
| 容量上限 | 512 MB |
| 批量落盘间隔 | 5 秒 |

启动日志会打印实际生效参数：

```
08:19:11 [iec104] INFO: History DB: data\history.db (retention=7d, max_size=512MB, flush_interval=5.0s)
```

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

## 6. 已知限制

- Web UI 模式目前**只建库不接线**：报文记录回调仍只在 headless/CLI 模式
  （`--no-gui`）挂接，Web 模式未注入历史库（`webui/server.py` 尚无历史库参数，
  本次未改动该文件以避免与他人改动冲突）。
- 默认落盘目录 `<项目根目录>/data/` 未加入 `.gitignore`，请在提交前确认未误提交
  `data/history.db`。
- 容量上限只保证**逻辑占用**回落到上限内；实际文件大小需靠
  `wal_checkpoint(TRUNCATE)`（已自动执行）与 SQLite 的 freelist 复用逐步收敛，
  不会立刻等于上限值。
