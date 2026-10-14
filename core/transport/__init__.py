"""传输层包 (core.transport).

**唯一权威入口是** :mod:`core.transport.connection`
（``TCPClient`` / ``TCPServer`` / ``TCPConnection`` / ``ConnectionStats``）。

``client`` 与 ``server`` 两个子模块仅为历史导入路径保留的兼容 shim，已标记
``DEPRECATED``（兼容期至 2026-12-31），新代码请勿依赖，应直接从
``core.transport.connection`` 导入。

设计说明（职责划分、``close()`` 幂等与超时契约、shim 存废）见
``docs/transport_design.md``。
"""
