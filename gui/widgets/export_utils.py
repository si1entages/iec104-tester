"""数据导出工具."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, QAbstractTableModel
from PySide6.QtWidgets import QFileDialog, QTableView, QWidget, QMessageBox


def export_table_to_csv(parent: QWidget, table_view: QTableView,
                        title: str = "导出数据") -> bool:
    """将表格数据导出为CSV文件."""
    model = table_view.model()
    if not model:
        QMessageBox.warning(parent, "导出失败", "没有数据可导出")
        return False

    # 获取保存路径
    default_name = f"{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    file_path, _ = QFileDialog.getSaveFileName(
        parent, f"导出{title}", default_name,
        "CSV文件 (*.csv);;所有文件 (*.*)"
    )

    if not file_path:
        return False

    try:
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)

            # 写入表头
            headers = []
            for col in range(model.columnCount()):
                header = model.headerData(col, Qt.Horizontal)
                headers.append(str(header) if header else f"列{col}")
            writer.writerow(headers)

            # 写入数据
            for row in range(model.rowCount()):
                row_data = []
                for col in range(model.columnCount()):
                    index = model.index(row, col)
                    data = model.data(index)
                    row_data.append(str(data) if data is not None else "")
                writer.writerow(row_data)

        QMessageBox.information(parent, "导出成功",
                                f"数据已导出到:\n{file_path}")
        return True

    except Exception as e:
        QMessageBox.critical(parent, "导出失败", f"导出数据时出错:\n{str(e)}")
        return False


def export_hex_to_file(parent: QWidget, hex_content: str,
                       title: str = "报文") -> bool:
    """将HEX内容导出为文件."""
    # 获取保存路径
    default_name = f"{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    file_path, _ = QFileDialog.getSaveFileName(
        parent, f"导出{title}", default_name,
        "文本文件 (*.txt);;所有文件 (*.*)"
    )

    if not file_path:
        return False

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(hex_content)

        QMessageBox.information(parent, "导出成功",
                                f"报文已导出到:\n{file_path}")
        return True

    except Exception as e:
        QMessageBox.critical(parent, "导出失败", f"导出报文时出错:\n{str(e)}")
        return False


def export_log_to_file(parent: QWidget, log_content: str,
                       title: str = "日志") -> bool:
    """将日志内容导出为文件."""
    # 获取保存路径
    default_name = f"{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_path, _ = QFileDialog.getSaveFileName(
        parent, f"导出{title}", default_name,
        "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*.*)"
    )

    if not file_path:
        return False

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(log_content)

        QMessageBox.information(parent, "导出成功",
                                f"日志已导出到:\n{file_path}")
        return True

    except Exception as e:
        QMessageBox.critical(parent, "导出失败", f"导出日志时出错:\n{str(e)}")
        return False


def export_data_to_json(parent: QWidget, data: dict[str, Any],
                        title: str = "数据") -> bool:
    """将数据导出为JSON文件."""
    # 获取保存路径
    default_name = f"{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    file_path, _ = QFileDialog.getSaveFileName(
        parent, f"导出{title}", default_name,
        "JSON文件 (*.json);;所有文件 (*.*)"
    )

    if not file_path:
        return False

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        QMessageBox.information(parent, "导出成功",
                                f"数据已导出到:\n{file_path}")
        return True

    except Exception as e:
        QMessageBox.critical(parent, "导出失败", f"导出数据时出错:\n{str(e)}")
        return False
