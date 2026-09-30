"""提供 C++ 高层查询、类型化视图入口以及受保护源码区域的编辑能力。
High-level C++ document queries and protected-region editing helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from xr_syntax.core import (
    Diagnostic,
    SourceSpan,
    SyntaxDocument,
    SyntaxElement,
    SyntaxNode,
    SyntaxParserProtocol,
    SyntaxToken,
    SyntaxTree,
    encode_source,
)

from .grammar import CPP_GRAMMAR
from .invocation import (
    CppIdentifierOccurrence,
    CppInvocationView,
    _identifier_occurrences_of,
    find_invocations,
)
from .lexer import _Lexeme, _Lexer
from .lexical import CppLexicalToken, _code_tokens_of
from .parser import CppParser
from .syntax_utils import declaration_name, field_text
from .view import (
    CppCallView,
    CppClassView,
    CppFunctionView,
    CppIncludeView,
    CppVariableView,
)

# ---------------------------------------------------------------------------
# 受保护源码区域
# Protected source regions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CppRegion:
    """表示由成对标记界定的源码保护区域，例如 User Code、clang-format 或 NOLINT。
    Paired source-marker region such as User Code, clang-format or NOLINT.
    """

    kind: str
    name: str | None
    begin: SyntaxElement
    end: SyntaxElement
    body_span: SourceSpan
    body_text: str


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
    grammar = CPP_GRAMMAR

    def __init__(
        self,
        tree: SyntaxTree,
        parser: SyntaxParserProtocol,
        lexed: tuple[list[_Lexeme], list[Diagnostic]] | None = None,
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
        """使用 xr-syntax 原生 C++ parser 解析源码并保留 source_name。
        Parse C++ source with the validated default parser while preserving source identity.
        """
        selected = parser or CppParser()
        # 重写了 parse 的解析器照常调用；词法结果在首次用到时重新切分。
        # A parser that overrides parse is called as usual; the source is lexed on first use.
        if type(selected).parse is not CppParser.parse:
            return cls(selected.parse(source, source_name=source_name), selected)
        tree, lexed = selected._parse_lexed(source, source_name)
        return cls(tree, selected, lexed)

    def _lexemes(self) -> tuple[list[_Lexeme], list[Diagnostic]]:
        """文档源码的 lexeme 和 lexer 诊断。
        The lexemes and lexer diagnostics of the document's source.
        """
        if self._lexed is None:
            self._lexed = _Lexer(self.tree.render()).scan()
        return self._lexed

    def code_tokens(self) -> tuple[CppLexicalToken, ...]:
        """与 code_tokens(document.render()) 相同，复用解析时的词法结果。
        The same as code_tokens(document.render()), reusing the lexing of the parse.

        Raises:
            ValueError: 源码有词法错误（未闭合的注释或字面量）。
                The source has a lexical error (an unclosed comment or literal).
        """
        lexemes, diagnostics = self._lexemes()
        if diagnostics:
            raise ValueError(diagnostics[0].message)
        return _code_tokens_of(lexemes)

    def identifier_occurrences(self) -> tuple[CppIdentifierOccurrence, ...]:
        """与 identifier_occurrences(document.render()) 相同，复用解析时的词法结果。
        The same as identifier_occurrences(document.render()), reusing the lexing of the parse.

        Raises:
            ValueError: 源码有词法错误（未闭合的注释或字面量）。
                The source has a lexical error (an unclosed comment or literal).
        """
        lexemes, diagnostics = self._lexemes()
        if diagnostics:
            raise ValueError(diagnostics[0].message)
        return _identifier_occurrences_of(lexemes)

    def is_expression(self, element: SyntaxElement) -> bool:
        """依据 C++ grammar subtype 图判断元素是否属于 expression。
        Classify an element through the packaged grammar subtype graph.
        """
        if not isinstance(element, (SyntaxNode, SyntaxToken)):
            return False
        return self.grammar.is_subtype(
            element.kind,
            "expression",
            actual_named=element.named,
        )

    def is_statement(self, element: SyntaxElement) -> bool:
        """依据 C++ grammar subtype 图判断元素是否属于 statement。
        Classify an element through the packaged grammar subtype graph.
        """
        if not isinstance(element, (SyntaxNode, SyntaxToken)):
            return False
        return self.grammar.is_subtype(
            element.kind,
            "statement",
            actual_named=element.named,
        )

    def replace_region_body(self, region: CppRegion, body: str) -> CppDocument:
        """替换当前文档中一个已验证区域的 body。
        Replace the body of a validated region owned by this document snapshot.
        """
        source = self.render_bytes()
        self._validate_region(region, len(source))
        replacement = encode_source(body)
        changed = source[: region.body_span.start] + replacement + source[region.body_span.end :]
        return self._reparse(changed)

    def _validate_region(self, region: CppRegion, source_size: int) -> None:
        """确认 region 属于当前快照且 body span 与 marker 一致。
        Verify region ownership and ensure its body span matches the paired markers.
        """
        if region.begin.tree is not self.tree or region.end.tree is not self.tree:
            raise ValueError("region belongs to a different immutable syntax snapshot")
        expected = SourceSpan(region.begin.span.end, region.end.span.start)
        if region.body_span != expected:
            raise ValueError("region body span does not match its begin/end markers")
        if region.body_span.end > source_size:
            raise ValueError("region body span exceeds the current source range")

    def includes(self) -> tuple[SyntaxNode, ...]:
        """按源码顺序返回原始 preproc_include 节点。
        Return raw preprocessor include syntax nodes.
        """
        return self.nodes("preproc_include")

    def include_views(self) -> tuple[CppIncludeView, ...]:
        """为全部 include 节点创建 CppIncludeView。
        Return typed convenience views for all include directives.
        """
        return tuple(CppIncludeView(node) for node in self.includes())

    def comments(self) -> tuple[SyntaxElement, ...]:
        """按源码顺序返回 parser 识别的注释元素。
        Return parser comment elements in source order.
        """
        return self.elements("comment")

    def functions(self, name: str | None = None) -> tuple[SyntaxNode, ...]:
        """返回函数定义，并可按源码级函数名过滤。
        Return function definitions, optionally filtered by source-level name.
        """
        nodes = self.nodes("function_definition")
        if name is None:
            return nodes
        return tuple(node for node in nodes if declaration_name(node) == name)

    def classes(self, name: str | None = None) -> tuple[SyntaxNode, ...]:
        """返回 class/struct 定义，并可按源码级名称过滤。
        Return class/struct specifiers, optionally filtered by source-level name.
        """
        nodes = self.nodes("class_specifier") + self.nodes("struct_specifier")
        if name is None:
            return nodes
        return tuple(node for node in nodes if field_text(node, "name") == name)

    def calls(self, name: str | None = None) -> tuple[SyntaxNode, ...]:
        """返回调用表达式，并可按精确 callee 源码文本过滤。
        Return call expressions, optionally filtered by exact callee source text.
        """
        nodes = self.nodes("call_expression")
        if name is None:
            return nodes
        return tuple(node for node in nodes if field_text(node, "function") == name)

    def function_views(self, name: str | None = None) -> tuple[CppFunctionView, ...]:
        """把匹配的函数节点包装为 CppFunctionView。
        Wrap matching function definitions in CppFunctionView.
        """
        return tuple(CppFunctionView(node) for node in self.functions(name))

    def class_views(self, name: str | None = None) -> tuple[CppClassView, ...]:
        """把匹配的类节点包装为 CppClassView。
        Wrap matching class or struct specifiers in CppClassView.
        """
        return tuple(CppClassView(node) for node in self.classes(name))

    def call_views(self, name: str | None = None) -> tuple[CppCallView, ...]:
        """把匹配的调用节点包装为 CppCallView。
        Wrap matching call expressions in CppCallView.
        """
        return tuple(CppCallView(node) for node in self.calls(name))

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
            self.tree, name, template_angles=template_angles, lexemes=self._lexemes()[0]
        )

    # declaration 视图只按当前 syntax fields 识别变量 declarator。
    # Declaration views classify variable declarators from the current syntax fields.
    def variable_views(
        self,
        name: str | None = None,
        *,
        global_scope: bool | None = None,
    ) -> tuple[CppVariableView, ...]:
        """返回变量声明视图，并可按全局/局部作用域过滤。
        Return variable-like declarations, optionally filtered by name and lexical scope.
        """
        result: list[CppVariableView] = []
        for declaration in self.nodes("declaration"):
            for declarator in declaration.children_by_field("declarator"):
                if isinstance(declarator, SyntaxNode) and (
                    declarator.kind == "function_declarator"
                    or declarator.first_descendant("function_declarator") is not None
                ):
                    continue
                view = CppVariableView(declaration, declarator)
                if name is not None and view.name != name:
                    continue
                if global_scope is not None and view.global_scope != global_scope:
                    continue
                result.append(view)
        return tuple(result)

    def declarations(self) -> tuple[SyntaxNode, ...]:
        """返回文档中的声明节点集合。
        Return common declaration-like syntax nodes.
        """
        kinds = ("declaration", "function_definition", "template_declaration")
        return tuple(node for kind in kinds for node in self.nodes(kind))

    def user_regions(self) -> tuple[CppRegion, ...]:
        """识别并返回成对的 User Code Begin/End 区域。
        Find paired STM32-style User Code Begin/End comment regions.
        """
        return self._paired_comment_regions(
            kind="user",
            begin=re.compile(r"/\*\s*User Code Begin(?:\s+(.+?))?\s*\*/"),
            end=re.compile(r"/\*\s*User Code End(?:\s+(.+?))?\s*\*/"),
        )

    def format_regions(self) -> tuple[CppRegion, ...]:
        """识别并返回 clang-format off/on 区域。
        Find paired clang-format off/on comment regions.
        """
        return self._paired_comment_regions(
            kind="format",
            begin=re.compile(r"//\s*clang-format\s+off\b"),
            end=re.compile(r"//\s*clang-format\s+on\b"),
        )

    def lint_regions(self) -> tuple[CppRegion, ...]:
        """识别并返回 NOLINTBEGIN/NOLINTEND 区域。
        Find paired NOLINTBEGIN/NOLINTEND comment regions.
        """
        return self._paired_comment_regions(
            kind="lint",
            begin=re.compile(r"//\s*NOLINTBEGIN\b"),
            end=re.compile(r"//\s*NOLINTEND\b"),
        )

    # 区域标记由普通 C++ 注释配对得到，实现在 document 层。
    # Region markers are paired from ordinary C++ comments at the document layer.
    def _paired_comment_regions(
        self,
        *,
        kind: str,
        begin: re.Pattern[str],
        end: re.Pattern[str],
    ) -> tuple[CppRegion, ...]:
        """按 begin/end 正则匹配成对注释，并构造带 body span 的区域对象。
        Pair begin/end comments and construct protected-region objects with body spans.
        """
        source = self.render_bytes()
        stack: list[tuple[SyntaxElement, str | None]] = []
        regions: list[CppRegion] = []
        for comment in sorted(self.comments(), key=lambda node: node.span.start):
            begin_match = begin.fullmatch(comment.text.strip())
            if begin_match:
                name = begin_match.group(1).strip() if begin_match.lastindex else None
                stack.append((comment, name))
                continue
            end_match = end.fullmatch(comment.text.strip())
            if not end_match or not stack:
                continue
            start, name = stack[-1]
            end_name = (
                end_match.group(1).strip()
                if end_match.lastindex and end_match.group(1) is not None
                else None
            )
            if end_name != name:
                continue
            stack.pop()
            body = SourceSpan(start.span.end, comment.span.start)
            regions.append(
                CppRegion(
                    kind,
                    name,
                    start,
                    comment,
                    body,
                    source[body.start : body.end].decode(
                        "utf-8",
                        errors="surrogateescape",
                    ),
                )
            )
        return tuple(sorted(regions, key=lambda region: region.begin.span.start))
