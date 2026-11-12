# 端到端（E2E）验收脚本

本目录存放**真实 socket / HTTP / WebSocket** 的端到端验收脚本（由原 `qa_verify/` 择优提升而来）。

> ⚠️ 这些脚本**不会被 pytest 自动收集**（文件名不以 `test_` 开头），需**手动运行**。
> 它们依赖本机端口与运行中的服务，不适合在 CI 中无人值守运行。
> **例外**：`qa_full_flow.py` 已纳入 CI（`.github/workflows/ci.yml` 的
> `e2e-full-flow` job：job 内拉起主站/子站服务 → 等就绪 → 跑 12 阶段验收 →
> 退出时回收；失败上传 `master.log` / `slave.log`）。

## 脚本清单

| 脚本 | 用途 | 前置条件 | 运行命令 |
|------|------|---------|---------|
| `qa_full_flow.py` | **全流程验收**：从零复位→启动→系统/控制命令→参数与文件→模拟→注入矩阵→点表管理→多客户端→前端 WS→关停重连（**已入 CI** `e2e-full-flow`） | 需先启动主站(8765)/子站(8766)服务，IEC 端口 24040 | `python tests/e2e/qa_full_flow.py [--shots]` |
| `qa_shutdown.py` | **关停与资源泄漏回归**：传输层/引擎层 `stop()` 耗时与 `wait_closed` 告警（真 socket） | 无（自包含，自动分配端口） | `python tests/e2e/qa_shutdown.py` |
| `qa_real_device.py` | **真机只读功能矩阵**：对运行中的主站服务跑总召/累计量/对时/读/测试/复位（默认不发控制类命令） | 需主站已连真机并运行 | `python tests/e2e/qa_real_device.py [--base http://127.0.0.1:8765] [--yk]` |
| `qa_file_transfer_probe.py` | **文件传输真机核实探针（C4，只读）**：目录召唤（默认）/可选 select/request，结构化打印 NOF/LOF/NOS/LSQ/CHS/FRQ/SRQ/AFQ，用于填写 [`docs/file_transfer_open_items.md`](../../docs/file_transfer_open_items.md) | 需主站已连真机并 Running | `python tests/e2e/qa_file_transfer_probe.py [--base URL] [--ioa N] [--select NOF] [--request NOF]` |
| `qa_master_sbo.py` | **主站侧 SBO 两段式**：自动补选择、选择被拒/超时中止、竞态（真 TCP 回环 + 假子站） | 无（自包含） | `python tests/e2e/qa_master_sbo.py` |
| `qa_slave_sbo.py` | **子站侧 SBO 语义**：按点表 `sbo` 配置处理遥控/设点（真双引擎 TCP） | 无（自包含） | `python tests/e2e/qa_slave_sbo.py` |
| `qa_interop_consumer.py` | **第三方跨栈互操作（consumer 接入）**：本仓主站逐栈连 5 个独立 104 参考站（otfabric/iec104-interop v0.6.0 镜像），断言 GI/读/时钟/文件目录/稳定性；`--all` 全 5 栈，结果落 `docs/interop_consumer_results.json`（**不进 CI**：CI 无 Docker；能力差异项标 INFO 不硬失败） | WSL2 Docker Engine + 已发布 5 镜像（`ghcr.io/otfabric/iec104-interop-*:v0.6.0`）；本仓主站 Web 服务先起（8765）；WSL↔Windows `127.0.0.1:2404` 转发可用 | `python tests/e2e/qa_interop_consumer.py --all` |
| `qa_webui_e2e.py` | **Web UI 双端联调**：SBO true/false、显式 select、设点、错误 COT 注入 | 可 `--spawn` 自启服务，或手动启动 8765/8766 | `python tests/e2e/qa_webui_e2e.py [--spawn]` |
| `qa_common.py` | 共享工具（HTTP/WS 探针、报文解码、断言记录） | — | 被上述脚本 import，不单独运行 |
| `playwright.config.ts` + `specs/` | **前端交互 e2e（T15，Playwright，headless）**：主站连接/点表虚拟滚动/命令面板、双击不发命令红线、子站置数与应答配置、多站增删启停、日志面板、契约降级告警、报文查看器悬停翻译（真实后端扁平响应 + Popover 渲染）、**API 响应契约矩阵（真实后端 × 前端 schema）**、**单页工作台（合并模式两菜单原生切换、无 iframe）**、**UI 自动巡检（8 页 × 3 视口 × 中英/深色：文本裁切、横向溢出、控制台 error/warn、API 失败、漏出 i18n key、空白页签、下载链接探活）**、**配色对比度（WCAG 2.1，浅/深主题，<3:1 门禁）**、**非文本对比度（控件边框/图标/焦点环）**、**视觉回归基线（按平台、`VISUAL=1`）** | 无（webServer 自动拉起主站/子站/合并模式/视觉基线服务并回收） | 见下节 |

## 前端交互 e2e（Playwright，T15）

`specs/` 下的 `.spec.ts` 用例基于 `@playwright/test`（依赖在 `webui/frontend/package.json` 的
devDependencies 中），由 `playwright.config.ts` 托管后端进程：**自动拉起**主站(8765)、
子站(8766) 与合并模式(8767，单进程双角色)，跑完自动回收。

**本地一条命令复现**（在仓库根目录，bash）：

```bash
NODE_PATH="$PWD/webui/frontend/node_modules" \
  webui/frontend/node_modules/.bin/playwright test --config tests/e2e/playwright.config.ts
```

> 本机已有运行中的实例占用 8765~8768 时（例如正在使用打包的 exe），加
> `E2E_PORT_OFFSET=10` 把整套 webServer 与用例端口整体平移到 8775~8778，
> 不必关掉正在使用的应用；两端（config 与 specs/helpers）读同一个变量。

> `NODE_PATH` 指向前端依赖目录，使 `tests/e2e/specs/*.ts` 能解析 `@playwright/test`
> （仓库根没有 node_modules，这是无需在根目录引包的最小方案）。
> 浏览器默认用系统 Edge（`channel: 'msedge'`，无需额外下载）；CI 上设
> `E2E_CHANNEL=chromium` 并先执行 `npx playwright install --with-deps chromium`。
>
> ⚠️ **必须在仓库根目录运行**：`visual.spec.ts` 用相对 cwd 的路径定位
> `tests/e2e/specs/__screenshots__/<platform>/`；在 `webui/frontend` 下运行会让
> 视觉用例因「找不到基线」被静默 skip（其余用例照常通过，容易误判为全绿）。

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
> 若 8765/8766/8767 已被**别人的**服务（队友在跑测试/调试）占用，Playwright 会
> 直接复用那个服务，造成跨工程串台的假失败/假通过。因此并行开发时跑 e2e
> 务必 `CI=1`（强制新起 webServer）或先清端口：
>
> ```bash
> netstat -ano | grep -E ":(8765|8766|8767|2404) .*LISTENING"   # 先看占用
> CI=1 E2E_CHANNEL=msedge webui/frontend/node_modules/.bin/playwright test \
>   --config tests/e2e/playwright.config.ts
> ```
>
> 另外 Windows 上连环跑两轮 e2e 时，2404 的 TIME_WAIT 可能尚未消散，
> 第二轮 `/api/slave/start` 绑定会失败——两轮间隔 ≥60s（CI/Linux 无此问题）。

用例清单（见 `specs/*.spec.ts`）：

- 主站：UI 连接建立 → 点表虚拟滚动（**DOM 行数远小于总行数**，T12 验收）→ 选中行 →
  命令面板下发（断言请求体）→ 双击命令点值单元格 → 确认弹窗 → 下发遥控/设点
  （断言请求体；SBO 由后端自动选择-执行）→ **红线：双击遥信值单元格不产生任何
  `/api/master/*` POST**
- 子站：YX/YC/YM 手动置数（请求体断言）、STEP 置数（输入 200 夹紧到 63）、
  应答行为配置（`wrong_cot`/`drop_rate` 请求体断言）
- 多站：添加站 → 启动 → 聚合状态可见 → 停止 → 删除（独立端口 15002，避开 2404）
- 日志：级别过滤、暂停后恢复不丢缓冲、导出（附件头 + 非空）
- 契约：伪造 `schemaVersion=99` → 降级告警横幅、外壳不崩溃（WS 经 `routeWebSocket` 吞掉）
- API 契约：`api-contract.spec.ts` 用前端 `contracts.ts` 的同一份 schema 校验真实后端
  （主站/子站只读端点矩阵、幂等停止命令、主站连接+总召后的运行态），后端字段漂移在 CI 失败
- 报文查看器：悬停 HEX → 真实 `/api/frames/decode` → 逐段翻译 Popover（防「翻译失败」回归）
- 单页工作台：合并模式服务器（`--mode both`，8767）→ 左侧两个菜单在同一页面**原生**切换
  （子站 API/WS 在 `/slave/*`），验证只有一个浏览器页且**没有 iframe**
- UI 自动巡检：`ui-audit.spec.ts` 覆盖 8 个菜单页 × 3 个桌面视口（1680/1366/1280）、
  主站/子站页签、命令面板折叠区全部展开、中文 + 英文、深色主题；断言 Card 标题/按钮/
  页签/表单标签/提示文案不裁切（`scrollWidth > clientWidth`）、页面无横向滚动、关键控件
  不出视口（表格内横向滚动豁免）、无控制台 error/warn、无 API 4xx/5xx、无错误 Alert、
  无空白页签、界面不漏 i18n key；另探活所有导出/下载链接（2xx + `Content-Disposition`）。
  截图落在 `tests/e2e/audit-shots/` 供人工复核（已 gitignore，不会被 Playwright 清空）。
- 配色对比度：`ui-contrast.spec.ts` 覆盖 8 页 × 浅/深主题（3488 处文本），沿祖先链
  合成有效背景（含 alpha/opacity），按 WCAG 2.1 校验文字与 `::placeholder` 对比度；
  <3:1 默认失败，`CONTRAST_REPORT=1` 只输出报告；3:1~4.5:1 作为 AA 建议项列出。
- 非文本对比度：`ui-nontext-contrast.spec.ts` 检查输入框/下拉/默认按钮/勾选圈边框、
  Switch 轨道、纯图标按钮、键盘 Tab 焦点环与相邻背景 ≥3:1（WCAG 1.4.11 / 2.4.7）；
  禁用控件按 WCAG 豁免。
- 视觉回归：`visual.spec.ts` 用专用单角色服务 8768（无引擎/无帧/无历史）截
  浅/深主站工作台 + 状态总览整页基线；**当前平台有基线就会自动跑**（Windows 基线
  已入库，`windows-build` job 执行），没有基线的平台自动 skip。基线按平台存在
  `specs/__screenshots__/<platform>/`。
  > **P1-3 已知缺口（如实标注）**：当前仅 `win32/` 有基线，
  > Linux `frontend-e2e` job 的 3 个视觉用例会静默 skip。补 Linux 基线必须在
  > **Linux + chromium** 上用 `VISUAL_UPDATE=1 --update-snapshots` 真实渲染生成
  > 并人工 review，不能用 Windows PNG 复制改名（字体/抗锯齿差异会制造假回归）。
  > 该项待 Linux runner 窗口，属增强项、不阻塞发布。

  ```bash
  # 校验当前平台（有基线时）
  NODE_PATH="$PWD/webui/frontend/node_modules" \
    webui/frontend/node_modules/.bin/playwright test \
    --config tests/e2e/playwright.config.ts tests/e2e/specs/visual.spec.ts
  # 新平台/更新基线（人工 review diff 后提交）
  VISUAL_UPDATE=1 NODE_PATH="$PWD/webui/frontend/node_modules" \
    webui/frontend/node_modules/.bin/playwright test \
    --config tests/e2e/playwright.config.ts tests/e2e/specs/visual.spec.ts --update-snapshots
  ```

端口占用：8765 / 8766 / 8767 / 8768（主站/子站/合并模式/视觉基线）与 2404、
15002（多站用例，跑完即停删），**勿与 pytest 并行运行**。

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
