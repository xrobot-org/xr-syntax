"""提供带字符/字节位置的公共 C++ 词法 token 查询。
Public C++ lexical-token queries with explicit character and byte positions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from xr_syntax.core import SourceSpan

from ._lexical_support import _inside_preprocessor
from .lexer import _LITERAL_KINDS, _Lexer

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


# Lexer 内部 span 使用 UTF-8 byte offset；公共 API 同时暴露 Python 字符下标，
# 因此这里建立 byte->char 映射，而不是假设非 ASCII 字符宽度为 1 byte。
def code_tokens(source: str) -> tuple[CppLexicalToken, ...]:
    """返回实际 C++ 代码 token，跳过 trivia、注释和预处理逻辑行。
    Return C++ code tokens while excluding trivia, comments, and preprocessor logical lines.
    """
    lexemes, diagnostics = _Lexer(source).scan()
    if diagnostics:
        raise ValueError(diagnostics[0].message)
    byte_to_char = _byte_to_char_offsets(source)
    result = []
    for index, item in enumerate(lexemes):
        if item.trivia or item.kind == "comment" or _inside_preprocessor(lexemes, index):
            continue
        result.append(
            CppLexicalToken(
                item.text,
                byte_to_char[item.start],
                byte_to_char[item.end],
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
        raise ValueError("Expected opening delimiter")
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
    raise ValueError(f"Unclosed delimiter at offset {tokens[start].start}")


def _byte_to_char_offsets(source: str) -> dict[int, int]:
    """建立 token 边界使用的 byte offset 到字符 offset 映射。
    Build the byte-to-character offset map used at lexical-token boundaries.
    """
    result = {0: 0}
    byte_offset = 0
    for char_offset, char in enumerate(source, 1):
        byte_offset += len(char.encode("utf-8", errors="surrogateescape"))
        result[byte_offset] = char_offset
    return result


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
