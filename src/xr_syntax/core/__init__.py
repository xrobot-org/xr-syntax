"""集中导出不可变语法树、源码范围、诊断、片段和文档等核心抽象。
Core abstractions: the immutable syntax tree, source spans, diagnostics, fragments and documents.

片段与草稿只在第一次用到它们时才导入：只读地使用语法树或文档时不该为它们付出导入代价。
The fragments and drafts are imported on first use only: using the tree or a document read-only must
not pay for them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from xr_syntax.core.diagnostic import Diagnostic
from xr_syntax.core.document import SourceRegion, SyntaxDocument, SyntaxParserProtocol
from xr_syntax.core.green import GreenChild, GreenElement, GreenNode, GreenToken, GreenTrivia
from xr_syntax.core.red import SyntaxElement, SyntaxNode, SyntaxToken, SyntaxTrivia
from xr_syntax.core.span import SourcePoint, SourceSpan
from xr_syntax.core.text import decode_source, encode_source
from xr_syntax.core.tree import SyntaxTree

if TYPE_CHECKING:  # pragma: no cover - 只为类型检查导入 / Imported for type checking only
    from xr_syntax.core.fragment import (
        SourceDraft as SourceDraft,
    )
    from xr_syntax.core.fragment import (
        SyntaxFragment as SyntaxFragment,
    )

# 需要时才导入的名字与它们所在的子模块。
# The names imported on demand and the submodule they live in.
_LAZY = {
    "SourceDraft": "xr_syntax.core.fragment",
    "SyntaxFragment": "xr_syntax.core.fragment",
}


def __getattr__(name: str) -> Any:
    """按第一次使用的名字导入对应子模块。
    Import the submodule a name comes from on first use.
    """
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module), name)


__all__ = [
    "Diagnostic",
    "GreenChild",
    "GreenElement",
    "GreenNode",
    "GreenToken",
    "GreenTrivia",
    "SourceDraft",
    "SourcePoint",
    "SourceRegion",
    "SourceSpan",
    "SyntaxDocument",
    "SyntaxElement",
    "SyntaxFragment",
    "SyntaxNode",
    "SyntaxParserProtocol",
    "SyntaxToken",
    "SyntaxTree",
    "SyntaxTrivia",
    "decode_source",
    "encode_source",
]
