---
feature: modbus-style-dual-app
status: delivered
updated: 2026-06-15
branch: feature/modbus-style-dual-app
commits: 5f2f559..5f2f559
---

# IEC104 主站 / 子站双应用（借鉴 Modbus Poll/Slave 双窗口使用模式）

> 命名说明：仅借鉴双独立窗口、可并开对测的使用模式。
> 产品对外名称为 **IEC104 主站** / **IEC104 子站**，不叫 Poll。

## Report

**What was built** — 将单一 `app.py --mode` 工具拆成可并开的双窗口应用：`gui/master_app`（主站客户端）与 `gui/slave_app`（子站服务端），共享 `core/` 引擎与 `gui/common/`（主题、连接/监听栏、状态条）。入口为 `apps/master_main.py`、`apps/slave_main.py`；`app.py` 默认打开新界面，`--legacy-ui` 保留旧一体化 GUI。主站支持定义表、遥控/设点、周期 GI、报文/趋势/录制；子站支持可编辑点表（双击改值并自发上送）、客户端列表、ResponseBehavior、模拟。PyInstaller 脚本产出 `iec104-master` / `iec104-slave`。

**Verification** — `pytest tests/ -q` → **224 passed**；offscreen 冒烟 Master/Slave 窗口标题与 Signal 挂接 OK。Review 后已修复：跨线程 UI 回调改为 Signal 编组；GUI 线程改值经 `run_coroutine` 发自发上送；启动前 ResponseBehavior 落盘并应用；去除 Poll 残留命名。

**Journey log**
1. 用户澄清：只学 Poll/Slave 双窗口模式，**不要**改名为 Poll → 重命名为 master_app/主站。
2. 不做内嵌子站（S2.3）：联调=同时开两窗口。
3. `simulate_*` 在 GUI 线程调用会因无事件循环导致 SPONT 失败，必须 `run_coroutine`。
4. 引擎回调直接碰 Qt 控件不安全，沿用 `base_view` 的 Signal 编组模式。
5. `TCPClient.start()` 非阻塞，连接失败不会抛到调用方，UI 需轮询 `is_running`。

## [S1] Problem

现有工具主站/子站靠 `--mode` 切换，无法并排双窗口对测；缺少「打开即连、点表即改、立刻上送」的日常可用路径。

## [S2] Design

| 产品 | 角色 | 入口 |
|------|------|------|
| IEC104 主站 | 主站客户端 | `apps/master_main.py` → iec104-master |
| IEC104 子站 | 子站服务端 | `apps/slave_main.py` → iec104-slave |

布局：`gui/common` + `gui/master_app` + `gui/slave_app` + `build/build_all.py`。

主站：连接栏/定义表/命令面板/报文|日志|趋势|录制；「连本地」填 127.0.0.1。
子站：监听栏/可编辑点表/客户端列表/ResponseBehavior/模拟。
联调：同时启动两窗口，不内嵌子站。
UI：Catppuccin 主题、布局 QSettings、Toast；引擎回调经 Qt Signal 回到 UI 线程。

## [S3] Out of Scope

内嵌子站；产品改名 Poll；101/103 串口；Web UI；完整 i18n；协议栈重写。

## Tasks

- [x] T1: apps + gui/common 骨架与主题 — acceptance: 双入口可启动窗口 (covers: S2, S2.5)
- [x] T2: 主站连接栏 + 引擎 + 状态栏 — acceptance: 可连接，状态灯/k-w 正确 (covers: S2.1; depends: T1)
- [x] T3: 主站定义表 + 命令面板 + 周期 GI — acceptance: 可编辑、可发令、总召进数 (covers: S2.1; depends: T2)
- [x] T4: 主站报文/日志/趋势/录制页签 — acceptance: 帧可见可过滤 (covers: S2.1, S2.4; depends: T2)
- [x] T5: 子站监听 + 可编辑点表 + 自发上送 — acceptance: 改值经 asyncio 线程发送 (covers: S2.2; depends: T1)
- [x] T6: 子站客户端列表 + 响应行为 + 模拟 — acceptance: 延迟/丢帧可观测；启动前配置可应用 (covers: S2.2, S2.4; depends: T5)
- [x] T7: 主题/布局记忆/Toast — acceptance: 切换主题、重启恢复布局 (covers: S2.5; depends: T3, T5)
- [x] T8: app.py 兼容转发 — acceptance: --mode slave 仍可启动新界面 (covers: S2; depends: T5)
- [x] T9: PyInstaller 双 exe 脚本 — acceptance: 脚本产出 iec104-master/salve (covers: S2.6; depends: T8)
- [x] T10: 回归 pytest + 双入口 offscreen 冒烟 — acceptance: 224 passed (covers: S2; depends: T9)
- [x] T11: README/PROJECT 说明 — acceptance: 文档含双应用启动方式 (covers: S2; depends: T10)
