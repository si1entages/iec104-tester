"""ASDU 地址字段长度配置（WP1 / 现场非标装置互联）。

IEC 60870-5-104 未强制规定公共地址(CA)、信息对象地址(IOA)、传送原因(COT)
的字节数，各厂商/规约转换器常见 1 字节 CA、2 字节 IOA 的变体。历史上本仓
把 2/3/2 硬编码在 :mod:`core.protocol.asdu` 的 encode/decode 中，遇到这类
装置会整帧信息体错位且无报错。

本模块提供单一真值源：

* :class:`AsduAddressConfig` —— 三个长度值 + 校验；
* :func:`get_default` / :func:`set_default` / :func:`use_default` ——
  进程级默认，由启动时从 ``AppConfig.asdu_address`` 注入；
* ``ContextVar`` 实现任务级隔离：多站、透明桥两侧可在同一进程内使用
  不同长度而互不串味；显式传参（离线解析工具按帧指定）优先级最高。

默认值 ``ca_length=2, ioa_length=3, cot_length=2`` 与历史硬编码完全一致，
因此**未做任何配置时编解码逐字节不变**。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

__all__ = [
    "AsduAddressConfig",
    "DEFAULT_ASDU_ADDRESS",
    "get_default",
    "set_default",
    "use_default",
]

_VALID_CA = (1, 2)
_VALID_IOA = (1, 2, 3)
_VALID_COT = (1, 2)


@dataclass(frozen=True)
class AsduAddressConfig:
    """ASDU 地址字段字节数。

    Attributes:
        ca_length: 公共地址字节数（1 或 2）。
        ioa_length: 信息对象地址字节数（1、2 或 3）。
        cot_length: 传送原因字节数（1 或 2）。为 1 时不写入源发地址字节，
            读取时源发地址恒为 0；为 2 时第二字节为源发地址（标准布局）。
    """

    ca_length: int = 2
    ioa_length: int = 3
    cot_length: int = 2

    def __post_init__(self) -> None:
        if self.ca_length not in _VALID_CA:
            raise ValueError(f"ca_length must be one of {_VALID_CA}, got {self.ca_length}")
        if self.ioa_length not in _VALID_IOA:
            raise ValueError(f"ioa_length must be one of {_VALID_IOA}, got {self.ioa_length}")
        if self.cot_length not in _VALID_COT:
            raise ValueError(f"cot_length must be one of {_VALID_COT}, got {self.cot_length}")

    @property
    def header_size(self) -> int:
        """ASDU 头部字节数：TypeID + VSQ + COT + CA。"""
        return 1 + 1 + self.cot_length + self.ca_length


DEFAULT_ASDU_ADDRESS = AsduAddressConfig()

# 进程级默认：``set_default`` 直接改这个变量，因此无论 asyncio 任务何时创建、
# context 如何复制，所有未显式覆盖的编解码都能立即看到同一份配置。
# 任务级临时覆盖则由 ``_current``（ContextVar）承担，二者叠加见 ``get_default``。
_process_default: AsduAddressConfig = DEFAULT_ASDU_ADDRESS
_current: ContextVar[AsduAddressConfig | None] = ContextVar(
    "asdu_address_config", default=None
)


def get_default() -> AsduAddressConfig:
    """返回当前任务（或进程默认）生效的地址配置。

    优先级：``use_default`` 的任务级覆盖 > ``set_default`` 的进程级默认。
    """
    return _current.get() or _process_default


def set_default(config: AsduAddressConfig | None) -> None:
    """设置**进程级**默认配置。

    应在应用启动、尚未创建引擎/任务前调用（``AppConfig.asdu_address`` 接线）。
    ``None`` 表示恢复标准默认值。进程级变量保证跨 asyncio 任务可见。
    """
    global _process_default
    _process_default = config or DEFAULT_ASDU_ADDRESS


@contextmanager
def use_default(config: AsduAddressConfig | None):
    """在 ``with`` 块内临时覆盖当前任务的地址配置，退出后自动还原。

    用于多站/透明桥等「同一进程内不同链路使用不同长度」的场景；引擎在
    建链时按所属链路包住收发协程即可。

    ``None`` 表示**不覆盖**（沿用 ``set_default`` 的进程级默认），而不是
    「恢复标准默认」——否则桥两侧未单独配置时会屏蔽掉进程级配置。
    """
    token = _current.set(config)
    try:
        yield get_default()
    finally:
        _current.reset(token)
