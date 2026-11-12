"""报告导出（WP8）：``Evidence`` 模型 + xlsx / PDF / HTML 三种渲染.

对外只需两个名字：

- :class:`Evidence` / :func:`points_from_session` —— 组装归档数据；
- :func:`export_report` / :func:`pdf_available` —— 渲染与能力探测。
"""

from .evidence import Evidence, EvidencePoint, points_from_session
from .report import PdfUnavailable, export_report, pdf_available

__all__ = [
    "Evidence",
    "EvidencePoint",
    "PdfUnavailable",
    "export_report",
    "pdf_available",
    "points_from_session",
]
