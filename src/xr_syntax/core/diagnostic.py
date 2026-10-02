"""定义附着在不可变语法快照上的解析诊断数据结构。
Parser diagnostics attached to immutable syntax snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass

from .span import SourcePoint, SourceSpan


@dataclass(frozen=True)
class Diagnostic:
    """表示一条绑定到源码字节范围的 parser 诊断。
    Describe one parser diagnostic anchored to a byte span.
    """

    message: str
    span: SourceSpan
    start_point: SourcePoint | None = None
    end_point: SourcePoint | None = None
    severity: str = "error"
