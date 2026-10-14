"""WebSocket/订阅事件总线：环形缓冲 + 背压丢弃计数."""

from __future__ import annotations

import asyncio
import time
from typing import Any

# ── WS/REST 契约版本（T18）────────────────────────────────────────────
# 递增规则（详见 webui/api_contract.md §版本策略）：
#   * 破坏性变更（删字段 / 改类型 / 改语义）→ +1，消费方必须适配
#   * 纯新增字段（向后兼容）→ 不递增，消费方应忽略未知字段
# 该字段始终出现在 WS 消息信封顶层（snapshot / frame / event / log），
# 旧消费者（static/js/app.js 等）只读 kind/data，新增键向后兼容。
SCHEMA_VERSION = 1


class EventBus:
    def __init__(self, buffer_size: int = 500, queue_size: int = 256):
        self._buffer_size = buffer_size
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue] = set()
        self._frames: list[dict] = []
        self._events: list[dict] = []
        self._dropped = 0

    @property
    def dropped(self) -> int:
        return self._dropped

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, kind: str, data: dict) -> dict:
        msg = {
            "kind": kind,
            "schemaVersion": SCHEMA_VERSION,
            "ts": time.time(),
            "data": data,
        }
        if kind == "frame":
            self._frames.append(msg)
            if len(self._frames) > self._buffer_size:
                self._frames = self._frames[-self._buffer_size:]
        elif kind == "event":
            self._events.append(msg)
            if len(self._events) > self._buffer_size:
                self._events = self._events[-self._buffer_size:]
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # 背压：丢最旧再塞，保证 UI 能跟上
                self._dropped += 1
                try:
                    q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(msg)
                except Exception:
                    self._dropped += 1
        return msg

    def recent(self, kind: str, limit: int = 100) -> list[dict]:
        src = self._frames if kind == "frame" else self._events
        return src[-limit:]

    def export_session(self, role: str, status: dict[str, Any]) -> dict:
        return {
            "role": role,
            "status": status,
            "frames": self.recent("frame", 500),
            "events": self.recent("event", 500),
        }
