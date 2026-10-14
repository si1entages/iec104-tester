# 测试说明（分层测试策略）

本目录是 IEC 60870-5-104 Tester 的测试资产根目录，采用**分层测试策略**：越靠下的层越快、越靠上的层越接近真实运行环境。

```
tests/
├── conftest.py          # 共享 fixtures（协议编解码、Mock 传输层等）
├── test_*.py            # ① 单元 / 集成测试（Mock 传输层，快速回归）
├── conformance/         # ③ 一致性测试（对照 IEC 60870-5-104 标准）
├── scripts/             # YAML 场景脚本（由 run_tests.py 驱动）
└── e2e/                 # ② 真实 socket 端到端脚本（人工/联调触发，不进 pytest）
```

---

## ① 单元 / 集成测试（`tests/test_*.py`）

- **目的**：协议编解码、引擎编排、传输层、Web API、数据层的快速回归。
- **策略**：引擎层用 **Mock 传输层**，不建立真实 TCP 连接，因此可秒级完成、无端口/网络依赖，可在任意 CI 环境稳定复现。
- **运行**：

  ```bash
  python -m pytest tests/ -q          # 全量
  python -m pytest tests/test_asdu.py -q   # 单文件
  ```

- 当前基线：**489 passed**。

### 覆盖率

测试带覆盖率门禁（针对 `core/`）：

```bash
python -m pytest tests/ -q --cov=core --cov-report=term-missing
```

- **当前实测覆盖率：64%**（`core/` 共 7662 条语句，未覆盖 2787 条）。
- **CI 门禁**：`--cov-fail-under=60`（略低于实测值，避免跨 Python 版本/环境的正常抖动导致误红）。
- **提升目标**：逐步提升至 **85%**，再同步上调门禁。当前低覆盖主要集中在 `core/testing/`（YAML 脚本引擎）、`core/simulation/`（网络异常注入）、`core/capture/recorder.py`、`core/data/history.py` 等非核心链路——这些模块主要由端到端脚本覆盖，单元测试待补。

---

## ② 真实 socket 端到端脚本（`tests/e2e/`）

- **目的**：在**真实 TCP / HTTP / WebSocket** 下验证主站↔子站联调、SBO 两段式、关停资源回收、真机只读功能矩阵等。
- **特点**：依赖本机端口与运行中的服务，**不适合在 CI 中无人值守运行**，因此文件名不以 `test_` 开头，**不会被 pytest 自动收集**，需手动执行。
- **运行**：见 [`tests/e2e/README.md`](e2e/README.md)。

---

## ③ 一致性测试（`tests/conformance/`）

- **目的**：对照 IEC 60870-5-104 标准（Annex A 测试规范）逐项验证协议行为。
- **运行**：

  ```bash
  python tests/conformance/test_conformance.py
  # 或经 pytest 收集：
  python -m pytest tests/conformance/ -q
  ```

---

## ④ YAML 场景脚本（`tests/scripts/`）

- **目的**：由现场工程师以 YAML 定义「动作 + 断言」场景（连接、总召唤、遥控、网络异常等）。
- **运行**：

  ```bash
  python run_tests.py tests/scripts/            # 整个目录
  python run_tests.py tests/scripts/basic_connection_gi.yaml -v
  ```

---

## 本地一键回归

```bash
# 静态检查 + 单元/集成测试（提交前必跑）
python -m ruff check .
python -m pytest tests/ -q
```
