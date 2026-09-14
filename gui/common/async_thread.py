"""独立线程运行 asyncio 事件循环."""

from __future__ import annotations

import asyncio
from typing import Optional

from PySide6.QtCore import QThread


class AsyncThread(QThread):
    """在独立线程运行 asyncio 事件循环."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.wait(3000)

    def run_coroutine(self, coro):
        if self.loop and self.loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        coro.close()
        return None
