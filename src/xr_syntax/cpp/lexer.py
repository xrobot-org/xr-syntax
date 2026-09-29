"""xr-syntax 自有 C++ 词法器。
xr-syntax native C++ lexer. It produces lossless lexemes without performing C++ semantic analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from xr_syntax.core import Diagnostic, GreenElement, GreenToken, GreenTrivia, SourceSpan

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

# 按首字符分组的 punctuator（组内仍为最长优先），避免逐个尝试全部 punctuator。
# Punctuators grouped by first character (still longest first within a group) so
# the scanner does not try every punctuator at each position.
_PUNCTUATORS_BY_FIRST: dict[str, tuple[str, ...]] = {}
for _punctuator in _PUNCTUATORS:
    _PUNCTUATORS_BY_FIRST[_punctuator[0]] = _PUNCTUATORS_BY_FIRST.get(_punctuator[0], ()) + (
        _punctuator,
    )

# 与 _identifier_continue 等价：ASCII 字母数字、下划线或任意非 ASCII 字符。
# Equivalent to _identifier_continue: ASCII alphanumerics, underscore or any non-ASCII.
_IDENTIFIER_TAIL = re.compile(r"(?:\w|[^\x00-\x7f])*")

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


@dataclass(frozen=True)
class _Lexeme:
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
            return GreenTrivia(self.kind, self.text)
        return GreenToken(self.kind, self.text, named=self.named)


class _Lexer:
    """纯 Python C++ lexer；对不认识的字符保守地生成 raw token。
    Pure-Python C++ lexer that conservatively emits raw tokens for unknown characters.
    """

    def __init__(self, text: str) -> None:
        """保存待扫描文本并初始化字符/字节游标。
        Store the source text and initialize character and byte cursors.
        """
        self.text = text
        self.length = len(text)
        self.index = 0
        self.byte_offset = 0
        self.diagnostics: list[Diagnostic] = []

    def scan(self) -> tuple[list[_Lexeme], list[Diagnostic]]:
        """扫描完整输入并返回 lossless lexeme 序列。
        Scan the complete input and return a lossless lexeme sequence.
        """
        result: list[_Lexeme] = []
        while self.index < self.length:
            start = self.index
            char = self.text[self.index]

            if start == 0 and char == "\ufeff":
                self.index += 1
                result.append(self._emit("raw", start, self.index, trivia=True))
                continue

            if char in "\r\n":
                # 行结束必须独立成 lexeme。预处理指令需要拥有“本行”的换行，
                # 但不能把下一空行一起吞掉；CRLF 作为一个逻辑换行整体保留。
                # Keep each line ending as its own lexeme so a preprocessor directive owns only
                # its own newline. Preserve CRLF as one logical line ending without consuming
                # the following blank line.
                if (
                    char == "\r"
                    and self.index + 1 < self.length
                    and self.text[self.index + 1] == "\n"
                ):
                    self.index += 2
                else:
                    self.index += 1
                result.append(self._emit("newline", start, self.index, trivia=True))
                continue

            if char.isspace():
                self.index += 1
                while (
                    self.index < self.length
                    and self.text[self.index].isspace()
                    and self.text[self.index] not in "\r\n"
                ):
                    self.index += 1
                result.append(self._emit("whitespace", start, self.index, trivia=True))
                continue

            if self.text.startswith("//", start):
                self.index += 2
                while self.index < self.length and self.text[self.index] not in "\r\n":
                    self.index += 1
                result.append(self._emit("comment", start, self.index, named=True))
                continue

            if self.text.startswith("/*", start):
                close = self.text.find("*/", start + 2)
                if close < 0:
                    self.index = self.length
                    result.append(self._emit("comment", start, self.index, named=True))
                    self._diagnostic("未闭合的块注释", result[-1].start, result[-1].end)
                else:
                    self.index = close + 2
                    result.append(self._emit("comment", start, self.index, named=True))
                continue

            literal = self._scan_string_or_char(start)
            if literal is not None:
                result.append(literal)
                continue

            if _identifier_start(char):
                # 该模式可以匹配空串，因此总能匹配成功。
                # The pattern also matches the empty string, so it always matches.
                tail = _IDENTIFIER_TAIL.match(self.text, self.index + 1)
                assert tail is not None
                self.index = tail.end()
                word = self.text[start : self.index]
                if word in {"true", "false", "nullptr"}:
                    result.append(self._emit(word, start, self.index, named=True))
                else:
                    result.append(self._emit("identifier", start, self.index, named=True))
                continue

            if char.isdigit() or (
                char == "." and self.index + 1 < self.length and self.text[self.index + 1].isdigit()
            ):
                result.append(self._scan_number(start))
                continue

            punctuator = next(
                (
                    item
                    for item in _PUNCTUATORS_BY_FIRST.get(char, ())
                    if self.text.startswith(item, start)
                ),
                None,
            )
            if punctuator is not None:
                self.index += len(punctuator)
                result.append(self._emit(punctuator, start, self.index))
                continue

            self.index += 1
            result.append(self._emit("raw", start, self.index, named=True))

        return result, self.diagnostics

    def _scan_string_or_char(self, start: int) -> _Lexeme | None:
        """识别普通/宽字符/UTF/原始字符串字面量。
        Recognize ordinary, wide, UTF-prefixed, and raw string/character literals.
        """
        if self.text[start] not in "uULR\"'":
            return None
        prefixes = (
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
        prefix = next((item for item in prefixes if self.text.startswith(item, start)), None)
        if prefix is None:
            return None

        raw = 'R"' in prefix
        quote = "'" if prefix.endswith("'") else '"'
        self.index = start + len(prefix)
        kind = "char_literal" if quote == "'" else "string_literal"

        if raw:
            kind = "raw_string_literal"
            delimiter_start = self.index
            paren = self.text.find("(", delimiter_start)
            if paren < 0 or paren - delimiter_start > 16:
                self.index = self.length
                token = self._emit(kind, start, self.index, named=True)
                self._diagnostic("非法或未闭合的 raw string delimiter", token.start, token.end)
                return token
            delimiter = self.text[delimiter_start:paren]
            close_text = ")" + delimiter + '"'
            close = self.text.find(close_text, paren + 1)
            if close < 0:
                self.index = self.length
                token = self._emit(kind, start, self.index, named=True)
                self._diagnostic("未闭合的 raw string", token.start, token.end)
                return token
            self.index = close + len(close_text)
        else:
            escaped = False
            while self.index < self.length:
                current = self.text[self.index]
                self.index += 1
                if escaped:
                    escaped = False
                    continue
                if current == "\\":
                    escaped = True
                    continue
                if current == quote:
                    break
            else:
                token = self._emit(kind, start, self.index, named=True)
                self._diagnostic("未闭合的字符串或字符字面量", token.start, token.end)
                return token

        while self.index < self.length and _identifier_continue(self.text[self.index]):
            self.index += 1
        return self._emit(kind, start, self.index, named=True)

    def _scan_number(self, start: int) -> _Lexeme:
        """扫描 C++ 数字字面量；后缀保持在同一 token 中。
        Scan a C++ numeric literal while keeping its suffix in the same token.
        """
        self.index += 1
        previous = self.text[start]
        while self.index < self.length:
            current = self.text[self.index]
            if current.isalnum() or current in "._'":
                self.index += 1
                previous = current
                continue
            if current in "+-" and previous in "eEpP":
                self.index += 1
                previous = current
                continue
            break
        return self._emit("number_literal", start, self.index, named=True)

    def _emit(
        self,
        kind: str,
        start: int,
        end: int,
        *,
        named: bool = False,
        trivia: bool = False,
    ) -> _Lexeme:
        """生成带准确字节区间的 lexeme，并推进累计字节位置。
        Create a lexeme with an exact byte span and advance the cumulative byte offset.
        """
        fragment = self.text[start:end]
        encoded = fragment.encode("utf-8", errors="surrogateescape")
        item = _Lexeme(
            kind, fragment, self.byte_offset, self.byte_offset + len(encoded), named, trivia
        )
        self.byte_offset += len(encoded)
        return item

    def _diagnostic(self, message: str, start: int, end: int) -> None:
        """记录 lexer 发现的源级错误。
        Record a parser diagnostic for the current lexeme byte range.
        """
        self.diagnostics.append(Diagnostic(message, SourceSpan(start, end)))


def _identifier_start(char: str) -> bool:
    """判断字符是否可作为保守 C++ identifier 起始字符。
    Return whether a character can conservatively start a C++ identifier.
    """
    return char == "_" or char.isalpha() or ord(char) >= 128


def _identifier_continue(char: str) -> bool:
    """判断字符是否可继续出现在保守 C++ identifier 中。
    Return whether a character can conservatively continue a C++ identifier.
    """
    return char == "_" or char.isalnum() or ord(char) >= 128
