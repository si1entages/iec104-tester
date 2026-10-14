"""端到端 QA 脚本共享工具 — HTTP/WS 探针、报文解码与断言记录.

从 `qa_joint_debug.py` 抽取的可复用部分，供 `tests/e2e/` 下的端到端脚本共享，
使这些脚本**自包含**、可在干净克隆中独立运行（不依赖被 gitignore 的 `qa_verify/`）。

注意：本模块只做 HTTP/WS 与报文解码的薄封装，不含任何业务逻辑。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

# tests/e2e/qa_common.py -> 项目根（上溯 3 级）
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 屏蔽代理，否则 Windows 下 urllib 走系统代理导致连接被拒 ──
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"):
    os.environ.pop(_k, None)
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

MASTER = "http://127.0.0.1:8765"
SLAVE = "http://127.0.0.1:8766"
IEC_PORT = 24040

PASS, FAIL, OBS = "PASS", "FAIL", "OBS"
_results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str, obs: bool = False) -> None:
    """记录一项结论；obs=True 表示「观察项」（不参与通过/失败统计）."""
    status = OBS if obs else (PASS if ok else FAIL)
    _results.append((name, status, detail))
    print(f"[{status}] {name}\n      {detail}", flush=True)


def post(base: str, path: str, body: dict | None = None, timeout: float = 15.0) -> dict:
    """向某端 POST JSON 并返回解析后的响应体."""
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get(base: str, path: str) -> dict:
    """向某端 GET 并返回解析后的响应体."""
    with _opener.open(base + path, timeout=15) as r:
        return json.loads(r.read().decode())


def post_raw(base: str, path: str, text: str) -> dict:
    """以 text/yaml 原始体 POST（用于注入点表 YAML）."""
    req = urllib.request.Request(base + path, data=text.encode(),
                                 headers={"Content-Type": "text/yaml"}, method="POST")
    with _opener.open(req, timeout=15) as r:
        return json.loads(r.read().decode())


def wait_http(base: str, timeout: float = 15.0) -> bool:
    """轮询直到某端 /api/status 可访问，或超时."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            get(base, "/api/status")
            return True
        except Exception:
            time.sleep(0.2)
    return False


# ── 报文解码 ──────────────────────────────────────────────────────

def decode_frame(hex_str: str) -> dict:
    """把 /api/recent 的帧 HEX 解码为 {type, cot, pn, type_id, ioas, select}."""
    from core.protocol.asdu import ASDU

    raw = bytes.fromhex(hex_str)
    out: dict = {"type": None, "cot": None, "pn": None, "type_id": None,
                 "ioas": [], "select": None}
    if len(raw) < 6:
        return out
    cf0 = raw[2]
    if (cf0 & 0x01) == 0:
        out["type"] = "I"
    elif (cf0 & 0x03) == 0x01:
        out["type"] = "S"
    else:
        out["type"] = "U"
    if out["type"] != "I" or len(raw) <= 6:
        return out
    try:
        asdu = ASDU.decode(raw[6:])
        out["cot"] = int(asdu.cot)
        out["pn"] = bool(asdu.pn)
        out["type_id"] = int(asdu.type_id)
        out["ioas"] = [o.ioa for o in asdu.objects]
        if asdu.objects:
            out["select"] = bool(getattr(asdu.objects[0].data, "select", False))
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def iframes(base: str, direction: str = "tx") -> list[dict]:
    """取某端最近报文中的 I 帧（已解码）."""
    r = get(base, "/api/recent")
    out = []
    for fr in r.get("frames", []):
        d = fr.get("data", fr)
        if d.get("direction") != direction:
            continue
        dec = decode_frame(d.get("hex", ""))
        if dec["type"] == "I":
            out.append(dec)
    return out


def tail(base: str, direction: str, n: int) -> list[dict]:
    """取某端 I 帧序列第 n 条之后的部分."""
    return iframes(base, direction)[n:]


def frames_since(base: str, direction: str, since: float) -> list[dict]:
    """取某端在 since 时刻之后收发的 I 帧（按报文时间戳过滤）.

    **不要用"先记长度再切片"**：``/api/recent`` 只返回最近 200 条，缓冲区满后
    长度不再增长，切片会漏帧。
    """
    r = get(base, "/api/recent")
    out = []
    for fr in r.get("frames", []):
        d = fr.get("data", fr)
        if d.get("direction") != direction:
            continue
        if float(fr.get("ts", 0) or 0) < since:
            continue
        dec = decode_frame(d.get("hex", ""))
        if dec["type"] == "I":
            out.append(dec)
    return out


class WsCollector:
    """后台 WS 订阅某端的**全量**报文（单调递增，不会被窗口裁剪）.

    `/api/recent` 只给最近 200 条，用"记长度再切片"在缓冲区满后会漏帧；
    WS 是逐条推送，顺序完整。
    """

    def __init__(self, base: str) -> None:
        self.base = base
        self._frames: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:  # pragma: no cover - 线程入口
        import aiohttp

        url = self.base.replace("http://", "ws://") + "/ws"

        async def loop() -> None:
            while True:
                try:
                    async with (
                        aiohttp.ClientSession() as sess,
                        sess.ws_connect(url) as ws,
                    ):
                        self._ready.set()
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            m = json.loads(msg.data)
                            if m.get("kind") != "frame":
                                continue
                            d = m.get("data", {})
                            with self._lock:
                                self._frames.append((d.get("direction", ""), d.get("hex", "")))
                except Exception:
                    self._ready.set()          # 连不上也别让调用方卡死
                    await asyncio.sleep(1.0)

        asyncio.run(loop())

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def count(self, direction: str) -> int:
        """该方向已采集的 **I 帧** 数（与 ``frames()`` 长度严格一致）."""
        return len(self.frames(direction))

    def frames(self, direction: str) -> list[dict]:
        with self._lock:
            raw = [h for d, h in self._frames if d == direction]
        out = []
        for hex_str in raw:
            dec = decode_frame(hex_str)
            if dec["type"] == "I":
                out.append(dec)
        return out


_COLLECTORS: dict[str, WsCollector] = {}
_MARKS: dict[tuple[str, str], int] = {}


def collector(base: str) -> WsCollector:
    """获取（或惰性创建）某端的 WS 采集器."""
    c = _COLLECTORS.get(base)
    if c is None:
        c = WsCollector(base)
        c.wait_ready()
        _COLLECTORS[base] = c
    return c


def mark(base: str, direction: str = "tx") -> int:
    """记录当前帧序号；随后用 ``delta()`` 取之后的新帧（序号单调，不受窗口影响）."""
    n = collector(base).count(direction)
    _MARKS[(base, direction)] = n
    return n


def delta(base: str, direction: str = "tx") -> list[dict]:
    """取某端自上次 ``mark()`` 之后新采集的 I 帧."""
    if base not in _COLLECTORS:
        return []
    return collector(base).frames(direction)[_MARKS.get((base, direction), 0):]


def by_type(frames: list[dict], *type_ids: int) -> list[dict]:
    """按 TypeID 过滤帧列表."""
    return [f for f in frames if f["type_id"] in type_ids]


def yx_values(base: str) -> dict[int, str]:
    """取某端遥信实时值（按类型过滤——YK 与 YX 可能同 IOA，直接按 IOA 建字典会互相覆盖）."""
    return {p["ioa"]: p["value"] for p in get(base, "/api/points")["points"]
            if p["type"] == "YX"}
