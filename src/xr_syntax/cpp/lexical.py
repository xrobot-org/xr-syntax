"""提供带字符/字节位置的公共 C++ 词法 token 查询。
Public C++ lexical-token queries with explicit character and byte positions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from xr_syntax.core import SourceSpan
from xr_syntax.i18n import tr

from ._lexical_support import _preprocessor_mask
from .lexer import _LITERAL_KINDS, _Lexeme, _Lexer

# ---------------------------------------------------------------------------
# 模块实现：提供带字符/字节位置的公共 C++ 词法 token 查询。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CppLexicalToken:
    """保存公共词法 token；start/end 为字符位置，span 为字节位置。
    Public lexical token whose start/end are character offsets and span is byte-based.
    """

    text: str
    start: int
    end: int
    kind: str
    span: SourceSpan


def code_tokens(source: str) -> tuple[CppLexicalToken, ...]:
    """返回实际 C++ 代码 token，跳过 trivia、注释和预处理逻辑行。
    Return C++ code tokens while excluding trivia, comments, and preprocessor logical lines.
    """
    lexemes, diagnostics = _Lexer(source).scan()
    if diagnostics:
        raise ValueError(diagnostics[0].message)
    return _code_tokens_of(lexemes)


def _code_tokens_of(lexemes: Sequence[_Lexeme]) -> tuple[CppLexicalToken, ...]:
    """由 lexeme 序列得到代码 token；字符位置由各 lexeme 的文本长度累加得出。
    The code tokens of a lexeme sequence; character positions add up the lexemes' text
    lengths.
    """
    directives = _preprocessor_mask(lexemes)
    result = []
    char_offset = 0
    for item, directive in zip(lexemes, directives, strict=True):
        start = char_offset
        char_offset += len(item.text)
        if item.trivia or directive or item.kind == "comment":
            continue
        result.append(
            CppLexicalToken(
                item.text,
                start,
                char_offset,
                _public_kind(item.kind),
                SourceSpan(item.start, item.end),
            )
        )
    return tuple(result)


def matching_delimiter(tokens: Sequence[CppLexicalToken], start: int) -> int:
    """返回 opening token 对应的 closing token 索引。
    Return the token index matching the opening delimiter at start.
    """
    # 普通分隔符直接入栈；模板上下文还要处理 >> 一次关闭两层尖括号。
    pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
    expected = pairs.get(tokens[start].text)
    if expected is None:
        raise ValueError(tr("expected an opening delimiter", "这里应当是左括号"))
    stack = [expected]
    for index in range(start + 1, len(tokens)):
        token = tokens[index]
        text = token.text
        if token.kind == "literal":
            continue
        if text in ("(", "[", "{"):
            stack.append(pairs[text])
        elif text == "<" and stack[-1] == ">":
            stack.append(">")
        elif text == ">>" and stack[-1] == ">":
            for _ in range(2):
                if stack and stack[-1] == ">":
                    stack.pop()
                    if not stack:
                        return index
        elif text == stack[-1]:
            stack.pop()
            if not stack:
                return index
    raise ValueError(
        tr(
            f"unclosed delimiter at offset {tokens[start].start}",
            f"位置 {tokens[start].start} 处的括号没有闭合",
        )
    )


def _public_kind(kind: str) -> str:
    """把内部 lexer kind 映射为稳定的公共词法分类。
    Map internal lexer kinds onto stable public lexical categories.
    """
    if kind == "identifier" or kind in {"true", "false", "nullptr"}:
        return "identifier"
    if kind == "number_literal":
        return "number"
    if kind in _LITERAL_KINDS:
        return "literal"
    return "punct"
