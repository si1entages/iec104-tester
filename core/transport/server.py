"""TCP Server — 兼容性 re-export shim.

DEPRECATED: 仅为向后兼容保留，新代码请从 :mod:`core.transport.connection`
导入。兼容期至 2026-12-31；届时（下一个主版本）本模块将被删除。

权威实现见 ``core.transport.connection.TCPServer``。
"""

from .connection import ConnectionStats, TCPConnection, TCPServer

__all__ = ["TCPServer", "TCPConnection", "ConnectionStats"]
