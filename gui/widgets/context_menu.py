"""通用右键菜单工厂."""

from __future__ import annotations

from PySide6.QtWidgets import QMenu, QApplication
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtCore import Signal, QObject


class ContextMenuFactory(QObject):
    """右键菜单工厂."""

    # 信号
    copy_triggered = Signal()
    copy_row_triggered = Signal()
    copy_ioa_triggered = Signal()
    export_csv_triggered = Signal()
    send_command_triggered = Signal(int)  # ioa
    set_value_triggered = Signal(int)     # ioa

    def __init__(self, parent=None):
        super().__init__(parent)

    def create_table_menu(self, ioa: int = None, has_command: bool = False) -> QMenu:
        """创建表格右键菜单."""
        menu = QMenu()

        # 复制操作
        copy_action = QAction("复制", menu)
        copy_action.setShortcut(QKeySequence("Ctrl+C"))
        copy_action.triggered.connect(self.copy_triggered.emit)
        menu.addAction(copy_action)

        copy_row_action = QAction("复制整行", menu)
        copy_row_action.triggered.connect(self.copy_row_triggered.emit)
        menu.addAction(copy_row_action)

        copy_ioa_action = QAction("复制 IOA", menu)
        copy_ioa_action.triggered.connect(self.copy_ioa_triggered.emit)
        menu.addAction(copy_ioa_action)

        menu.addSeparator()

        # 导出操作
        export_action = QAction("导出 CSV", menu)
        export_action.triggered.connect(self.export_csv_triggered.emit)
        menu.addAction(export_action)

        # 命令操作（如果适用）
        if has_command and ioa is not None:
            menu.addSeparator()
            cmd_action = QAction(f"发送命令到 IOA {ioa}", menu)
            cmd_action.triggered.connect(lambda: self.send_command_triggered.emit(ioa))
            menu.addAction(cmd_action)

            set_action = QAction(f"设置 IOA {ioa} 的值", menu)
            set_action.triggered.connect(lambda: self.set_value_triggered.emit(ioa))
            menu.addAction(set_action)

        return menu

    def create_hex_menu(self) -> QMenu:
        """创建HEX查看器右键菜单."""
        menu = QMenu()

        copy_action = QAction("复制选中", menu)
        copy_action.setShortcut(QKeySequence("Ctrl+C"))
        copy_action.triggered.connect(self.copy_triggered.emit)
        menu.addAction(copy_action)

        copy_all_action = QAction("复制全部", menu)
        copy_all_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        copy_all_action.triggered.connect(lambda: self._copy_all_hex())
        menu.addAction(copy_all_action)

        menu.addSeparator()

        export_action = QAction("导出报文", menu)
        export_action.triggered.connect(self.export_csv_triggered.emit)
        menu.addAction(export_action)

        return menu

    def create_log_menu(self) -> QMenu:
        """创建日志右键菜单."""
        menu = QMenu()

        copy_action = QAction("复制选中", menu)
        copy_action.setShortcut(QKeySequence("Ctrl+C"))
        copy_action.triggered.connect(self.copy_triggered.emit)
        menu.addAction(copy_action)

        copy_all_action = QAction("复制全部日志", menu)
        copy_all_action.triggered.connect(lambda: self._copy_all_log())
        menu.addAction(copy_all_action)

        menu.addSeparator()

        clear_action = QAction("清空日志", menu)
        clear_action.setShortcut(QKeySequence("Ctrl+L"))
        clear_action.triggered.connect(self._clear_log)
        menu.addAction(clear_action)

        export_action = QAction("导出日志", menu)
        export_action.triggered.connect(self.export_csv_triggered.emit)
        menu.addAction(export_action)

        return menu

    def _copy_all_hex(self):
        """复制全部HEX内容."""
        # 由具体实现覆盖
        pass

    def _copy_all_log(self):
        """复制全部日志."""
        # 由具体实现覆盖
        pass

    def _clear_log(self):
        """清空日志."""
        # 由具体实现覆盖
        pass
