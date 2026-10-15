"""TLS / IEC 62351 传输层加密 — SSLContext 构造与引擎注入（T20，自 connection.py 抽出）.

覆盖边界（**请勿宣传为"支持 IEC 62351"**）:
  已实现 —— TLS 1.2+ 传输层加密、服务端/客户端证书与私钥、受信 CA、
            客户端可选校验、双向认证（mTLS）。
  未实现 —— IEC 62351 的应用层认证（62351-4/-6）、会话密钥协商、
            安全关联与访问控制、证书吊销（CRL/OCSP）、重放防护等。
详见 docs/tls.md §覆盖边界。
"""

from __future__ import annotations

import logging
import ssl
from pathlib import Path

logger = logging.getLogger("iec104.transport")


class TlsConfigError(ValueError):
    """TLS 配置错误（文件缺失、参数矛盾等）."""


def _require_file(path: str, what: str) -> str:
    """校验文件存在，返回其字符串路径."""
    if not path:
        raise TlsConfigError(f"{what} 未配置")
    if not Path(path).is_file():
        raise TlsConfigError(f"{what} 不存在: {path!r}")
    return str(path)


def build_server_context(
    *, certfile: str, keyfile: str = "", cafile: str = "",
    verify_client: bool = False,
) -> ssl.SSLContext:
    """构造服务端（子站）``SSLContext``.

    Args:
        certfile: 服务端证书（PEM）。
        keyfile: 私钥（PEM）；为空时假定私钥与证书同文件。
        cafile: 受信 CA（PEM）；``verify_client=True`` 时必填。
        verify_client: 是否要求并校验客户端证书（双向认证 / mTLS）。

    Returns:
        配置好的 ``SSLContext``（最低 TLS 1.2）。

    Raises:
        TlsConfigError: 证书/密钥/CA 缺失或路径不存在。
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(
        certfile=_require_file(certfile, "certfile"),
        keyfile=keyfile or None,
    )
    if verify_client:
        ctx.load_verify_locations(cafile=_require_file(cafile, "cafile"))
        ctx.verify_mode = ssl.CERT_REQUIRED
    else:
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def build_client_context(
    *, cafile: str = "", certfile: str = "", keyfile: str = "",
    verify: bool = True,
) -> ssl.SSLContext:
    """构造客户端（主站）``SSLContext``.

    Args:
        cafile: 受信 CA；``verify=True`` 且为空时退回系统信任库。
        certfile: 客户端证书（双向认证时提供）。
        keyfile: 客户端私钥。
        verify: 是否校验服务端证书；``False`` 时同时关闭主机名校验
            （**仅供自签证书联调，生产禁用**）。

    Returns:
        配置好的 ``SSLContext``（最低 TLS 1.2）。

    Raises:
        TlsConfigError: 提供的证书/密钥/CA 路径不存在。
    """
    if verify:
        ctx = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH,
            cafile=_require_file(cafile, "cafile") if cafile else None,
        )
    else:
        # 注意顺序：必须先关 check_hostname 再置 CERT_NONE，否则 ValueError
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    if certfile:
        ctx.load_cert_chain(
            certfile=_require_file(certfile, "certfile"),
            keyfile=keyfile or None,
        )
    return ctx


def build_context_from_config(tls_cfg, role: str) -> ssl.SSLContext:
    """按 ``core.config.TlsConfig`` 与角色构造 ``SSLContext``."""
    if role == "slave":
        return build_server_context(
            certfile=tls_cfg.certfile,
            keyfile=tls_cfg.keyfile,
            cafile=tls_cfg.cafile,
            verify_client=tls_cfg.verify_client,
        )
    return build_client_context(
        cafile=tls_cfg.cafile,
        certfile=tls_cfg.certfile,
        keyfile=tls_cfg.keyfile,
        verify=tls_cfg.verify,
    )


def configure_engine_tls(engine, role: str, tls_cfg) -> bool:
    """把 TLS 注入引擎（兼容入口）；返回是否已启用.

    推荐做法：在构造 ``MasterEngine`` / ``SlaveEngine`` 时直接传
    ``ssl_context``（主站另可传 ``server_hostname``）参数。本函数保留给
    已持有引擎实例的旧调用方，内部经引擎公开方法 ``engine.set_ssl_context``
    走与构造参数完全相同的传输层注入路径。**必须在引擎 ``start()`` 之前调用。**

    Args:
        engine: ``MasterEngine`` 或 ``SlaveEngine`` 实例。
        role: "master" / "slave"。
        tls_cfg: ``core.config.TlsConfig``。

    Returns:
        True 表示已注入；``tls_cfg.enabled`` 为 False 时返回 False（不注入）。

    Raises:
        TlsConfigError: 上下文构造失败，或引擎未暴露 ``set_ssl_context`` 公开方法。
    """
    if not getattr(tls_cfg, "enabled", False):
        return False

    ctx = build_context_from_config(tls_cfg, role)
    setter = getattr(engine, "set_ssl_context", None)
    if not callable(setter):
        raise TlsConfigError(
            f"{type(engine).__name__} 未暴露 set_ssl_context 公开方法；"
            "请在构造 MasterEngine / SlaveEngine 时传入 ssl_context 参数"
        )
    if role == "slave":
        setter(ctx)
        logger.info("TLS enabled on slave (server side)")
    else:
        setter(ctx, getattr(tls_cfg, "server_hostname", "") or None)
        logger.info("TLS enabled on master (client side)")
    return True
