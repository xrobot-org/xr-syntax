"""定义解析诊断。
Parse diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass

from xr_syntax.core.span import SourcePoint, SourceSpan


@dataclass(frozen=True)
class Diagnostic:
    """一条解析诊断：消息、字节范围以及起止处的行号和字节列号（都从 0 开始）。
    One parse diagnostic: the message, the byte span, and the row and byte column (both from 0)
    where it starts and ends.
    """

    message: str
    span: SourceSpan
    start_point: SourcePoint
    end_point: SourcePoint
