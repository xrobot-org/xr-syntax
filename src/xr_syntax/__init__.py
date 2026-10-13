"""xr-syntax 的顶层接口：C++ 与 CMake 文档、解析器、构建器、排版引擎和语法树类型。
Top-level interface of xr-syntax: the C++ and CMake documents, their parsers and builders, the
layout engine, and the syntax-tree types.

顶层包只在真正用到某个名字时才导入对应的子模块：0.2.0 的用户只 `import xr_syntax.cpp`（或
`xr_syntax.i18n`）时，不该为 CMake、排版引擎和构建器付导入代价。
This package imports a submodule only when one of its names is actually used: a 0.2.0 user who only
imports xr_syntax.cpp, or xr_syntax.i18n, must not pay for the CMake, layout and builder modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# 每个公开名字来自哪个子模块。
# The submodule every public name comes from.
_ORIGIN = {
    # 核心抽象
    # Core abstractions
    "Diagnostic": "xr_syntax.core",
    "GreenChild": "xr_syntax.core",
    "GreenElement": "xr_syntax.core",
    "GreenNode": "xr_syntax.core",
    "GreenToken": "xr_syntax.core",
    "GreenTrivia": "xr_syntax.core",
    "SourceDraft": "xr_syntax.core",
    "SourcePoint": "xr_syntax.core",
    "SourceRegion": "xr_syntax.core",
    "SourceSpan": "xr_syntax.core",
    "SyntaxDocument": "xr_syntax.core",
    "SyntaxElement": "xr_syntax.core",
    "SyntaxFragment": "xr_syntax.core",
    "SyntaxNode": "xr_syntax.core",
    "SyntaxParserProtocol": "xr_syntax.core",
    "SyntaxToken": "xr_syntax.core",
    "SyntaxTree": "xr_syntax.core",
    "SyntaxTrivia": "xr_syntax.core",
    "decode_source": "xr_syntax.core",
    "encode_source": "xr_syntax.core",
    # C++ 前端
    # The C++ frontend
    "CppClassView": "xr_syntax.cpp",
    "CppDocument": "xr_syntax.cpp",
    "CppFileBuilder": "xr_syntax.cpp",
    "CppFunctionView": "xr_syntax.cpp",
    "CppIdentifierOccurrence": "xr_syntax.cpp",
    "CppIncludeView": "xr_syntax.cpp",
    "CppInvocationView": "xr_syntax.cpp",
    "CppLexicalToken": "xr_syntax.cpp",
    "CppParameterView": "xr_syntax.cpp",
    "CppParser": "xr_syntax.cpp",
    "CppRegion": "xr_syntax.cpp",
    "CppTemplateParameterView": "xr_syntax.cpp",
    "code_tokens": "xr_syntax.cpp",
    "identifier_occurrences": "xr_syntax.cpp",
    "matching_delimiter": "xr_syntax.cpp",
    "split_source_list": "xr_syntax.cpp",
    # CMake 前端
    # The CMake frontend
    "CMakeArgumentView": "xr_syntax.cmake",
    "CMakeCommandView": "xr_syntax.cmake",
    "CMakeDocument": "xr_syntax.cmake",
    "CMakeFileBuilder": "xr_syntax.cmake",
    "CMakeParser": "xr_syntax.cmake",
    "CMakeStatementView": "xr_syntax.cmake",
    # 排版引擎
    # The layout engine
    "Braces": "xr_syntax.format",
    "COLUMN_LIMIT": "xr_syntax.format",
    "INDENT": "xr_syntax.format",
    "layout_call": "xr_syntax.format",
    "layout_declaration": "xr_syntax.format",
    "layout_macro": "xr_syntax.format",
    "layout_statement": "xr_syntax.format",
    "layout_value": "xr_syntax.format",
    "sort_includes": "xr_syntax.format",
    "wrap_comment": "xr_syntax.format",
    # 输出语言
    # The output language
    "chinese": "xr_syntax.i18n",
    "localize_argparse": "xr_syntax.i18n",
    "tr": "xr_syntax.i18n",
}

# 类型检查时这些名字来自子模块；__all__ 让它们被视为再导出，而不是未使用的导入。
# For type checking these names come from the submodules; __all__ marks them as re-exports instead
# of unused imports.
if TYPE_CHECKING:  # pragma: no cover - 只为类型检查导入 / Imported for type checking only
    from xr_syntax.cmake import (
        CMakeArgumentView as CMakeArgumentView,
    )
    from xr_syntax.cmake import (
        CMakeCommandView as CMakeCommandView,
    )
    from xr_syntax.cmake import (
        CMakeDocument as CMakeDocument,
    )
    from xr_syntax.cmake import (
        CMakeFileBuilder as CMakeFileBuilder,
    )
    from xr_syntax.cmake import (
        CMakeParser as CMakeParser,
    )
    from xr_syntax.cmake import (
        CMakeStatementView as CMakeStatementView,
    )
    from xr_syntax.core import (
        Diagnostic as Diagnostic,
    )
    from xr_syntax.core import (
        GreenChild as GreenChild,
    )
    from xr_syntax.core import (
        GreenElement as GreenElement,
    )
    from xr_syntax.core import (
        GreenNode as GreenNode,
    )
    from xr_syntax.core import (
        GreenToken as GreenToken,
    )
    from xr_syntax.core import (
        GreenTrivia as GreenTrivia,
    )
    from xr_syntax.core import (
        SourceDraft as SourceDraft,
    )
    from xr_syntax.core import (
        SourcePoint as SourcePoint,
    )
    from xr_syntax.core import (
        SourceRegion as SourceRegion,
    )
    from xr_syntax.core import (
        SourceSpan as SourceSpan,
    )
    from xr_syntax.core import (
        SyntaxDocument as SyntaxDocument,
    )
    from xr_syntax.core import (
        SyntaxElement as SyntaxElement,
    )
    from xr_syntax.core import (
        SyntaxFragment as SyntaxFragment,
    )
    from xr_syntax.core import (
        SyntaxNode as SyntaxNode,
    )
    from xr_syntax.core import (
        SyntaxParserProtocol as SyntaxParserProtocol,
    )
    from xr_syntax.core import (
        SyntaxToken as SyntaxToken,
    )
    from xr_syntax.core import (
        SyntaxTree as SyntaxTree,
    )
    from xr_syntax.core import (
        SyntaxTrivia as SyntaxTrivia,
    )
    from xr_syntax.core import (
        decode_source as decode_source,
    )
    from xr_syntax.core import (
        encode_source as encode_source,
    )
    from xr_syntax.cpp import (
        CppClassView as CppClassView,
    )
    from xr_syntax.cpp import (
        CppDocument as CppDocument,
    )
    from xr_syntax.cpp import (
        CppFileBuilder as CppFileBuilder,
    )
    from xr_syntax.cpp import (
        CppFunctionView as CppFunctionView,
    )
    from xr_syntax.cpp import (
        CppIdentifierOccurrence as CppIdentifierOccurrence,
    )
    from xr_syntax.cpp import (
        CppIncludeView as CppIncludeView,
    )
    from xr_syntax.cpp import (
        CppInvocationView as CppInvocationView,
    )
    from xr_syntax.cpp import (
        CppLexicalToken as CppLexicalToken,
    )
    from xr_syntax.cpp import (
        CppParameterView as CppParameterView,
    )
    from xr_syntax.cpp import (
        CppParser as CppParser,
    )
    from xr_syntax.cpp import (
        CppRegion as CppRegion,
    )
    from xr_syntax.cpp import (
        CppTemplateParameterView as CppTemplateParameterView,
    )
    from xr_syntax.cpp import (
        code_tokens as code_tokens,
    )
    from xr_syntax.cpp import (
        identifier_occurrences as identifier_occurrences,
    )
    from xr_syntax.cpp import (
        matching_delimiter as matching_delimiter,
    )
    from xr_syntax.cpp import (
        split_source_list as split_source_list,
    )
    from xr_syntax.format import (
        COLUMN_LIMIT as COLUMN_LIMIT,
    )
    from xr_syntax.format import (
        INDENT as INDENT,
    )
    from xr_syntax.format import (
        Braces as Braces,
    )
    from xr_syntax.format import (
        layout_call as layout_call,
    )
    from xr_syntax.format import (
        layout_declaration as layout_declaration,
    )
    from xr_syntax.format import (
        layout_macro as layout_macro,
    )
    from xr_syntax.format import (
        layout_statement as layout_statement,
    )
    from xr_syntax.format import (
        layout_value as layout_value,
    )
    from xr_syntax.format import (
        sort_includes as sort_includes,
    )
    from xr_syntax.format import (
        wrap_comment as wrap_comment,
    )
    from xr_syntax.i18n import chinese as chinese
    from xr_syntax.i18n import localize_argparse as localize_argparse
    from xr_syntax.i18n import tr as tr


def __getattr__(name: str) -> Any:
    """按第一次使用的名字导入对应子模块，而不是在 import xr_syntax 时全部导入。
    Import the submodule a name comes from on first use, instead of everything at import xr_syntax.
    """
    module = _ORIGIN.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module), name)


def __dir__() -> list[str]:
    """列出顶层包公开的名字。
    List the public names of the top-level package.
    """
    return sorted(_ORIGIN)


# 公开的名字集合；由 _ORIGIN 的键填出，类型检查据此判断这些导入是再导出。
# The public names; filled from the keys of _ORIGIN, so a type checker sees the imports above as
# re-exports.
__all__ = sorted(_ORIGIN)
