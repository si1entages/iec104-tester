# 工程配置方案管理（WP5）

> 方案：[`optimization_plan_v111.md`](optimization_plan_v111.md) §WP5 ｜ 契约：[`webui/api_contract.md`](../webui/api_contract.md) §2.4f

## 1. 它解决什么问题

现场调试要记的东西很多：装置 IP、端口、公共地址、链路超时与 k/w、非标地址长度、
点表文件、告警阈值。以前这些散落在命令行参数、YAML 配置和页面输入框里——
刷新页面连接参数就回默认值，换一个间隔要重新手抄一遍。

「方案」把这些**打包成一份可命名的文本文件**，换现场一键切换。

## 2. 使用方式

### 界面（推荐）

状态总览页 →「工程配置方案」卡片：

| 操作 | 说明 |
|---|---|
| 当前方案下拉 | 列出 `configs/profiles/*.yaml`；带 ● 的是当前**活动方案** |
| 应用 | 把方案写回运行态（连接/链路参数/ASDU 长度/阈值/点表） |
| 保存为方案 | 用下方「方案名」把**当前生效参数**存成新方案 |
| 覆盖保存当前参数 | 用当前参数覆盖选中的方案 |
| 导出 YAML / 从文本导入 | 方案在机器/现场之间转移（纯文本，可走邮件/优盘/git） |
| 删除 | 删除方案文件（若它是活动方案，活动指针一并清空） |

**刷新后自动恢复**：应用过的方案名记在 `configs/profiles/_active.yaml`（该文件被 git 忽略），
页面挂载时调 `POST /api/profiles/restore` 还原——所以浏览器刷新、换标签页、重开浏览器
都不会回到默认参数。

### 命令行（无浏览器 / 脚本化）

```bash
# 用方案启动（方案叠加在 --config 之上；显式指定，取不到即退出报错）
python app.py --profile 示例-标准2_3_2

# 方案文件本身就是合法配置，等价写法：
python app.py --config configs/profiles/示例-标准2_3_2.yaml
```

`--profile` 只叠加**工程参数**；`--config` 里其余内容（TLS、历史库、显示偏好）保持不变。

## 3. 方案内容

```yaml
name: 示例-标准2_3_2          # 由保存方写入
mode: master                  # 记录用途；--profile 不改启动角色
note: 标准 IEC 104 口径
connection:                   # ← 会被应用
  host: 127.0.0.1
  port: 2404
  common_addr: 1
timers: {t0: 30.0, t1: 15.0, t2: 10.0, t3: 20.0}   # ← 会被应用
flow_control: {k: 12, w: 8}                          # ← 会被应用
asdu_address: {ca_length: 2, ioa_length: 3, cot_length: 2}   # ← 会被应用（WP1）
point_table:
  file: configs/demo_points.yaml                     # ← 会被应用（导入并重建实时库）
alarms:                                              # ← 会被应用（告警阈值）
  stale_seconds: 60.0
  comm_seconds: 10.0
  jump_delta: null
  debounce: 2
  sound: false
display: {theme: dark}        # 仅 --config 生效；方案与 --profile 都不覆盖
tls: {enabled: true, certfile: /path/x.pem}          # 同上：安全配置不经方案流转
```

**有意不覆盖的项**：TLS/证书路径、历史库保留期、显示偏好（主题/语言/刷新率）。
理由：这些是**运行环境与安全**属性，不同现场共用一份方案时若被静默改写，
后果比"少还原一个参数"严重得多。要连它们一起带，请直接维护一份 `--config` 文件。

## 4. 权限与审计

- 方案是**管理动作**：`admin` 可写；`operator` / `viewer` 只读（§2.4d 权限矩阵）；
- 保存 / 应用 / 删除 / 导入写入**审计哈希链**（`profiles/save`、`profiles/apply`、
  `profiles/delete`），可用「操作审计」页的「校验链」证明未被事后删改；
- `profiles/apply` 记录的 `reason` 列出本次实际还原的项（如 `connection,timers.t1,asdu_address`），
  便于事后回答"这次切换到底改了什么"。

## 5. 设计取舍（有意为之，勿当缺陷）

1. **服务端启动不自动应用方案**：端口与角色只由 CLI 和 `--config` 决定。否则磁盘上的
   历史状态会悄悄改变启动行为——CI、e2e、以及"我只想用 --config 起一个干净实例"
   都会变得不可预测。「刷新后还原」由前端挂载时显式 `restore` 完成，语义清晰。
2. **应用是幂等的"写回"**：`apply` 会覆盖当前运行参数（这正是"还原"的含义）。
   若你手动改了参数但没保存，再点「应用」会回到方案里的值。
3. **点表引用缺失不阻断**：方案引用的点表文件不存在时，记日志并跳过该项，
   连接/阈值等照常还原，响应 `applied` 里不含 `point_table`——避免一个搬走的
   文件让整套方案完全不可用。
4. **坏文件不影响列表**：某个方案 YAML 写坏了，列表仍会列出它（摘要为空），
   用户可以在界面上删除或修好它，而不是整个列表报错。
5. **改名 = 另存 + 删除**：没有"重命名"接口（`save` 新名 + `delete` 旧名即可），
   少一个隐藏状态。
6. **名称限制**：≤64 字符，禁止 `/ \ : * ? " < > |` 与 `..`、禁止以 `.`/`_` 开头
   （`.`/`_` 开头留给隐藏文件与活动指针）。

## 6. 验证命令

```bash
# 存储 + 服务 + CLI 叠加 + API + 权限 + 审计
python -m pytest tests/test_profiles.py -q

# 端到端（含 3 套方案切换后全部参数还原）
python -m pytest tests/test_profiles.py::TestService::test_three_profiles_switch_restores_all -q
```
