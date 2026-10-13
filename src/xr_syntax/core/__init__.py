"""集中导出不可变语法树、源码范围、诊断、片段和文档等核心抽象。
Core abstractions: the immutable syntax tree, source spans, diagnostics, fragments and documents.
"""

from xr_syntax.core.diagnostic import Diagnostic
from xr_syntax.core.document import SourceRegion, SyntaxDocument, SyntaxParserProtocol
from xr_syntax.core.fragment import SourceDraft, SyntaxFragment
from xr_syntax.core.green import GreenChild, GreenElement, GreenNode, GreenToken, GreenTrivia
from xr_syntax.core.red import SyntaxElement, SyntaxNode, SyntaxToken, SyntaxTrivia
from xr_syntax.core.span import SourcePoint, SourceSpan
from xr_syntax.core.text import decode_source, encode_source
from xr_syntax.core.tree import SyntaxTree

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
