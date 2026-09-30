"""xr-syntax 自有 C++ 词法器。
xr-syntax native C++ lexer. It produces lossless lexemes without performing C++ semantic analysis.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from xr_syntax.core import Diagnostic, GreenElement, SourceSpan
from xr_syntax.core.green import _token, _trivia

# C++ punctuator 采用最长匹配。模板中的 >> 在 parser 的角括号匹配阶段按两个 > 处理。
# Use longest-match C++ punctuators; template `>>` is split logically into two
# closing angles during parser bracket matching.
_PUNCTUATORS = tuple(
    sorted(
        {
            "%:%:",
            "<=>",
            ">>=",
            "<<=",
            "->*",
            "...",
            "::",
            ".*",
            "->",
            "++",
            "--",
            "<<",
            ">>",
            "<=",
            ">=",
            "==",
            "!=",
            "&&",
            "||",
            "+=",
            "-=",
            "*=",
            "/=",
            "%=",
            "&=",
            "|=",
            "^=",
            "##",
            "<:",
            ":>",
            "<%",
            "%>",
            "%:",
            "{",
            "}",
            "[",
            "]",
            "(",
            ")",
            ";",
            ":",
            "?",
            ".",
            ",",
            "~",
            "!",
            "+",
            "-",
            "*",
            "/",
            "%",
            "^",
            "&",
            "|",
            "=",
            "<",
            ">",
            "#",
        },
        key=len,
        reverse=True,
    )
)

# 一个 lexeme 一次正则匹配。分支顺序即优先级：换行、空白、注释、字符串前缀、标识符、数字、
# punctuator（最长优先），最后是任意单个字符。正则的 \s 与 str.isspace()、\w 与 isalnum() 或 _
# 对全部码位一致，标识符和数字的判断因此与逐字符扫描相同。
# One regular-expression match per lexeme. The branch order is the priority: line ending,
# whitespace, comments, string prefixes, identifiers, numbers, punctuators (longest first) and
# finally any single character. \s agrees with str.isspace() and \w with isalnum() or _ on every
# code point, so identifiers and numbers are recognized as a character-by-character scan would.
_LITERAL_PREFIXES = (
    'u8R"',
    'uR"',
    'UR"',
    'LR"',
    'R"',
    'u8"',
    'u"',
    'U"',
    'L"',
    '"',
    "u8'",
    "u'",
    "U'",
    "L'",
    "'",
)
_TOKEN = re.compile(
    r"(?P<newline>\r\n?|\n)"
    r"|(?P<whitespace>[^\S\r\n]+)"
    r"|(?P<line_comment>//[^\r\n]*)"
    r"|(?P<block_comment>/\*)"
    r"|(?P<literal>" + "|".join(re.escape(prefix) for prefix in _LITERAL_PREFIXES) + r")"
    r"|(?P<identifier>[A-Za-z_\x80-\U0010ffff](?:\w|[^\x00-\x7f])*)"
    r"|(?P<number>[0-9](?:[\w.']|(?<=[eEpP])[+-])*)"
    r"|(?P<punctuator>" + "|".join(re.escape(item) for item in _PUNCTUATORS) + r")"
    r"|(?P<raw>.)",
    re.DOTALL,
)
# 以 . 开头的数字（.5）在 punctuator 分支中识别：. 后的字符按 str.isdigit() 判断。
# A number that starts with . (.5) is recognized in the punctuator branch, where the character
# after the . is tested with str.isdigit().
_NUMBER_TAIL = re.compile(r"(?:[\w.']|(?<=[eEpP])[+-])*")
_IDENTIFIER_TAIL = re.compile(r"(?:\w|[^\x00-\x7f])*")
_ESCAPED_STRING = {
    '"': re.compile(r'(?:[^"\\]|\\.)*"', re.DOTALL),
    "'": re.compile(r"(?:[^'\\]|\\.)*'", re.DOTALL),
}
_WORD_LITERALS = {"true", "false", "nullptr"}

_STORAGE = {"static", "extern", "thread_local", "mutable", "register"}
_QUALIFIERS = {"const", "volatile", "restrict", "__restrict", "__restrict__"}
_CONTROL = {"if", "for", "while", "switch", "catch"}
_TYPE_WORDS = {
    "auto",
    "bool",
    "char",
    "char8_t",
    "char16_t",
    "char32_t",
    "double",
    "float",
    "int",
    "long",
    "short",
    "signed",
    "unsigned",
    "void",
    "wchar_t",
    "typename",
    "class",
    "struct",
    "enum",
}
_LITERAL_KINDS = {
    "number_literal",
    "string_literal",
    "char_literal",
    "raw_string_literal",
    "true",
    "false",
    "nullptr",
}

# Pratt parser 的二元运算符优先级；数值越小，绑定越弱。
# Pratt-parser binary precedence; smaller values bind more weakly.
_BINARY_PRECEDENCE = {
    "=": 1,
    "+=": 1,
    "-=": 1,
    "*=": 1,
    "/=": 1,
    "%=": 1,
    "&=": 1,
    "|=": 1,
    "^=": 1,
    "<<=": 1,
    ">>=": 1,
    "or": 2,
    "||": 2,
    "and": 3,
    "&&": 3,
    "|": 4,
    "xor": 5,
    "^": 5,
    "&": 6,
    "==": 7,
    "!=": 7,
    "<": 8,
    "<=": 8,
    ">": 8,
    ">=": 8,
    "<=>": 8,
    "<<": 9,
    ">>": 9,
    "+": 10,
    "-": 10,
    "*": 11,
    "/": 11,
    "%": 11,
}


class _Lexeme(NamedTuple):
    """保存一个不可再分的源码片段及其字节位置。
    Store one indivisible source fragment together with its byte positions.
    """

    kind: str
    text: str
    start: int
    end: int
    named: bool = False
    trivia: bool = False

    def green(self) -> GreenElement:
        """把词法项转换成 green token/trivia。
        Convert the lexical element into its green token/trivia representation.
        """
        if self.trivia:
            return _trivia(self.kind, self.text)
        return _token(self.kind, self.text, self.named)


class _Lexer:
    """纯 Python C++ lexer；对不认识的字符保守地生成 raw token。
    Pure-Python C++ lexer that conservatively emits raw tokens for unknown characters.
    """

    def __init__(self, text: str) -> None:
        """保存待扫描文本并初始化字节游标。
        Store the source text and initialize the byte cursor.
        """
        self.text = text
        self.length = len(text)
        self.byte_offset = 0
        self.diagnostics: list[Diagnostic] = []
        # 纯 ASCII 文本的字节位置等于字符位置，不必逐个片段编码。
        # In ASCII text byte positions equal character positions, so no fragment is encoded.
        self._ascii = text.isascii()
        self._result: list[_Lexeme] = []

    def scan(self) -> tuple[list[_Lexeme], list[Diagnostic]]:
        """扫描完整输入并返回 lossless lexeme 序列。
        Scan the complete input and return a lossless lexeme sequence.
        """
        text, length, emit = self.text, self.length, self._emit
        index = 0
        if text.startswith("﻿"):
            emit("raw", 0, 1, trivia=True)
            index = 1
        match = _TOKEN.match
        while index < length:
            found = match(text, index)
            # 最后一个分支匹配任何字符。
            # The last branch matches any character.
            assert found is not None
            branch = found.lastgroup
            end = found.end()
            if branch == "identifier":
                word = found.group()
                if word in _WORD_LITERALS:
                    emit(word, index, end, named=True)
                else:
                    emit("identifier", index, end, named=True)
            elif branch == "punctuator":
                if end - index == 1 and text[index] == "." and text[end : end + 1].isdigit():
                    end = _match_end(_NUMBER_TAIL, text, end)
                    emit("number_literal", index, end, named=True)
                else:
                    emit(found.group(), index, end)
            elif branch == "whitespace" or branch == "newline":
                emit(branch, index, end, trivia=True)
            elif branch == "line_comment":
                emit("comment", index, end, named=True)
            elif branch == "number":
                emit("number_literal", index, end, named=True)
            elif branch == "block_comment":
                close = text.find("*/", index + 2)
                end = length if close < 0 else close + 2
                emit("comment", index, end, named=True)
                if close < 0:
                    self._diagnostic("未闭合的块注释", self._result[-1].start, self._result[-1].end)
            elif branch == "literal":
                end = self._scan_literal(index, found.group())
            else:
                emit("raw", index, end, named=True)
            index = end
        return self._result, self.diagnostics

    def _scan_literal(self, start: int, prefix: str) -> int:
        """扫描以 prefix 开头的普通/宽字符/UTF/原始字符串或字符字面量，返回结束位置。
        Scan an ordinary, wide, UTF-prefixed or raw string or character literal that starts with
        prefix, and return where it ends.
        """
        text, length = self.text, self.length
        quote = prefix[-1]
        kind = "char_literal" if quote == "'" else "string_literal"
        index = start + len(prefix)
        if 'R"' in prefix:
            kind = "raw_string_literal"
            paren = text.find("(", index)
            if paren < 0 or paren - index > 16:
                self._emit(kind, start, length, named=True)
                self._diagnostic("非法或未闭合的 raw string delimiter", *self._last_span())
                return length
            close_text = ")" + text[index:paren] + '"'
            close = text.find(close_text, paren + 1)
            if close < 0:
                self._emit(kind, start, length, named=True)
                self._diagnostic("未闭合的 raw string", *self._last_span())
                return length
            index = close + len(close_text)
        else:
            closing = _ESCAPED_STRING[quote].match(text, index)
            if closing is None:
                self._emit(kind, start, length, named=True)
                self._diagnostic("未闭合的字符串或字符字面量", *self._last_span())
                return length
            index = closing.end()
        # 用户定义字面量的后缀属于同一个 token。
        # A user-defined literal suffix belongs to the same token.
        end = _match_end(_IDENTIFIER_TAIL, text, index)
        self._emit(kind, start, end, named=True)
        return end

    def _emit(
        self,
        kind: str,
        start: int,
        end: int,
        *,
        named: bool = False,
        trivia: bool = False,
    ) -> None:
        """记录带准确字节区间的 lexeme，并推进累计字节位置。
        Record a lexeme with an exact byte span and advance the cumulative byte offset.
        """
        fragment = self.text[start:end]
        if self._ascii or fragment.isascii():
            width = end - start
        else:
            width = len(fragment.encode("utf-8", errors="surrogateescape"))
        offset = self.byte_offset
        self._result.append(_Lexeme(kind, fragment, offset, offset + width, named, trivia))
        self.byte_offset = offset + width

    def _last_span(self) -> tuple[int, int]:
        """最后一个 lexeme 的字节区间。
        The byte span of the last lexeme.
        """
        last = self._result[-1]
        return last.start, last.end

    def _diagnostic(self, message: str, start: int, end: int) -> None:
        """记录 lexer 发现的源级错误。
        Record a source-level error the lexer found.
        """
        self.diagnostics.append(Diagnostic(message, SourceSpan(start, end)))


def _match_end(pattern: re.Pattern[str], text: str, start: int) -> int:
    """可以匹配空串的 pattern 从 start 起匹配到的结束位置。
    Where a pattern that also matches the empty string ends when matched at start.
    """
    match = pattern.match(text, start)
    assert match is not None  # 该模式能匹配空串 / the pattern matches the empty string
    return match.end()
