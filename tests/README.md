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

- 当前基线：**1049 passed**。

### 覆盖率

测试带覆盖率门禁（针对 `core/`）：

```bash
python -m pytest tests/ -q --cov=core --cov-report=term-missing
```

- **当前实测覆盖率：90%**（`core/` 未覆盖约 900 条语句；语句总数随并行开发小幅漂移，此处只锚定百分比）。
- **CI 门禁**：`--cov-fail-under=88`（低于实测约 2 个点，避免跨 Python 版本/环境的正常抖动导致误红）。
- **提升目标：已达 85%**（当前 90%）。**注意：总数字会掩盖分布问题**，故下面把全部未达
  85% 的单模块列成**待后续补测清单**（覆盖率与缺口为测量时点值，精确行号见
  `python -m pytest tests/ -q --cov=core --cov-report=term-missing` 的 `Missing` 列）。

#### 待后续补测清单（单模块 < 85%，尚未完成）

| 模块 | 覆盖率 | 缺口性质 | 补测落点 |
|---|---|---|---|
| `core/engine/scheduler.py` | 55% | 定时任务管理 API（`add_task`/`remove_task`/`enable`/`disable`）与**主调度循环**几乎未覆盖：到期分派（协程 vs 同步回调）、`run_count`/`error_count` 统计、`auto_restart=False` 时出错自动禁用 | 注入受控时钟 + 直接驱动调度循环一轮，断言到期分派与异常计数/禁用行为 |
| `core/engine/slave_session.py` | 69% | 子站会话的收发/超时/重连分支大量未覆盖（缺口行见 `Missing` 列） | 参照 `tests/test_slave_engine.py` 的 Mock 传输层手法补会话级用例 |
| `core/engine/master_protocol.py` | 75% | 总召唤响应的**多类型分支**（`process_interrogation_response` 按数据类型逐分支）、文件传输收发分支、其余按 TypeID 的解析分支 | 按 TypeID 表驱动构造 ASDU，逐类型断言入库结果 |
| `core/engine/master_session.py` | 75% | 定时器超时处置与连接生命周期分支未覆盖（缺口行见 `Missing` 列） | 显式驱动定时器回调与状态机迁移，Mock 传输层 |
| `core/engine/slave_sim.py` | 75% | 自发上送仿真的周期 tick / 品质位组合分支覆盖不足 | 显式驱动 tick，断言上送报文内容 |
| `core/engine/multi_station.py` | 82% | 聚合只读接口（`get_all_station_status` / `get_summary`）与 `start_simulation` 的多站分支未覆盖 | Mock 子引擎，断言聚合与多站启停/隔离行为 |
| `core/data/data_store.py` | 83% | 品质位/时标异常与容量边界分支未覆盖（缺口行见 `Missing` 列） | 边界值与异常品质组合用例 |

- `core/transport/client.py`、`core/transport/server.py` 为 0% 是**预期且正确**的：两者各仅 2 行，
  是**兼容性 re-export 垫片**（实现在 `connection.py` / 服务端实现），其语句只在直接
  `import` 该模块时执行。**不应为它们编造测试来刷数字。**

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
python -m pytest tests/ -q --basetemp=.pytest-tmp
```

---

## 排障：看起来像「偶发失败」的环境噪声

**症状**：全量跑退出码非 0（常见为 1），但输出里**没有任何 `F` / `E`**——进度行全是 `.`，
甚至最后的 `passed` 汇总行整段缺失；**同一命令立刻复跑又全绿**，单文件跑也全绿。

**先查这一条，再怀疑测试**：pytest 默认把临时根放在**跨会话共享**的目录
（Windows `%TEMP%\pytest-of-<user>`、Linux `/tmp/pytest-of-<user>`）。历次会话遗留的
`pytest-N` / `garbage-*` 目录会无界累积。累积量变大后：

- 收集阶段明显变慢；
- 在带「批量删除需人工确认」类安全钩子的环境（本地 agent 沙箱、部分企业终端管控）里，
  pytest 清理这些目录会触发钩子，**截断 stdout 并让进程以非 0 退出** —— 表现就是
  「没有 F/E 的假红灯」。

**排查与规避**：

```bash
# 1) 看共享临时根里堆了多少
ls /tmp/pytest-of-$(whoami) | wc -l          # Linux/macOS
ls "$TEMP/pytest-of-$USERNAME" | wc -l       # Windows(Git Bash)

# 2) 用仓库内的 basetemp：每次会话开始 pytest 会清空重建该目录，累积被限定在有界范围内
python -m pytest tests/ -q --basetemp=.pytest-tmp
```

CI 已默认带上 `--basetemp=.pytest-tmp`（见 `.github/workflows/ci.yml`），本地建议同样带上。

> **判定原则**：见到「无 F/E 的非 0 退出」先按本节归因；只有在**能看到具体失败用例名与
> 断言差异**时才当作真实测试失败处理。
>
> **注意**：在多人共享的脏工作区上跑全量并据此下结论本身也不可靠——其他人在跑的过程中
> 半写 `core/**`、`tests/**` 会导致收集期 ImportError，同样表现为「全量偶发失败、单测通过」。
> 判定性验证请用干净 worktree / 独立检出。
