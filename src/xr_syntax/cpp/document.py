"""提供 C++ 高层查询、类型化视图入口以及受保护源码区域的编辑能力。
High-level C++ document queries and protected-region editing helpers.
"""

from __future__ import annotations

import re

from xr_syntax.core import (
    SourceRegion,
    SyntaxDocument,
    SyntaxNode,
    SyntaxParserProtocol,
    SyntaxTree,
)
from xr_syntax.cpp.invocation import (
    CppIdentifierOccurrence,
    CppInvocationView,
    find_invocations,
    identifier_occurrences_of,
)
from xr_syntax.cpp.lexer import Lexed, lex
from xr_syntax.cpp.lexical import CppLexicalToken, code_tokens_of
from xr_syntax.cpp.parser import CppParser, parse_with_lexing
from xr_syntax.cpp.view import CppClassView, CppIncludeView

# ---------------------------------------------------------------------------
# 受保护源码区域
# Protected source regions
# ---------------------------------------------------------------------------

# 区域的实现与配对规则在 core.document，两种语言共用；这里保留 CppRegion 这个名字。
# The region implementation and pairing rules live in core.document and are shared by both
# languages; the name CppRegion is kept here.
CppRegion = SourceRegion

# C++ 的 User Code 标记：区分大小写，与 STM32CubeMX 写出的一致。
# The C++ User Code markers: case-sensitive, as STM32CubeMX writes them.
_USER_BEGIN = re.compile(r"/\*\s*User Code Begin(?:\s+(.+?))?\s*\*/")
_USER_END = re.compile(r"/\*\s*User Code End(?:\s+(.+?))?\s*\*/")


# ---------------------------------------------------------------------------
# C++ 文档查询
# C++ document queries
# ---------------------------------------------------------------------------


class CppDocument(SyntaxDocument):
    """在完整 C++ 语法树之上提供高层文档能力。
    C++-specific query/edit facade over the complete generic syntax tree.
    """

    __slots__ = ("_lexed",)

    language = "cpp"

    def __init__(
        self,
        tree: SyntaxTree,
        parser: SyntaxParserProtocol,
        lexed: Lexed | None = None,
    ) -> None:
        """绑定语法树和解析器；lexed 是解析时的词法结果，没有时在首次用到时重新切分。
        Bind a syntax tree and parser; lexed is the lexing result of the parse, and without it
        the source is lexed on first use.
        """
        super().__init__(tree, parser)
        self._lexed = lexed

    @classmethod
    def parse(
        cls,
        source: str | bytes,
        *,
        source_name: str | None = None,
        parser: CppParser | None = None,
    ) -> CppDocument:
        """解析源码，得到文档；source_name 记录在语法树上，词法结果留给词法查询复用。
        Parse source into a document; source_name is recorded on the syntax tree, and the lexing
        result is kept for the lexical queries to reuse.

        parser 给出复用的解析器实例（工厂与构建器这样做，避免每次解析都新建一个）；省略时新建。
        parser reuses one parser instance, as the factory and builders do instead of creating one
        per parse; without it a new parser is created.
        """
        if parser is None:
            tree, lexed = parse_with_lexing(source, source_name)
            return cls(tree, CppParser(), lexed)
        tree = parser.parse(source, source_name=source_name)
        return cls(tree, parser, lex(tree.render()))

    def _lexing(self) -> Lexed:
        """文档源码的词法结果（lexeme 和 lexer 诊断）。
        The lexing result (lexemes and lexer diagnostics) of the document's source.
        """
        if self._lexed is None:
            self._lexed = lex(self.tree.render())
        return self._lexed

    def code_tokens(self) -> tuple[CppLexicalToken, ...]:
        """与 code_tokens(document.render()) 相同，复用解析时的词法结果。
        The same as code_tokens(document.render()), reusing the lexing of the parse.

        Raises:
            ValueError: 源码有词法错误（未闭合的块注释或原始字符串）。
                The source has a lexical error (an unclosed block comment or raw string).
        """
        lexed = self._lexing()
        if lexed.diagnostics:
            raise ValueError(lexed.diagnostics[0].message)
        return code_tokens_of(lexed)

    def identifier_occurrences(self) -> tuple[CppIdentifierOccurrence, ...]:
        """与 identifier_occurrences(document.render()) 相同，复用解析时的词法结果。
        The same as identifier_occurrences(document.render()), reusing the lexing of the parse.

        Raises:
            ValueError: 源码有词法错误（未闭合的块注释或原始字符串）。
                The source has a lexical error (an unclosed block comment or raw string).
        """
        lexed = self._lexing()
        if lexed.diagnostics:
            raise ValueError(lexed.diagnostics[0].message)
        return identifier_occurrences_of(lexed)

    def include_views(self) -> tuple[CppIncludeView, ...]:
        """按源码顺序返回全部 #include 的视图。
        Views of all #include directives, in source order.
        """
        return tuple(CppIncludeView(node) for node in self.nodes("preproc_include"))

    def class_views(self, name: str | None = None) -> tuple[CppClassView, ...]:
        """按源码顺序返回 class 和 struct 的视图；给出 name 时只返回同名的。
        Views of the classes and structs in source order; with name, only those of that name.
        """
        kinds = frozenset({"class_specifier", "struct_specifier"})
        views = (
            CppClassView(element)
            for element in self.root.descendants(kinds=kinds, include_self=True)
            if isinstance(element, SyntaxNode)
        )
        return tuple(view for view in views if name is None or view.name == name)

    def invocation_views(
        self,
        name: str,
        *,
        template_angles: bool = False,
    ) -> tuple[CppInvocationView, ...]:
        """按词法规则查找 NAME(...)，用于宏等非普通 call-expression 结构。
        Find lexical NAME(...) invocations for macros and similar source constructs.
        """
        return find_invocations(
            self.tree, name, template_angles=template_angles, lexed=self._lexing()
        )

    def user_regions(self) -> tuple[CppRegion, ...]:
        """识别并返回成对的 User Code Begin/End 区域，按源码顺序排列。
        Find paired STM32-style User Code Begin/End comment regions, in source order.

        配对与校验语义在 core.document.SyntaxDocument.paired_comment_regions，CMake 侧共用同一套。
        The pairing and validation semantics are in
        core.document.SyntaxDocument.paired_comment_regions and are shared with the CMake frontend.
        """
        return self.paired_comment_regions(kind="user", begin=_USER_BEGIN, end=_USER_END)
