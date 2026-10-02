"""提供带字符/字节位置的公共 C++ 词法 token 查询。
Public C++ lexical-token queries with explicit character and byte positions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate

from xr_syntax.core import SourceSpan
from xr_syntax.cpp._lexical_support import preprocessor_mask
from xr_syntax.cpp.lexer import LITERAL_KINDS, Lexed, lex
from xr_syntax.i18n import tr


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
    lexed = lex(source)
    if lexed.diagnostics:
        raise ValueError(lexed.diagnostics[0].message)
    return code_tokens_of(lexed)


def code_tokens_of(lexed: Lexed) -> tuple[CppLexicalToken, ...]:
    """由词法结果得到代码 token；字符位置由各 lexeme 的文本长度累加得出。
    The code tokens of a lexing result; character positions add up the lexemes' text lengths.
    """
    directives = preprocessor_mask(lexed)
    texts = lexed.texts
    offsets = lexed.offsets
    characters = list(accumulate(map(len, texts), initial=0))
    return tuple(
        CppLexicalToken(
            text,
            characters[index],
            characters[index + 1],
            _public_kind(info[0]),
            SourceSpan(offsets[index], offsets[index + 1]),
        )
        for index, (text, info, directive) in enumerate(
            zip(texts, lexed.infos, directives, strict=True)
        )
        if not (info[2] or directive or info[0] == "comment")
    )


def matching_delimiter(tokens: Sequence[CppLexicalToken], start: int) -> int:
    """返回 opening token 对应的 closing token 索引。
    Return the token index matching the opening delimiter at start.
    """
    # 普通分隔符直接入栈；模板上下文还要处理 >> 一次关闭两层尖括号。
    # Ordinary delimiters are pushed as they come; in a template context >> closes two
    # angle brackets at once.
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
    if kind in LITERAL_KINDS:
        return "literal"
    return "punct"
