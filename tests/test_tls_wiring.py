"""D3 回归测试：CLI ``--tls*`` 在默认 Web 模式下必须真实生效.

覆盖（QA 互调报告 2026-10-15 §C7/D3）:
- CLI 入口：TLS 配置无效（坏 CA）→ ``app.cli()`` 非零退出（返回 2），
  且不进入 Web 服务（run_web 不被调用）
- CLI 入口：``--tls*`` 解析结果经 run_web(engine_config=...) 完整传入 Web 层
- Web 会话：HTTP body 未带 ``tls`` 时回落 ``config.tls``（CLI 声明的 TLS 生效）
- Web 会话：HTTP body 显式 ``tls`` 仍优先（既有路径行为不变，QA 实测为好的）
- Web 会话：config.tls 无效 → 启动失败 ``ok=False``，绝不静默降级明文
- Web 会话：无 TLS 配置 → 明文（行为与改动前一致）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import app as app_module
from core.config import AppConfig
from core.transport.tls_context import TlsConfigError
from webui.bridge import EngineBridge

CERTS = Path(__file__).parent / "certs"
CA1 = str(CERTS / "ca1.pem")
SERVER_CRT = str(CERTS / "server.pem")
SERVER_KEY = str(CERTS / "server.key")


# ── CLI 入口 ─────────────────────────────────────────────────────


def _run_cli_with_argv(argv: list[str], monkeypatch, capture: dict) -> int:
    """以指定 argv 运行 ``app.cli()``；run_web 被拦截并记录到 capture."""
    monkeypatch.setattr(sys, "argv", ["app.py", *argv])

    def _fake_run_web(role, *args, **kwargs):
        capture["role"] = role
        capture["kwargs"] = kwargs
        return None

    monkeypatch.setattr(app_module, "run_web", _fake_run_web)
    return app_module.cli()


def test_cli_rejects_invalid_tls_in_web_mode(monkeypatch):
    """坏 CA + 默认 Web 模式 → 非零退出，绝不带着坏配置启动服务."""
    capture: dict = {}
    rc = _run_cli_with_argv(
        ["--mode", "master", "--no-browser", "--no-history",
         "--tls", "--tls-ca", "definitely_missing_ca.pem"],
        monkeypatch, capture,
    )
    assert rc == 2
    # 绝不能进入 Web 服务启动流程
    assert "kwargs" not in capture


def test_cli_passes_tls_config_to_web(monkeypatch):
    """--tls* 解析结果必须经 engine_config 传入 Web 层（D3 断点修复）."""
    capture: dict = {}
    rc = _run_cli_with_argv(
        ["--mode", "master", "--no-browser", "--no-history",
         "--tls", "--tls-ca", CA1],
        monkeypatch, capture,
    )
    assert rc == 0
    cfg = capture["kwargs"]["engine_config"]
    assert cfg is not None
    assert cfg.tls.enabled is True
    assert cfg.tls.cafile == CA1


def test_cli_no_tls_web_mode_unchanged(monkeypatch):
    """未启用 TLS 的 Web 模式不受影响（engine_config 照传，tls.enabled=False）."""
    capture: dict = {}
    rc = _run_cli_with_argv(
        ["--mode", "slave", "--no-browser", "--no-history"],
        monkeypatch, capture,
    )
    assert rc == 0
    cfg = capture["kwargs"]["engine_config"]
    assert cfg.tls.enabled is False


# ── Web 会话层：config.tls 兜底生效 ───────────────────────────────


def _master_config_with_tls() -> AppConfig:
    cfg = AppConfig()
    cfg.tls.enabled = True
    cfg.tls.cafile = CA1
    return cfg


def _slave_config_with_tls() -> AppConfig:
    cfg = AppConfig()
    cfg.tls.enabled = True
    cfg.tls.certfile = SERVER_CRT
    cfg.tls.keyfile = SERVER_KEY
    return cfg


@pytest.mark.asyncio
async def test_session_master_uses_config_tls_when_body_omits_tls():
    """body 未带 tls → 回落 config.tls，主站引擎真实启用 TLS（客户端侧）."""
    bridge = EngineBridge(role="master", app_config=_master_config_with_tls())
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_master("127.0.0.1", 12700, 1,
                                      reconnect=False, gi_interval=0)
        assert r["ok"] is True
        assert bridge.engine is not None
        assert bridge.engine._client.tls_enabled is True
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_session_slave_uses_config_tls_when_body_omits_tls():
    """body 未带 tls → 回落 config.tls，子站引擎真实启用 TLS（服务端侧）."""
    bridge = EngineBridge(role="slave", app_config=_slave_config_with_tls())
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_slave("127.0.0.1", 12701, 1)
        assert r["ok"] is True
        assert bridge.engine is not None
        assert bridge.engine._server.tls_enabled is True
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_body_tls_still_wins_over_config():
    """body 显式 tls 仍优先：config 未启用 TLS、body 启用 → TLS 生效（既有路径）."""
    bridge = EngineBridge(role="slave", app_config=AppConfig())
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_slave("127.0.0.1", 12702, 1, tls={
            "enabled": True, "certfile": SERVER_CRT, "keyfile": SERVER_KEY,
        })
        assert r["ok"] is True
        assert bridge.engine is not None
        assert bridge.engine._server.tls_enabled is True
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_session_rejects_invalid_config_tls_without_downgrade():
    """config.tls 无效（坏 CA）→ ok=False + 可读错误，引擎不创建、不降级明文."""
    cfg = AppConfig()
    cfg.tls.enabled = True
    cfg.tls.cafile = "definitely_missing_ca.pem"
    bridge = EngineBridge(role="master", app_config=cfg)
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_master("127.0.0.1", 12703, 1,
                                      reconnect=False, gi_interval=0)
        assert r["ok"] is False
        assert "TLS 配置无效" in r["error"]
        assert bridge.engine is None
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_session_without_tls_config_stays_plaintext():
    """无 TLS 配置 → 明文（与改动前行为一致）."""
    bridge = EngineBridge(role="master", app_config=AppConfig())
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_master("127.0.0.1", 12704, 1,
                                      reconnect=False, gi_interval=0)
        assert r["ok"] is True
        assert bridge.engine is not None
        assert bridge.engine._client.tls_enabled is False
    finally:
        await bridge.shutdown()


def test_tls_config_error_type_is_importable_for_cli_path():
    """CLI Web 路径依赖 ``build_context_from_config`` 的 TlsConfigError 失败语义."""
    from core.transport.connection import build_context_from_config

    cfg = AppConfig()
    cfg.tls.enabled = True
    cfg.tls.cafile = "definitely_missing_ca.pem"
    with pytest.raises(TlsConfigError):
        build_context_from_config(cfg.tls, "master")
