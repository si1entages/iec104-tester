# ASDU 地址字段长度可配（WP1）

> 状态：已实现（v1.11.0 已发布）。适用于主站、子站、透明桥、离线报文解析全链路。

## 背景

IEC 60870-5-104 未强制规定 ASDU 中三个地址字段的字节数：

| 字段 | 标准常用 | 现场常见变体 |
|---|---|---|
| 公共地址 CA | 2 字节 | **1 字节** |
| 信息对象地址 IOA | 3 字节 | **1 / 2 字节** |
| 传送原因 COT | 2 字节（原因 + 源发地址） | **1 字节**（无源发地址） |

v1.10.0 及之前把 `2 / 3 / 2` 硬编码在 `core/protocol/asdu.py` 的 encode/decode 中，
且 `ASDU.decode(data, ca_length=2)` 的 9 个调用点各自固定。遇到 1 字节 CA 或
2 字节 IOA 的装置时，信息体会**整体错位且不报错**——这是「实验室能跑、现场连不上」
的典型根因。

WP1 把这三项提升为一级配置，并让发送、接收、旁路与离线解析共用同一真值源。

## 配置方式

三选一，优先级从高到低：

### 1. 命令行（现场最快捷）

```bash
python app.py --mode master --host 192.168.1.9 \
    --ca-length 1 --ioa-length 2 --cot-length 2
```

三个参数都带 `choices` 校验，非法值 argparse 直接报错。可用
`python app.py --help` 查看。

### 2. YAML 配置文件

```yaml
asdu_address:
  ca_length: 2          # 1 或 2
  ioa_length: 3         # 1 / 2 / 3
  cot_length: 2         # 1 或 2
```

完整示例见 [configs/master_config.yaml](../configs/master_config.yaml)。
CLI 参数覆盖 YAML；`--demo` 会把这些参数透传给子进程。

### 3. 程序内（库调用 / 多站 / 桥两侧隔离）

```python
from core.protocol.address import AsduAddressConfig, set_default, use_default

# 进程级默认：启动前调用，之后所有 ASDUBuilder / 引擎解码共用
set_default(AsduAddressConfig(ca_length=1, ioa_length=2, cot_length=2))

# 任务级临时覆盖：同一进程内不同链路使用不同长度，退出自动还原
with use_default(AsduAddressConfig(2, 3, 2)):
    frame = ASDUBuilder.build_general_interrogation(1)

# 单帧显式指定：离线解析工具按帧指定，优先于默认
asdu = ASDU.decode(raw, address_config=AsduAddressConfig(1, 2, 2))
```

优先级：**单帧显式 `address_config` > `ca_length` 显式 override >
`use_default` 任务级 > `set_default` 进程级 > 标准默认 2/3/2**。

## 覆盖的调用点

| 路径 | 文件 | 方式 |
|---|---|---|
| 编码（74 个 `ASDUBuilder.build_*`） | `core/protocol/asdu.py` | 自动取生效配置，**零改动** |
| 主站 I 帧解码 / 头部解码 | `core/engine/master_protocol.py` | 自动取生效配置 |
| 子站 I 帧解码 / 头部解码 | `core/engine/slave_session.py`、`slave_response.py` | 自动取生效配置 |
| 桥旁路合规监视 | `core/engine/compliance_monitor.py` | 自动取生效配置 |
| 桥帧摘要 | `core/engine/tcp_bridge.py` | 已去掉硬编码 `ca_length=2` |
| 离线报文 diff | `webui/frame_diff.py` | 已去掉硬编码 `ca_length=2` |
| 报告帧摘要 | `webui/report.py` | 已去掉硬编码 `ca_length=2` |
| 报文翻译 | `webui/frame_translate.py` | 自动取生效配置 |
| 状态页显示 | `CarbonStatusPage` / `PfStatusPage` | `/api/status` 新增 `asdu_address` 只读键 |

## 行为约定

- **默认零回归**：未做任何配置时为 2/3/2，编码逐字节与历史实现一致（由
  `tests/test_asdu_address_config.py` 的黄金向量锁定）。
- **不静默截断**：`ioa_length` 位宽装不下待发 IOA 时，`ASDU.encode()` 抛
  `ValueError` 而不是截成另一个点。现场误配不会把遥控打到错误对象上。
- **COT=1 字节**时不写源发地址，解码 `origin_addr` 恒为 0；其余字段不串位。
- **非法配置启动即报错**：`AsduAddressConfig` 在构造时校验，`load_config`
  读到非法 YAML 直接抛错，不留到帧解析阶段。
- **旧配置兼容**：YAML 缺 `asdu_address` 节时退回 2/3/2（沿用 `load_config`
  的「未知键忽略」策略）。

## 验证

```bash
# 地址配置专项（44 例，含 12 长度组合 × SQ、时标、APDU、YAML 接线）
python -m pytest tests/test_asdu_address_config.py -q

# 全量后端 + 覆盖率门禁
pytest tests/ -q --cov=core --cov=webui --cov-branch \
    --cov-report=term-missing --cov-fail-under=91
```

`tests/test_asdu_address_config.py` 覆盖：默认字节一致性、12 种长度组合 ×
SQ 开/关的 encode→decode 往返、`ca_length` 旧式 override 语义、进程级/任务级/
单帧三级优先级、CP56 时标往返、APDU 与 `decode_header` 透传、IOA 溢出拒绝、
YAML save/load 往返、旧配置兼容、非法值拒绝、`/api/status` 新增键。

### 透明桥两侧独立配置

桥默认两侧共用进程级配置。若监听侧（真实主站）与上游侧（真实子站）装置
地址长度不同，可分别指定：

```bash
# headless 桥 CLI
python app.py --mode bridge --no-gui \
    --listen-port 2404 --upstream-host 192.168.1.9 \
    --bridge-listen-ca-length 1 --bridge-listen-ioa-length 2 \
    --bridge-upstream-ca-length 2 --bridge-upstream-ioa-length 3
```

Web 桥模式通过 `POST /api/bridge/start` 的可选字段（不传则沿用进程默认）：

```json
{
  "listen_host": "0.0.0.0", "listen_port": 2404,
  "upstream_host": "192.168.1.9", "upstream_port": 2404,
  "listen_address":   {"ca_length": 1, "ioa_length": 2, "cot_length": 2},
  "upstream_address": {"ca_length": 2, "ioa_length": 3, "cot_length": 2}
}
```

两条转发任务各包 `use_default(...)`，任务级 `ContextVar` 隔离，互不串味；
未指定时 `use_default(None)` 表示**不覆盖**进程默认（不会把 `--config` 静默丢弃）。

## 已知边界

- 多站 `StationConfig` 目前仍共用进程级默认；若同一进程内多站需要不同长度，
  需在 `multi_station.py` 各站任务内包 `use_default(...)`（尚未接线）。
- `cot_length=1` 属于非标变体，仅按「不写源发地址」实现；若厂商对第 2 字节
  另有语义，需现场抓包确认后扩展。
- 本配置只改变**地址字段长度**，不改变 TypeID/信息体布局；厂商私有 ASDU
  变体仍需用 `custom_types` 或现场抓包适配。
