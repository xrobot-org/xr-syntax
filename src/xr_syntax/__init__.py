"""xr-syntax 的顶层接口：C++ 文档、解析器和语法树类型。
Top-level interface of xr-syntax: the C++ document, its parser and the syntax-tree types.
"""

from xr_syntax.core import (
    Diagnostic,
    GreenChild,
    GreenNode,
    GreenToken,
    GreenTrivia,
    SourcePoint,
    SourceSpan,
    SyntaxElement,
    SyntaxNode,
    SyntaxToken,
    SyntaxTree,
    SyntaxTrivia,
)
from xr_syntax.cpp import CppDocument, CppParser, CppRegion

__all__ = [
    "CppDocument",
    "CppParser",
    "CppRegion",
    "Diagnostic",
    "GreenChild",
    "GreenNode",
    "GreenToken",
    "GreenTrivia",
    "SourcePoint",
    "SourceSpan",
    "SyntaxElement",
    "SyntaxNode",
    "SyntaxToken",
    "SyntaxTree",
    "SyntaxTrivia",
]
