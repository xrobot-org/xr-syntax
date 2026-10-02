"""提供宏式 NAME(...) invocation 的词法查询和逗号列表切分。
Lexical queries for macro-like NAME(...) invocations and comma-delimited source lists.
"""

from __future__ import annotations

from dataclasses import dataclass

from xr_syntax.core import SourceSpan, SyntaxTree, decode_source
from xr_syntax.cpp._lexical_support import preprocessor_mask
from xr_syntax.cpp.lexer import Lexed, Lexeme, lex
from xr_syntax.i18n import tr


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


# 宏参数和模板参数的逗号不能用 str.split(',')：只有所有括号/方括号/花括号
# （以及可选模板尖括号）depth 都为 0 时，逗号才是当前列表的分隔符。
# Commas of macro and template arguments cannot be split with str.split(','): a
# comma separates the list only where the parenthesis, bracket and brace depths (and
# optionally the template-angle depth) are all 0.
def split_source_list(source: str, *, template_angles: bool = False) -> tuple[str, ...]:
    """按顶层逗号切分源码列表，并按需把模板角括号视为嵌套。
    Split source on top-level commas, optionally treating template angles as nesting.
    """
    lexed = lex(source)
    if lexed.diagnostics:
        raise ValueError(lexed.diagnostics[0].message)
    significant = [item for item in lexed.lexemes() if not item.trivia and item.kind != "comment"]
    if not significant:
        return ()
    separators, balanced = _top_level_commas(significant, template_angles=template_angles)
    if not balanced:
        raise ValueError(tr("unbalanced C++ source list", "C++ 列表的括号不配对"))
    encoded = source.encode("utf-8", errors="surrogateescape")
    result = []
    start = 0
    for item in separators:
        text = decode_source(encoded[start : item.start]).strip()
        if not text:
            raise ValueError(tr("empty argument in C++ source list", "C++ 列表中有空的一项"))
        result.append(text)
        start = item.end
    text = decode_source(encoded[start:]).strip()
    if not text:
        raise ValueError(tr("empty argument in C++ source list", "C++ 列表中有空的一项"))
    result.append(text)
    return tuple(result)


def identifier_occurrences(source: str) -> tuple[CppIdentifierOccurrence, ...]:
    """返回代码中的 identifier occurrence，忽略注释和预处理逻辑行。
    Return identifier occurrences outside comments and preprocessor logical lines.
    """
    lexed = lex(source)
    if lexed.diagnostics:
        raise ValueError(lexed.diagnostics[0].message)
    return identifier_occurrences_of(lexed)


def identifier_occurrences_of(lexed: Lexed) -> tuple[CppIdentifierOccurrence, ...]:
    """词法结果中的 identifier occurrence，忽略注释和预处理逻辑行。
    The identifier occurrences of a lexing result outside comments and preprocessor logical
    lines.
    """
    directives = preprocessor_mask(lexed)
    texts = lexed.texts
    infos = lexed.infos
    offsets = lexed.offsets
    significant = [
        index
        for index, (info, directive) in enumerate(zip(infos, directives, strict=True))
        if not (info[2] or directive or info[0] == "comment")
    ]
    last = len(significant) - 1
    result = []
    for position, index in enumerate(significant):
        if infos[index][0] != "identifier":
            continue
        previous = texts[significant[position - 1]] if position else None
        following = texts[significant[position + 1]] if position < last else None
        result.append(
            CppIdentifierOccurrence(
                texts[index], SourceSpan(offsets[index], offsets[index + 1]), previous, following
            )
        )
    return tuple(result)


# XR_REGISTER 这类宏式调用可能不是正常 C++ call_expression，因此这里故意走
# 词法查询：跳过注释/预处理行，精确匹配 NAME 后紧跟的括号区间。
# Macro-style calls such as XR_REGISTER need not be ordinary C++ call expressions, so
# this is a lexical query: it skips comments and preprocessor lines and matches the
# parenthesized range right after NAME.
def find_invocations(
    tree: SyntaxTree,
    name: str,
    *,
    template_angles: bool = False,
    lexed: Lexed | None = None,
) -> tuple[CppInvocationView, ...]:
    """在语法快照中查找指定 NAME(...) invocation。
    Find lexical NAME(...) invocations in one syntax-tree snapshot.

    Args:
        lexed: tree 源码的词法结果；没有时重新切分。
            The lexing result of the tree's source; the source is lexed again without it.
    """
    if lexed is None:
        lexed = lex(tree.render())
    texts = lexed.texts
    if name not in texts:
        return ()
    infos = lexed.infos
    offsets = lexed.offsets
    directives = preprocessor_mask(lexed)
    encoded = tree.render_bytes()
    result = []
    for index, text in enumerate(texts):
        if text != name or infos[index][0] != "identifier" or directives[index]:
            continue
        open_index = _next_code(lexed, index + 1)
        if open_index is None or texts[open_index] != "(":
            continue
        close_index = _matching_paren(lexed, open_index)
        if close_index is None:
            continue
        inner = decode_source(encoded[offsets[open_index + 1] : offsets[close_index]])
        arguments = (
            split_source_list(inner, template_angles=template_angles) if inner.strip() else ()
        )
        result.append(
            CppInvocationView(
                tree,
                name,
                SourceSpan(offsets[index], offsets[close_index + 1]),
                arguments,
            )
        )
    return tuple(result)


def _next_code(lexed: Lexed, start: int) -> int | None:
    """从 start 起第一个不是空白、也不是注释的 lexeme。
    The first lexeme from start on that is neither whitespace nor a comment.
    """
    infos = lexed.infos
    for index in range(start, len(infos)):
        info = infos[index]
        if not info[2] and info[0] != "comment":
            return index
    return None


def _matching_paren(lexed: Lexed, opening: int) -> int | None:
    """匹配词法 invocation 的外层圆括号。
    Match the outer parenthesis of a lexical invocation.
    """
    texts = lexed.texts
    depth = 0
    for index in range(opening, len(texts)):
        text = texts[index]
        if text == "(":
            depth += 1
        elif text == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _top_level_commas(
    items: list[Lexeme],
    *,
    template_angles: bool,
) -> tuple[list[Lexeme], bool]:
    """返回顶层逗号以及列表分隔符是否平衡。
    Return top-level commas together with delimiter-balance state.
    """
    result = []
    # 四组 depth 分别跟踪 () [] {} <>；模板角括号只在调用者明确要求时启用，
    # 避免把普通比较运算符 < / > 错当成模板边界；括号内的 < 和 > 不计。
    # The four depths track () [] {} <>; template angles count only when the caller
    # asks for them, so plain comparisons < and > are not taken for template bounds; < and >
    # inside brackets do not count.
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
        elif round_depth or square_depth or brace_depth:
            continue
        elif template_angles and text == "<":
            angle_depth += 1
        elif template_angles and text in (">", ">>") and angle_depth:
            angle_depth = max(0, angle_depth - len(text))
        elif text == "," and not angle_depth:
            result.append(item)
    return result, not (round_depth or square_depth or brace_depth or angle_depth)
