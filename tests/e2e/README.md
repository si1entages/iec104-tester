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
| `playwright.config.ts` + `specs/` | **前端交互 e2e（T15，Playwright，headless）**：主站连接/点表虚拟滚动/命令面板、双击不发命令红线、子站置数与应答配置、多站增删启停、日志面板、契约降级告警 | 无（webServer 自动拉起主/子站服务并回收） | 见下节 |

## 前端交互 e2e（Playwright，T15）

`specs/` 下的 `.spec.ts` 用例基于 `@playwright/test`（依赖在 `webui/frontend/package.json` 的
devDependencies 中），由 `playwright.config.ts` 托管后端进程：**自动拉起**主站(8765)/子站(8766)
（`app.py --mode master|slave --no-browser`），跑完自动回收。

**本地一条命令复现**（在仓库根目录，bash）：

```bash
NODE_PATH="$PWD/webui/frontend/node_modules" \
  webui/frontend/node_modules/.bin/playwright test --config tests/e2e/playwright.config.ts
```

> `NODE_PATH` 指向前端依赖目录，使 `tests/e2e/specs/*.ts` 能解析 `@playwright/test`
> （仓库根没有 node_modules，这是无需在根目录引包的最小方案）。
> 浏览器默认用系统 Edge（`channel: 'msedge'`，无需额外下载）；CI 上设
> `E2E_CHANNEL=chromium` 并先执行 `npx playwright install --with-deps chromium`。

### CI 运行（`.github/workflows/ci.yml` 的 `frontend-e2e` job）

CI（ubuntu runner）上每次 push/PR 自动运行，与既有 lint/test/frontend job **并行**：

1. 建**仓库根 venv** 并 `pip install -r requirements.txt` —— e2e 的 webServer
   用 `venv/bin/python`（Linux 分支）拉起 `app.py --mode master|slave --no-browser`，
   没有这步 webServer 起不来；
2. `npm ci` + `npm run build`（保证 e2e 所见 SPA 与源码一致）+ `npx vitest run`；
3. `npx playwright install --with-deps chromium`（runner 无系统 Edge，必须用
   chromium 通道：`E2E_CHANNEL=chromium`）；
4. `NODE_PATH="$PWD/webui/frontend/node_modules" webui/frontend/node_modules/.bin/playwright
   test --config tests/e2e/playwright.config.ts`；
5. 失败时上传 `tests/e2e/.playwright-artifacts/` 为 artifact 辅助排查。

**Windows 本地两坑在 CI（Linux）上的对应处理**：

| 本地坑 | CI 上的情况 |
|--------|------------|
| 系统代理导致 Playwright 可用性探测误判 200、webServer 不被拉起 | `playwright.config.ts` 顶部**无条件删除**全部 `*_proxy` 环境变量（CI 同样生效；GitHub runner 默认无代理，双保险） |
| webServer 命令经 cmd.exe 执行，程序路径必须用反斜杠 | 配置里按 `process.platform === 'win32'` 分支选择 `venv\Scripts\python.exe` / `venv/bin/python`，CI（Linux）自动走正斜杠分支，无需处理 |
| 默认浏览器为系统 Edge（msedge） | CI 显式 `E2E_CHANNEL=chromium` + `playwright install --with-deps chromium` |

另注意：e2e 串行（`workers: 1`，主/子站共用 IEC 2404）、CI 上
`reuseExistingServer` 自动关闭（`process.env.CI` 判断）——不会复用也不会
误撞 runner 上不存在的服务。

> **本机并行开发跑 e2e 的提醒**：非 CI 环境下 `reuseExistingServer` 是开启的，
> 若 8765/8766 已被**别人的**服务（队友在跑测试/调试）占用，Playwright 会
> 直接复用那个服务，造成跨工程串台的假失败/假通过。因此并行开发时跑 e2e
> 务必 `CI=1`（强制新起 webServer）或先清端口：
>
> ```bash
> netstat -ano | grep -E ":(8765|8766|2404) .*LISTENING"   # 先看占用
> CI=1 E2E_CHANNEL=msedge webui/frontend/node_modules/.bin/playwright test \
>   --config tests/e2e/playwright.config.ts
> ```
>
> 另外 Windows 上连环跑两轮 e2e 时，2404 的 TIME_WAIT 可能尚未消散，
> 第二轮 `/api/slave/start` 绑定会失败——两轮间隔 ≥60s（CI/Linux 无此问题）。

用例清单（15 个，见 `specs/*.spec.ts`）：

- 主站：UI 连接建立 → 点表虚拟滚动（**DOM 行数远小于总行数**，T12 验收）→ 选中行 →
  命令面板下发（断言请求体）→ **红线：双击点表行不产生任何 `/api/master/*` POST**
- 子站：YX/YC/YM 手动置数（请求体断言）、STEP 置数（输入 200 夹紧到 63）、
  应答行为配置（`wrong_cot`/`drop_rate` 请求体断言）
- 多站：添加站 → 启动 → 聚合状态可见 → 停止 → 删除（独立端口 15002，避开 2404）
- 日志：级别过滤、暂停后恢复不丢缓冲、导出（附件头 + 非空）
- 契约：伪造 `schemaVersion=99` → 降级告警横幅、外壳不崩溃（WS 经 `routeWebSocket` 吞掉）

端口占用：8765 / 8766 / 2404（主/子站）与 15002（多站用例，跑完即停删），
**勿与 pytest 并行运行**。

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
>
> 注：`qa_joint_debug.py` 是**仅本地开发使用的临时调试脚本，未纳入版本控制**
> （位于被 `.gitignore` 忽略的 `qa_verify/`，干净克隆中不存在）。本目录下
> `qa_full_flow.py` / `qa_webui_e2e.py` / `qa_shutdown.py` 才是已入库、可在干净克隆中
> 独立运行的验收脚本（其可复用部分见 `qa_common.py`）。
