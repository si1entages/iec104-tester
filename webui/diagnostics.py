"""一键诊断包（现场排障用）.

把排障需要的上下文打成一个 zip，避免用户在多轮沟通中反复截图/导文件：

- ``manifest.json``：版本、角色、平台、生成时间、各项条数、脱敏说明
- ``status.json``：当前 ``/api/status`` 快照
- ``config.json``：生效配置（TLS 私钥路径等敏感项脱敏）
- ``logs.json``：最近日志（结构化）
- ``frames.json`` / ``events.json``：最近收发帧与引擎事件（环形缓冲）
- ``points.json``：点表 + 实时值快照
- ``history.json``：历史库统计（未启用时 ``enabled: false``）
- ``README.txt``：包内文件说明与隐私提示
"""

from __future__ import annotations

import io
import json
import os
import platform
import sys
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from webui.events import SCHEMA_VERSION

DEFAULT_LOG_LIMIT = 2000
DEFAULT_FRAME_LIMIT = 500
DEFAULT_EVENT_LIMIT = 500


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("iec104-tester")
    except Exception:
        return "unknown"


def _json_bytes(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sanitize_config(config: Any) -> dict[str, Any]:
    """配置转 dict，并脱敏私钥路径（其余为运行参数，排障需要保留）."""
    if config is None:
        return {}
    data = asdict(config)
    tls = data.get("tls")
    if isinstance(tls, dict) and tls.get("keyfile"):
        tls["keyfile"] = "<redacted>"
    return data


def _readme(role: str) -> str:
    return f"""IEC104 Tester 诊断包（角色：{role}）

文件说明
--------
manifest.json   版本/平台/生成时间/条数/脱敏说明
status.json     生成瞬间的服务状态（与 /api/status 一致）
config.json     生效配置；config.tls.keyfile 已脱敏为 <redacted>
logs.json       最近日志（结构化，可能包含文件路径与装置地址）
frames.json     最近收发原始帧（HEX）
events.json     最近引擎事件
points.json     点表定义 + 实时值快照
history.json    历史库统计（未启用时为 enabled=false）

隐私提示
--------
本包用于排障，可能包含现场 IOA/公共地址/业务值/文件路径。发送给他人前请
确认接收方与用途；不要上传到公开仓库或公共工单附件。
"""


def build_diagnostics_zip(
    bridge: Any,
    *,
    log_limit: int = DEFAULT_LOG_LIMIT,
    frame_limit: int = DEFAULT_FRAME_LIMIT,
    event_limit: int = DEFAULT_EVENT_LIMIT,
) -> bytes:
    """构造诊断 zip 的字节内容.

    Args:
        bridge: ``EngineBridge``（提供 role/config/logs/recent/status/snapshot_points）。
        log_limit/frame_limit/event_limit: 各环形缓冲导出条数上限。
    """
    logs = bridge.query_logs(limit=log_limit)
    frames = bridge.recent("frame", frame_limit)
    events = bridge.recent("event", event_limit)
    points = bridge.snapshot_points()

    history = getattr(bridge, "history_db", None)
    history_info: dict[str, Any] = {"enabled": history is not None}
    if history is not None:
        try:
            history_info.update(history.get_stats())
        except Exception as exc:  # 历史库异常不能拖垮诊断包
            history_info["error"] = f"{type(exc).__name__}: {exc}"

    generated_at = datetime.now(UTC).isoformat()
    manifest = {
        "kind": "iec104-diagnostics",
        "schemaVersion": SCHEMA_VERSION,
        "appVersion": _app_version(),
        "generatedAt": generated_at,
        "role": bridge.role,
        "pid": os.getpid(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
        "counts": {
            "logs": len(logs),
            "frames": len(frames),
            "events": len(events),
            "points": len(points),
        },
        "limits": {
            "logs": log_limit,
            "frames": frame_limit,
            "events": event_limit,
        },
        "redactions": ["config.tls.keyfile"],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", _readme(bridge.role))
        zf.writestr("manifest.json", _json_bytes(manifest))
        zf.writestr("status.json", _json_bytes(bridge.status()))
        zf.writestr("config.json", _json_bytes(_sanitize_config(
            getattr(bridge, "config", None)
        )))
        zf.writestr("logs.json", _json_bytes(logs))
        zf.writestr("frames.json", _json_bytes(frames))
        zf.writestr("events.json", _json_bytes(events))
        zf.writestr("points.json", _json_bytes(points))
        zf.writestr("history.json", _json_bytes(history_info))
    return buf.getvalue()
