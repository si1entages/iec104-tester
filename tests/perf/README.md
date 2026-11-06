# 性能与长稳基准

默认**不参与**日常全量测试（`pyproject.toml` 的 `addopts = -m "not perf"`）。
显式运行：

```bash
# 全部性能基准（含 5s 环回 soak 冒烟）
pytest tests/perf -m perf -q

# 只跑编解码吞吐 / 10 万点快照
pytest tests/perf -m perf -q -k "not soak"

# 拉长 soak（例如 2 小时；单位秒）
IEC104_SOAK_SECONDS=7200 pytest tests/perf -m perf -q -k soak
```

## 基准项与门槛

| 测试 | 场景 | 门槛（宽松，防数量级回归） |
|---|---|---|
| `test_apci_asdu_decode_throughput` | 2 万帧 APCI+ASDU 解码 | ≥ 2,000 帧/秒 |
| `test_point_snapshot_100k` | 10 万点 `PointService.snapshot()` | < 5 秒 |
| `test_twenty_clients_concurrent_gi` | 1 子站 ↔ 20 主站并发；GI + 持续自发上送 | 聚合 ≥ 1,000 帧/秒 |
| `test_loopback_soak_no_leak` | 主站↔子站真 TCP 环回，持续总召 | 结束后任务数不增长、`tracemalloc` 增长 < 8 MB、句柄数不增长 |

soak 的时长由 `IEC104_SOAK_SECONDS` 控制（默认 5s）。20 客户端用例时长由
`IEC104_PERF_CLIENTS_SECONDS` 控制（默认 5s）。CI 不跑 perf job；
需要夜间/发版前手动跑长时段，或把 `pytest tests/perf -m perf` 加到独立 cron job。

```bash
# 20 客户端并发（默认 5s）
pytest tests/perf/test_perf_clients.py -m perf -q -s
IEC104_PERF_CLIENTS_SECONDS=60 pytest tests/perf/test_perf_clients.py -m perf -q -s

# 2 小时长稳（2026-11-06 实测：7200s / 34,765 次 GI / 内存 +0.64 MB）
IEC104_SOAK_SECONDS=7200 pytest tests/perf/test_soak_loopback.py -m perf -q -s
```

## 说明

- 门槛刻意宽松：基准的目标是发现**泄漏/数量级退化**，不是精确跑分。
- 不同机器/CI runner 的绝对值差异很大，报告里请附 CPU/OS/Python 版本。
- 若某次合法优化导致门槛需要调整，改测试里的常量并在提交信息里说明原因。
