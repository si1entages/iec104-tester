"""防误操作闭锁（WP4b）——独立于 SBO 的**下发前**前置条件.

职责边界（勿混淆）：
- **SBO（选择-执行）** 解决的是"命令是否被正确确认/时序对不对"，属协议层；
- **闭锁（interlock）** 解决的是"当前工况是否允许下发这条命令"，属业务安全层。

求值发生在**发送任何帧之前**：条件不满足则直接拒绝、链路上不留任何命令帧，
并把拒绝原因写入审计链（WP4a 同一条链）。强制解锁需 admin 角色，同样写审计。

点表 YAML 形态（YK/YC/STEP 点均可声明）::

    yk:
      - ioa: 2001
        name: 1号机合闸
        interlock:
          - ioa: 1001        # 引用一条遥信
            value: false     # 必须处于分位
            label: 刀闸位置   # 可选说明

多个条件之间是 **AND**：全部满足才允许下发。
取值失败（遥信未上送 / 点不存在 / 读取异常）按**不满足**处理——
闭锁的默认取向是安全，未知工况不允许操作。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class InterlockCondition:
    """单条闭锁条件：某遥信必须处于指定位置."""

    ioa: int
    value: bool
    label: str = ""

    def describe(self) -> str:
        want = "合" if self.value else "分"
        base = f"YX {self.ioa} 须为{want}位"
        return f"{base}（{self.label}）" if self.label else base


@dataclass(frozen=True)
class InterlockResult:
    """求值结果：``blocked`` 为 True 时调用方不得下发任何帧."""

    blocked: bool
    reason: str = ""
    conditions: tuple[InterlockCondition, ...] = ()
    observed: tuple[tuple[int, bool | None], ...] = ()

    def as_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "conditions": [
                {"ioa": c.ioa, "value": c.value, "label": c.label} for c in self.conditions
            ],
            "observed": [
                {"ioa": ioa, "value": value} for ioa, value in self.observed
            ],
        }


def parse_interlock(raw: object) -> tuple[InterlockCondition, ...]:
    """解析 YAML 里的 ``interlock`` 节；非法配置抛 ``ValueError``（不静默丢弃）.

    接受形态：``[{ioa, value, label?}]``。``ioa`` 必须是非负整数，
    ``value`` 必须是布尔（字符串 ``"on"/"off"/"true"/"false"`` 亦接受，
    便于手写 YAML）。
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("interlock 须为条件列表（- ioa: … value: …）")
    out: list[InterlockCondition] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"interlock[{i}] 须为对象")
        ioa = item.get("ioa")
        if not isinstance(ioa, int) or isinstance(ioa, bool) or ioa < 0:
            raise ValueError(f"interlock[{i}].ioa 须为非负整数，实际 {ioa!r}")
        value = _as_bool(item.get("value"), f"interlock[{i}].value")
        label = str(item.get("label", ""))
        out.append(InterlockCondition(ioa=ioa, value=value, label=label))
    return tuple(out)


def _as_bool(raw: object, where: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in ("on", "true", "1", "yes", "合", "合位"):
            return True
        if low in ("off", "false", "0", "no", "分", "分位"):
            return False
    if isinstance(raw, int) and not isinstance(raw, bool):
        return bool(raw)
    raise ValueError(f"{where} 须为布尔（on/off/true/false）")


def dump_interlock(conditions: Iterable[InterlockCondition]) -> list[dict]:
    """序列化回 YAML 结构（空则返回空列表，由调用方决定是否写入）."""
    return [
        {"ioa": c.ioa, "value": c.value, **({"label": c.label} if c.label else {})}
        for c in conditions
    ]


def evaluate(
    conditions: Iterable[InterlockCondition],
    read_yx: Callable[[int], bool | None],
) -> InterlockResult:
    """逐条求值：任一条不满足即 ``blocked=True``，reason 列出全部未满足项."""
    conds = tuple(conditions)
    if not conds:
        return InterlockResult(blocked=False, conditions=())
    observed: list[tuple[int, bool | None]] = []
    fails: list[str] = []
    for c in conds:
        try:
            actual = read_yx(c.ioa)
        except Exception:  # noqa: BLE001 — 读取失败按"未知"处理，安全优先
            actual = None
        if actual is not None and not isinstance(actual, bool):
            actual = bool(actual)
        observed.append((c.ioa, actual))
        if actual is None:
            fails.append(f"{c.describe()}——实测值未知（遥信未上送）")
        elif actual != c.value:
            fails.append(f"{c.describe()}——实测为{'合' if actual else '分'}位")
    blocked = bool(fails)
    return InterlockResult(
        blocked=blocked,
        reason="；".join(fails),
        conditions=conds,
        observed=tuple(observed),
    )
