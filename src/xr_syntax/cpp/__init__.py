"""C++ 前端：解析器、文档、查询视图、词法工具和文件构建器。
C++ frontend: the parser, documents, query views, lexical helpers and the file builder.
"""

from xr_syntax.cpp.builder import CppFileBuilder
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
