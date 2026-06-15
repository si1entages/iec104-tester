"""视图模块 — 主站/子站视图分离."""

from .base_view import BaseView
from .master_view import MasterView
from .slave_view import SlaveView

__all__ = ["BaseView", "MasterView", "SlaveView"]
