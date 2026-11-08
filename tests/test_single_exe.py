"""单文件发布入口（一个 exe 支持 master / slave / both）单测.

不真正启动服务：验证默认 both、CLI 拒绝 no-gui+both、run_web 把 both 交给
单进程双角色服务器（同一端口）。
"""

from __future__ import annotations

import sys

import app as app_module


def test_cli_no_mode_defaults_to_both(monkeypatch):
    """双击/无参数：默认单进程双角色（一个端口、一个页面）."""
    called: dict = {}

    def _fake_run_web(role, *args, **kwargs):
        called["role"] = role
        called["history_dbs"] = kwargs.get("history_dbs")

    monkeypatch.setattr(app_module, "run_web", _fake_run_web)
    monkeypatch.setattr(sys, "argv", ["iec104-tester", "--no-browser", "--no-history"])
    assert app_module.cli() == 0
    assert called["role"] == "both"
    assert called["history_dbs"] == {}


def test_cli_mode_both_explicit(monkeypatch):
    called: dict = {}

    def _fake_run_web(role, *args, **kwargs):
        called["role"] = role

    monkeypatch.setattr(app_module, "run_web", _fake_run_web)
    monkeypatch.setattr(
        sys, "argv", ["iec104-tester", "--mode", "both", "--no-browser", "--no-history"]
    )
    assert app_module.cli() == 0
    assert called["role"] == "both"


def test_cli_both_rejects_no_gui(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["iec104-tester", "--mode", "both", "--no-gui", "--no-history"]
    )
    assert app_module.cli() == 2
    assert "仅支持 Web 模式" in capsys.readouterr().out


def test_run_web_both_uses_one_server_port(monkeypatch):
    """both 不再起两个子进程：直接把 role=both + history_dbs 交给 run_server."""
    from webui import server as server_module

    called: dict = {}

    def _fake_run_server(role, host, port, **kwargs):
        called.update(role=role, host=host, port=port, **kwargs)

    monkeypatch.setattr(server_module, "run_server", _fake_run_server)
    app_module.run_web(
        "both", 18767, open_browser=False,
        history_dbs={"master": object(), "slave": object()},
    )
    assert called["role"] == "both"
    assert called["port"] == 18767
    assert set(called["history_dbs"]) == {"master", "slave"}
