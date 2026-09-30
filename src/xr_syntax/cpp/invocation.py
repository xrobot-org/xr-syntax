"""提供宏式 NAME(...) invocation 的词法查询和逗号列表切分。
Lexical queries for macro-like NAME(...) invocations and comma-delimited source lists.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from xr_syntax.core import SourceSpan, SyntaxTree, decode_source

from ._lexical_support import _preprocessor_mask
from .lexer import _Lexeme, _Lexer

# ---------------------------------------------------------------------------
# 模块实现：提供宏式 NAME(...) invocation 的词法查询和逗号列表切分。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CppInvocationView:
    """表示指定名字的词法 invocation 及其精确源码实参。
    Lexical view of one named invocation together with exact source arguments.
    """

    tree: SyntaxTree
    name: str
    span: SourceSpan
    arguments: tuple[str, ...]

    @property
    def text(self) -> str:
        """返回 invocation 的精确源码文本。
        Return exact source text for the invocation.
        """
        return decode_source(self.tree.render_bytes()[self.span.start : self.span.end])

    @property
    def line(self) -> int:
        """返回一基源码行号。
        Return the one-based source line number.
        """
        return self.tree.render_bytes()[: self.span.start].count(b"\n") + 1


@dataclass(frozen=True)
class CppIdentifierOccurrence:
    """表示一个源码 identifier 及相邻有效 token。
    Source identifier occurrence with adjacent significant-token spellings.
    """

    text: str
    span: SourceSpan
    previous: str | None
    following: str | None

    @property
    def qualified_left(self) -> bool:
        """判断 identifier 左侧是否通过成员或作用域运算符限定。
        Return whether the identifier is qualified from the left.
        """
        return self.previous in (".", "->", ".*", "->*", "::")

    @property
    def scope_root(self) -> bool:
        """判断 identifier 是否作为作用域限定符的根。
        Return whether the identifier is followed by a scope-resolution operator.
        """
        return self.following == "::"


# 宏参数和模板参数的逗号不能用 str.split(',')：只有所有括号/方括号/花括号
# （以及可选模板尖括号）depth 都为 0 时，逗号才是当前列表的分隔符。
def split_source_list(source: str, *, template_angles: bool = False) -> tuple[str, ...]:
    """按顶层逗号切分源码列表，并按需把模板角括号视为嵌套。
    Split source on top-level commas, optionally treating template angles as nesting.
    """
    lexemes, diagnostics = _Lexer(source).scan()
    if diagnostics:
        raise ValueError(diagnostics[0].message)
    significant = [item for item in lexemes if not item.trivia and item.kind != "comment"]
    if not significant:
        return ()
    separators, balanced = _top_level_commas(significant, template_angles=template_angles)
    if not balanced:
        raise ValueError("unbalanced C++ source list")
    encoded = source.encode("utf-8", errors="surrogateescape")
    result = []
    start = 0
    for item in separators:
        text = decode_source(encoded[start : item.start]).strip()
        if not text:
            raise ValueError("empty argument in C++ source list")
        result.append(text)
        start = item.end
    text = decode_source(encoded[start:]).strip()
    if not text:
        raise ValueError("empty argument in C++ source list")
    result.append(text)
    return tuple(result)


def identifier_occurrences(source: str) -> tuple[CppIdentifierOccurrence, ...]:
    """返回代码中的 identifier occurrence，忽略注释和预处理逻辑行。
    Return identifier occurrences outside comments and preprocessor logical lines.
    """
    lexemes, diagnostics = _Lexer(source).scan()
    if diagnostics:
        raise ValueError(diagnostics[0].message)
    return _identifier_occurrences_of(lexemes)


def _identifier_occurrences_of(
    lexemes: Sequence[_Lexeme],
) -> tuple[CppIdentifierOccurrence, ...]:
    """lexeme 序列中的 identifier occurrence，忽略注释和预处理逻辑行。
    The identifier occurrences of a lexeme sequence outside comments and preprocessor
    logical lines.
    """
    directives = _preprocessor_mask(lexemes)
    significant = [
        (index, item)
        for index, item in enumerate(lexemes)
        if not item.trivia and item.kind != "comment" and not directives[index]
    ]
    result = []
    for position, (_, item) in enumerate(significant):
        if item.kind != "identifier":
            continue
        previous = significant[position - 1][1].text if position else None
        following = significant[position + 1][1].text if position + 1 < len(significant) else None
        result.append(
            CppIdentifierOccurrence(
                item.text, SourceSpan(item.start, item.end), previous, following
            )
        )
    return tuple(result)


# XR_REGISTER 这类宏式调用可能不是正常 C++ call_expression，因此这里故意走
# 词法查询：跳过注释/预处理行，精确匹配 NAME 后紧跟的括号区间。
def find_invocations(
    tree: SyntaxTree,
    name: str,
    *,
    template_angles: bool = False,
    lexemes: Sequence[_Lexeme] | None = None,
) -> tuple[CppInvocationView, ...]:
    """在语法快照中查找指定 NAME(...) invocation。
    Find lexical NAME(...) invocations in one syntax-tree snapshot.

    Args:
        lexemes: tree 源码的 lexeme；没有时重新切分。
            The lexemes of the tree's source; the source is lexed again without them.
    """
    if lexemes is None:
        lexemes, _ = _Lexer(tree.render()).scan()
    significant = [
        (index, item)
        for index, item in enumerate(lexemes)
        if not item.trivia and item.kind != "comment"
    ]
    positions = {index: position for position, (index, _) in enumerate(significant)}
    directives = _preprocessor_mask(lexemes)
    encoded = tree.render_bytes()
    result = []
    for index, item in significant:
        if item.kind != "identifier" or item.text != name:
            continue
        if directives[index]:
            continue
        position = positions[index]
        if position + 1 >= len(significant):
            continue
        open_index, opening = significant[position + 1]
        if opening.text != "(":
            continue
        close_index = _matching_paren(lexemes, open_index)
        if close_index is None:
            continue
        closing = lexemes[close_index]
        inner = decode_source(encoded[opening.end : closing.start])
        arguments = (
            split_source_list(inner, template_angles=template_angles) if inner.strip() else ()
        )
        result.append(
            CppInvocationView(
                tree,
                name,
                SourceSpan(item.start, closing.end),
                arguments,
            )
        )
    return tuple(result)


def _matching_paren(lexemes: Sequence[_Lexeme], opening: int) -> int | None:
    """匹配词法 invocation 的外层圆括号。
    Match the outer parenthesis of a lexical invocation.
    """
    depth = 0
    for index in range(opening, len(lexemes)):
        item = lexemes[index]
        if item.trivia or item.kind == "comment":
            continue
        if item.text == "(":
            depth += 1
        elif item.text == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _top_level_commas(
    items: list[_Lexeme],
    *,
    template_angles: bool,
) -> tuple[list[_Lexeme], bool]:
    """返回顶层逗号以及列表分隔符是否平衡。
    Return top-level commas together with delimiter-balance state.
    """
    result = []
    # 四组 depth 分别跟踪 () [] {} <>；模板角括号只在调用者明确要求时启用，
    # 避免把普通比较运算符 < / > 错当成模板边界。
    round_depth = square_depth = brace_depth = angle_depth = 0
    for item in items:
        text = item.text
        if text == "(":
            round_depth += 1
        elif text == ")":
            round_depth = max(0, round_depth - 1)
        elif text == "[":
            square_depth += 1
        elif text == "]":
            square_depth = max(0, square_depth - 1)
        elif text == "{":
            brace_depth += 1
        elif text == "}":
            brace_depth = max(0, brace_depth - 1)
        elif template_angles and text == "<" and not (round_depth or square_depth or brace_depth):
            angle_depth += 1
        elif template_angles and text == ">" and angle_depth:
            angle_depth -= 1
        elif template_angles and text == ">>" and angle_depth:
            angle_depth = max(0, angle_depth - 2)
        elif text == "," and not (round_depth or square_depth or brace_depth or angle_depth):
            result.append(item)
    return result, not (round_depth or square_depth or brace_depth or angle_depth)
