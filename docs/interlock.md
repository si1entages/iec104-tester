# 防误操作闭锁（WP4b）

> 方案：[`optimization_plan_v111.md`](optimization_plan_v111.md) §WP4 WP4b ｜ 契约：[`webui/api_contract.md`](../webui/api_contract.md) §2.4e

## 1. 它解决什么问题

SBO（选择-执行）保证**命令被正确确认、时序正确**，属协议层；
闭锁保证**当前工况允许下发这条命令**，属业务安全层。两者互补，不可互相替代。

典型场景：一条刀闸在合位时不允许对开关发合闸命令。传统做法靠操作票人工核对；
闭锁把这条"防误"规则写进点表，由程序在下发前强制求值——**不满足就一个帧都不发**。

## 2. 配置方式

在点表 YAML 的命令点（`yk` / `yc` / `step` 三类）上声明 `interlock`：

```yaml
yk:
  - ioa: 2001
    name: 1号机合闸
    interlock:
      - ioa: 1001        # 引用一条遥信
        value: false     # 必须处于分位
        label: 刀闸位置   # 可选，出现在拒绝原因与界面提示里
  - ioa: 2002
    name: 1号机分闸     # 未声明 interlock = 不闭锁（默认，与历史行为一致）
```

规则：

| 项 | 说明 |
|---|---|
| 条件关系 | 多个条件是 **AND**：全部满足才允许下发 |
| `value` | `false`=分位，`true`=合位；也接受 `on/off/true/false/合/分` 等写法 |
| 取值失败 | 遥信未上送、点不存在、读取异常 → 按**不满足**处理（未知工况不操作） |
| 非法配置 | `ioa` 非整数、`value` 非布尔 → **加载点表时即报错**，不静默忽略 |
| 适用范围 | 遥控（`master/yk`）、设点（`master/setpoint`）、升降（`master/step`）、比特串（`master/bitstring`） |
| 例外 | **DEACT 撤销帧（`deactivate=true`）不受闭锁限制**——它是安全清理动作，必须始终可发 |

## 3. 拒绝时的行为

闭锁不满足时：

1. **链路上不产生任何命令帧**（验收判据，`tests/test_interlock.py` 用替身断言发送列表为空）；
2. 接口返回 HTTP 200 + 业务错误（不是 5xx）：
   ```json
   {"ok": false,
    "error": "联锁不满足，命令未下发：YX 1001 须为分位（刀闸位置）——实测为合位",
    "interlock": {"blocked": true, "reason": "...",
                  "conditions": [{"ioa": 1001, "value": false, "label": "刀闸位置"}],
                  "observed": [{"ioa": 1001, "value": true}]}}
   ```
   `observed.value = null` 表示该遥信当时未上送；
3. 写入**审计链**（与 WP4a 同一条链）：`action = "yk/interlock-blocked"`、`result = "fail"`、
   `target = <下发 IOA>`、`reason = <拒绝原因>`。用 `/api/audit/verify` 可证明该记录未被事后删改。

界面表现：点表类型列显示「联锁」标记；双击点值打开的命令弹窗列出闭锁条件，命令被拒时把
`error` 原文展示在结果区。

## 4. 强制解锁

现场确有需要越过闭锁的场景（如刀闸遥信本身故障）。此时用 `force: true`：

```bash
curl -X POST http://127.0.0.1:8765/api/master/yk \
     -H 'Authorization: Bearer <admin-token>' \
     -d '{"ioa": 2001, "state": 1, "force": true}'
```

- **需 admin 角色**（`--auth-config` 的多用户模式；未启用认证时为全权，与兼容模式一致）；
  非 admin 请求返回 `{ok: false, error: "强制解锁需 admin 角色（当前 operator）"}`，且**不发帧**；
- 放行后额外写入 `action = "yk/force-unlock"`、`result = "ok"`、`reason = "强制解锁：<原拒绝原因>"`
  的审计记录——**谁、何时、越过哪条闭锁**在链上留痕，可举证；
- 界面：命令弹窗中勾选「强制解锁（需 admin 角色）」，弹窗转为危险色二次确认。

## 5. 验证命令

```bash
# 点表往返（interlock 读写、非法配置拒绝、旧点表兼容）
python -m pytest tests/test_interlock.py -q

# 端到端：闭锁拒绝时不发帧 + force 语义 + 契约响应形状
python -m pytest tests/test_interlock.py::TestApi -q
```

## 6. 已知边界（有意保留，勿当缺陷"修复"）

- **闭锁不改变主/子站 SBO 边界语义**：`master_commands.sbo_required` 中记载的
  "未命中 YK 点表 + 遥控"主站直发、子站要求 SBO 的差异是既有设计，闭锁不介入该判定。
- **闭锁只在主站侧求值**：它防的是"测试器发错命令"。若需装置侧防误，属装置五防职责范围。
- **闭锁只引用遥信位置**：不支持"某遥测在区间内""延时后允许"等复合表达式。这类规则
  需要表达力更强的规则引擎，当前保持可判定的最小形态（避免引入无法验证的模糊语义）。
- **Excel/CSV 点表导入不带 interlock 列**：Excel 导入保留设计基准用途，闭锁通过 YAML 维护。
- **演示点表不预置闭锁**：避免用户点「遥控」就被拒造成困惑；需要时由用户显式配置。
