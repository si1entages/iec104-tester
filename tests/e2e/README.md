# 端到端（E2E）验收脚本

本目录存放**真实 socket / HTTP / WebSocket** 的端到端验收脚本（由原 `qa_verify/` 择优提升而来）。

> ⚠️ 这些脚本**不会被 pytest 自动收集**（文件名不以 `test_` 开头），需**手动运行**。
> 它们依赖本机端口与运行中的服务，不适合在 CI 中无人值守运行。

## 脚本清单

| 脚本 | 用途 | 前置条件 | 运行命令 |
|------|------|---------|---------|
| `qa_full_flow.py` | **全流程验收**：从零复位→启动→系统/控制命令→参数与文件→模拟→注入矩阵→点表管理→多客户端→前端 WS→关停重连 | 需先启动主站(8765)/子站(8766)服务，IEC 端口 24040 | `python tests/e2e/qa_full_flow.py [--shots]` |
| `qa_shutdown.py` | **关停与资源泄漏回归**：传输层/引擎层 `stop()` 耗时与 `wait_closed` 告警（真 socket） | 无（自包含，自动分配端口） | `python tests/e2e/qa_shutdown.py` |
| `qa_real_device.py` | **真机只读功能矩阵**：对运行中的主站服务跑总召/累计量/对时/读/测试/复位（默认不发控制类命令） | 需主站已连真机并运行 | `python tests/e2e/qa_real_device.py [--base http://127.0.0.1:8765] [--yk]` |
| `qa_master_sbo.py` | **主站侧 SBO 两段式**：自动补选择、选择被拒/超时中止、竞态（真 TCP 回环 + 假子站） | 无（自包含） | `python tests/e2e/qa_master_sbo.py` |
| `qa_slave_sbo.py` | **子站侧 SBO 语义**：按点表 `sbo` 配置处理遥控/设点（真双引擎 TCP） | 无（自包含） | `python tests/e2e/qa_slave_sbo.py` |
| `qa_webui_e2e.py` | **Web UI 双端联调**：SBO true/false、显式 select、设点、错误 COT 注入 | 可 `--spawn` 自启服务，或手动启动 8765/8766 | `python tests/e2e/qa_webui_e2e.py [--spawn]` |
| `qa_common.py` | 共享工具（HTTP/WS 探针、报文解码、断言记录） | — | 被上述脚本 import，不单独运行 |

## 夹具

| 文件 | 用途 |
|------|------|
| `points_joint.yaml` | 联调点表（YX 3 + YC 1 + YK 2 + YM 1），供 `qa_full_flow.py` 注入 |
| `points_sbo_true.yaml` | SBO true/false 点表，供 `qa_webui_e2e.py` 注入 |

## 典型用法

```bash
# 全流程验收（两个终端先起服务）
python app.py --mode slave  --no-browser --port 24040
python app.py --mode master --no-browser --host 127.0.0.1 --port 24040
python tests/e2e/qa_full_flow.py --shots

# 关停回归（自包含，可直接跑）
python tests/e2e/qa_shutdown.py
```

> 端口占用提示：`qa_full_flow.py` / `qa_webui_e2e.py` / `qa_joint_debug.py` 会占用 2404/24040/8765/8766，
> **勿与 pytest 并行运行**（`tests/test_multi_station.py` 等也会绑定端口）。
