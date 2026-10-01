"""xr-syntax 自有 C++ 词法器。
xr-syntax native C++ lexer. It produces lossless lexemes without performing C++ semantic analysis.
"""

from __future__ import annotations

import re
from itertools import accumulate
from typing import NamedTuple

from xr_syntax.core import Diagnostic, GreenChild, GreenElement, SourceSpan
from xr_syntax.core.green import _child, _token, _trivia
from xr_syntax.i18n import tr

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
_PUNCTUATOR_SET = frozenset(_PUNCTUATORS)

# 整个文件只调用一次 Pattern.findall：匹配循环在正则引擎（C）里完成，Python 只处理结果列表。
# 分支顺序即优先级：换行、空白、注释、原始字符串前缀、字符串/字符字面量、标识符、数字、
# punctuator（最长优先），最后是任意单个字符。正则的 \s 与 str.isspace()、\w 与 isalnum() 或 _
# 对全部码位一致，标识符和数字的判断因此与逐字符扫描相同。未闭合的注释和字面量一直延伸到文件末尾。
# The whole file is matched with one Pattern.findall call: the matching loop runs in the regular
# expression engine (C) and Python only handles the resulting list. The branch order is the
# priority: line ending, whitespace, comments, raw string prefixes, string/character literals,
# identifiers, numbers, punctuators (longest first) and finally any single character. \s agrees
# with str.isspace() and \w with isalnum() or _ on every code point, so identifiers and numbers are
# recognized as a character-by-character scan would. Unclosed comments and literals run to the end
# of the file.
_IDENTIFIER_TAIL = r"(?:\w|[^\x00-\x7f])*"
_NUMBER_TAIL = r"(?:[\w.']|(?<=[eEpP])[+-])*"
_RAW_PREFIXES = frozenset({'u8R"', 'uR"', 'UR"', 'LR"', 'R"'})
_TOKEN = re.compile(
    r"\r\n?|\n"
    r"|[^\S\r\n]+"
    r"|//[^\r\n]*"
    r"|/\*.*?(?:\*/|\Z)"
    r'|(?:u8|u|U|L)?R"'
    r'|(?:u8|u|U|L)?"(?:(?:[^"\\]|\\.)*"' + _IDENTIFIER_TAIL + r"|.*)"
    r"|(?:u8|u|U|L)?'(?:(?:[^'\\]|\\.)*'" + _IDENTIFIER_TAIL + r"|.*)"
    r"|[A-Za-z_\x80-\U0010ffff]"
    + _IDENTIFIER_TAIL
    + r"|[0-9]"
    + _NUMBER_TAIL
    # 以 . 开头的数字（.5）。
    # A number that starts with . (.5).
    + r"|\.(?=\d)"
    + _NUMBER_TAIL
    + "|"
    + "|".join(re.escape(item) for item in _PUNCTUATORS)
    + r"|.",
    re.DOTALL,
)
_IDENTIFIER_TAIL_PATTERN = re.compile(_IDENTIFIER_TAIL)
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

# 每个 lexeme 的 (kind, named, trivia)。
# The (kind, named, trivia) of one lexeme.
_Info = tuple[str, bool, bool]
_NEWLINE: _Info = ("newline", False, True)
_WHITESPACE: _Info = ("whitespace", False, True)
_COMMENT: _Info = ("comment", True, False)
_STRING: _Info = ("string_literal", True, False)
_CHAR: _Info = ("char_literal", True, False)
_RAW_STRING: _Info = ("raw_string_literal", True, False)
_NUMBER: _Info = ("number_literal", True, False)
_IDENTIFIER: _Info = ("identifier", True, False)
_RAW: _Info = ("raw", True, False)
_BYTE_ORDER_MARK: _Info = ("raw", False, True)
_BY_FIRST_CHARACTER: dict[str, _Info] = {"\n": _NEWLINE, "\r": _NEWLINE}
for _character in " \t\f\v":
    _BY_FIRST_CHARACTER[_character] = _WHITESPACE
for _character in "0123456789":
    _BY_FIRST_CHARACTER[_character] = _NUMBER
_BY_FIRST_CHARACTER['"'] = _STRING
_BY_FIRST_CHARACTER["'"] = _CHAR
# 只缓存短文本，进程里出现过的长注释和长字符串不会一直留在内存里。
# Only short texts are cached, so long comments and strings seen by the process are not kept.
_CACHED_LENGTH = 64


def _classify(text: str) -> _Info:
    """按 findall 得到的 lexeme 文本判断 kind；同一文本总是同一 kind。
    Classify one lexeme text produced by findall; the same text always gets the same kind.
    """
    first = text[0]
    known = _BY_FIRST_CHARACTER.get(first)
    if known is not None:
        return known
    if first == "/" and text[1:2] in ("/", "*"):
        return _COMMENT
    if first == "_" or first.isalpha() or first > "\x7f":
        if first.isspace():
            return _WHITESPACE
        if first in "uUL":
            # u8"..."、L'x' 这类带前缀的字面量；标识符里不会有引号。
            # Prefixed literals such as u8"..." and L'x'; identifiers contain no quotes.
            for character in text:
                if character == '"':
                    return _STRING
                if character == "'":
                    return _CHAR
        if text in _WORD_LITERALS:
            return (text, True, False)
        return _IDENTIFIER
    if first == "." and text[1:2].isdigit():
        return _NUMBER
    if text in _PUNCTUATOR_SET:
        return (text, False, False)
    if first.isspace():
        return _WHITESPACE
    return _RAW


class _Infos(dict[str, _Info]):
    """按文本缓存 lexeme 的 (kind, named, trivia)；未见过的文本才执行 Python 分类。
    Cache the (kind, named, trivia) of lexeme texts; only unseen texts run the Python classifier.
    """

    def __missing__(self, text: str) -> _Info:
        """分类一个新文本，短文本留在缓存里。
        Classify a new text and keep it in the cache when it is short.
        """
        info = _classify(text)
        if len(text) <= _CACHED_LENGTH:
            self[text] = info
        return info


class _PlainEdges(dict[str, GreenChild]):
    """按文本缓存 lexeme 的 green 叶子及其无 field 的边；green 元素不可变且不含位置，可以共享。
    Cache the green leaf of a lexeme text together with its edge without a field; green elements
    are immutable and position-free, so they can be shared.
    """

    def __missing__(self, text: str) -> GreenChild:
        """为一个新文本创建叶子和边，短文本留在缓存里。
        Create the leaf and edge for a new text and keep them when the text is short.
        """
        edge = _child(_leaf(text, _INFOS[text]))
        if len(text) <= _CACHED_LENGTH:
            self[text] = edge
        return edge


class _Significance(dict[str, bool]):
    """按文本缓存 lexeme 是否有效（既不是空白也不是注释）。
    Cache whether a lexeme text is significant (neither whitespace nor a comment).
    """

    def __missing__(self, text: str) -> bool:
        """判断一个新文本，短文本留在缓存里。
        Decide for a new text and keep it in the cache when it is short.
        """
        kind, _, trivia = _INFOS[text]
        significant = not trivia and kind != "comment"
        if len(text) <= _CACHED_LENGTH:
            self[text] = significant
        return significant


_INFOS = _Infos()
_PLAIN_EDGES = _PlainEdges()
_SIGNIFICANCE = _Significance()


def _leaf(text: str, info: _Info) -> GreenElement:
    """由文本和 (kind, named, trivia) 构造 green token 或 trivia。
    Build the green token or trivia for a text and its (kind, named, trivia).
    """
    kind, named, trivia = info
    return _trivia(kind, text) if trivia else _token(kind, text, named)


def _byte_width(text: str) -> int:
    """文本按源码编码后的字节数。
    The number of bytes the text takes in the source encoding.
    """
    return len(text) if text.isascii() else len(text.encode("utf-8", errors="surrogateescape"))


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


class _Lexed:
    """一次词法扫描的结果：按 lexeme 顺序排列的并列数组，外加词法诊断。
    The result of one lexing pass: parallel arrays in lexeme order plus the lexer diagnostics.

    Attributes:
        texts: 每个 lexeme 的源码文本。
            The source text of each lexeme.
        infos: 每个 lexeme 的 (kind, named, trivia)。
            The (kind, named, trivia) of each lexeme.
        offsets: 每个 lexeme 起点的字节位置，最后一项是源码总字节数。
            The byte position where each lexeme starts; the last item is the source size in bytes.
        special: 不能由文本推出 kind 的 lexeme（BOM、原始字符串）的下标。
            Indices of lexemes whose kind does not follow from the text (BOM, raw strings).
        diagnostics: 未闭合的注释、字面量或原始字符串。
            Unclosed comments, literals or raw strings.
    """

    __slots__ = ("diagnostics", "infos", "offsets", "special", "texts", "_lexemes")

    def __init__(
        self,
        texts: list[str],
        infos: list[_Info],
        offsets: list[int],
        special: list[int],
        diagnostics: list[Diagnostic],
    ) -> None:
        """保存扫描结果。
        Store the lexing result.
        """
        self.texts = texts
        self.infos = infos
        self.offsets = offsets
        self.special = special
        self.diagnostics = diagnostics
        self._lexemes: list[_Lexeme] | None = None

    def plain_children(self) -> list[GreenChild]:
        """每个 lexeme 的 green 叶子边（无 field）；相同文本共享同一个对象。
        The green leaf edge (without a field) of every lexeme; equal texts share one object.
        """
        plain = list(map(_PLAIN_EDGES.__getitem__, self.texts))
        for index in self.special:
            plain[index] = _child(_leaf(self.texts[index], self.infos[index]))
        return plain

    def significance(self) -> list[bool]:
        """每个 lexeme 是否有效（既不是空白也不是注释）。
        Whether each lexeme is significant (neither whitespace nor a comment).
        """
        significant = list(map(_SIGNIFICANCE.__getitem__, self.texts))
        for index in self.special:
            kind, _, trivia = self.infos[index]
            significant[index] = not trivia and kind != "comment"
        return significant

    def lexemes(self) -> list[_Lexeme]:
        """逐个 lexeme 的对象形式，首次使用时创建。
        The lexemes as objects, created on first use.
        """
        if self._lexemes is None:
            offsets = self.offsets
            self._lexemes = [
                _Lexeme(info[0], text, offsets[index], offsets[index + 1], info[1], info[2])
                for index, (text, info) in enumerate(zip(self.texts, self.infos, strict=True))
            ]
        return self._lexemes


def lex(text: str) -> _Lexed:
    """把源码切成无损 lexeme 序列；对不认识的字符保守地生成 raw lexeme。
    Split source text into a lossless lexeme sequence; unknown characters become raw lexemes.
    """
    texts: list[str]
    special: list[int] = []
    messages: list[str] = []
    if text.startswith("﻿"):
        texts = ["﻿", *_TOKEN.findall(text, 1)]
        special.append(0)
    else:
        texts = _TOKEN.findall(text)
    if 'R"' in text:
        texts = _with_raw_strings(text, texts, special, messages)
    infos = list(map(_INFOS.__getitem__, texts))
    for index in special:
        infos[index] = _BYTE_ORDER_MARK if index == 0 and texts[0] == "﻿" else _RAW_STRING
    widths = map(len, texts) if text.isascii() else map(_byte_width, texts)
    offsets = list(accumulate(widths, initial=0))
    if not messages and texts:
        message = _unclosed(texts[-1], infos[-1])
        if message is not None:
            messages.append(message)
    diagnostics = [
        Diagnostic(message, SourceSpan(offsets[-2], offsets[-1])) for message in messages
    ]
    return _Lexed(texts, infos, offsets, special, diagnostics)


def _with_raw_strings(
    text: str, texts: list[str], special: list[int], messages: list[str]
) -> list[str]:
    """把 findall 切出的原始字符串前缀（R"、u8R" 等）展开成完整的原始字符串 lexeme。
    Expand the raw string prefixes (R", u8R" and so on) that findall produced into complete raw
    string lexemes.

    原始字符串的结束符取决于分隔符，正则无法在不分组的前提下表达，所以从前缀处在 Python 里扫描
    到结束符，然后对剩余源码重新 findall。
    A raw string ends at a delimiter-dependent sequence that the group-free pattern cannot express,
    so the literal is scanned in Python from its prefix and the rest of the source is matched again.
    """
    result: list[str] = []
    position = 0
    while True:
        # list.index 在 C 里查找；源码里出现 R" 不一定是原始字符串（也可能在字符串或注释里）。
        # list.index searches in C; an R" in the source is not necessarily a raw string (it may sit
        # inside a string or a comment).
        found = [texts.index(prefix) for prefix in _RAW_PREFIXES if prefix in texts]
        if not found:
            result += texts
            return result
        index = min(found)
        result += texts[:index]
        position += sum(map(len, texts[:index]))
        start = position
        end, message = _raw_string_end(text, start, texts[index])
        special.append(len(result))
        result.append(text[start:end])
        if message is not None:
            messages.append(message)
            return result
        position = end
        texts = _TOKEN.findall(text, end)


def _raw_string_end(text: str, start: int, prefix: str) -> tuple[int, str | None]:
    """原始字符串的结束位置；分隔符无效或未闭合时到源码末尾，并给出诊断消息。
    Where a raw string ends; with an invalid or unclosed delimiter it runs to the end of the source
    and a diagnostic message is returned.
    """
    length = len(text)
    index = start + len(prefix)
    paren = text.find("(", index)
    if paren < 0 or paren - index > 16:
        return length, tr(
            "invalid or unclosed raw string delimiter", "原始字符串的分隔符无效或未闭合"
        )
    close_text = ")" + text[index:paren] + '"'
    close = text.find(close_text, paren + 1)
    if close < 0:
        return length, tr("unclosed raw string", "未闭合的原始字符串")
    # 用户定义字面量的后缀属于同一个 token。
    # A user-defined literal suffix belongs to the same token.
    match = _IDENTIFIER_TAIL_PATTERN.match(text, close + len(close_text))
    assert match is not None  # 该模式能匹配空串 / the pattern matches the empty string
    return match.end(), None


def _unclosed(last: str, info: _Info) -> str | None:
    """最后一个 lexeme 是未闭合的块注释或字面量时返回诊断消息；未闭合的只可能是最后一个。
    The diagnostic message when the last lexeme is an unclosed block comment or literal; only the
    last lexeme can be unclosed.
    """
    kind = info[0]
    if kind == "comment":
        if last.startswith("/*") and not (len(last) >= 4 and last.endswith("*/")):
            return tr("unclosed block comment", "未闭合的块注释")
        return None
    if kind in ("string_literal", "char_literal"):
        quote = '"' if kind == "string_literal" else "'"
        if _ESCAPED_STRING[quote].match(last, last.index(quote) + 1) is None:
            return tr("unclosed string or character literal", "未闭合的字符串或字符字面量")
    return None
