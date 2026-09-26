"""网络异常模拟引擎.

在 TCP 传输层和协议引擎之间插入代理层，注入各种网络异常:
- 延迟 (delay)
- 丢包 (loss)
- 重复 (duplicate)
- 损坏 (corrupt)
- 乱序 (reorder)
- 断线 (disconnect)

用法:
    from core.simulation import NetworkCondition, inject_conditions

    condition = NetworkCondition(loss_rate=0.1, delay_ms=50)
    inject_conditions(engine, condition)
"""

from .conditions import ConditionPreset, NetworkCondition
from .manager import SimulationManager
from .proxy import NetworkProxy

__all__ = [
    "NetworkCondition",
    "ConditionPreset",
    "NetworkProxy",
    "SimulationManager",
]
