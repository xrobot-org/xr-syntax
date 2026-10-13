"""C++ 前端：解析器、文档、查询视图、词法工具和文件构建器。
C++ frontend: the parser, documents, query views, lexical helpers and the file builder.

文件构建器只在第一次用到它时才导入：只读地使用 C++ 前端时不该为它和它依赖的片段模块付出导入代价。
The file builder is imported on first use only: using the C++ frontend read-only must not pay for it
or for the fragment module it depends on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from xr_syntax.cpp.document import CppDocument, CppRegion
from xr_syntax.cpp.invocation import (
    CppIdentifierOccurrence,
    CppInvocationView,
    identifier_occurrences,
    split_source_list,
)
from xr_syntax.cpp.lexical import CppLexicalToken, code_tokens, matching_delimiter
from xr_syntax.cpp.parser import CppParser
from xr_syntax.cpp.view import (
    CppClassView,
    CppFunctionView,
    CppIncludeView,
    CppParameterView,
    CppTemplateParameterView,
)

if TYPE_CHECKING:  # pragma: no cover - 只为类型检查导入 / Imported for type checking only
    from xr_syntax.cpp.builder import (
        CppFileBuilder as CppFileBuilder,
    )


def __getattr__(name: str) -> Any:
    """按第一次使用的名字导入文件构建器。
    Import the file builder on first use.
    """
    if name == "CppFileBuilder":
        from xr_syntax.cpp.builder import CppFileBuilder

        return CppFileBuilder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CppClassView",
    "CppDocument",
    "CppFileBuilder",
    "CppFunctionView",
    "CppIdentifierOccurrence",
    "CppIncludeView",
    "CppInvocationView",
    "CppLexicalToken",
    "CppParameterView",
    "CppParser",
    "CppRegion",
    "CppTemplateParameterView",
    "code_tokens",
    "identifier_occurrences",
    "matching_delimiter",
    "split_source_list",
]
