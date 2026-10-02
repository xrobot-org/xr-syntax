"""xr-syntax 自有 C++ 词法器。
xr-syntax native C++ lexer. It produces lossless lexemes without performing C++ semantic analysis.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from itertools import accumulate
from typing import NamedTuple

from xr_syntax.core import Diagnostic, GreenChild, GreenElement, SourcePoint, SourceSpan
from xr_syntax.core.green import _child, _token, _trivia
from xr_syntax.i18n import tr

# C++ punctuator 采用最长匹配；同时关闭模板实参列表和 template 参数列表的 >> 随后拆成两个 >。
# C++ punctuators use the longest match; a >> that closes both a template argument list and a
# template parameter list is split into two > afterwards.
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
# 对全部码位一致，标识符和数字的判断因此与逐字符扫描相同。未闭合的块注释延伸到文件末尾；
# 未闭合的引号只到行尾，#error 和 #if 0 中不成对的撇号因此不会吞掉后面的代码。
# The whole file is matched with one Pattern.findall call: the matching loop runs in the regular
# expression engine (C) and Python only handles the resulting list. The branch order is the
# priority: line ending, whitespace, comments, raw string prefixes, string/character literals,
# identifiers, numbers, punctuators (longest first) and finally any single character. \s agrees
# with str.isspace() and \w with isalnum() or _ on every code point, so identifiers and numbers are
# recognized as a character-by-character scan would. An unclosed block comment runs to the end of
# the file; an unclosed quote only to the end of its line, so an unpaired apostrophe in #error or
# #if 0 does not take in the code after it.
_IDENTIFIER_TAIL = r"(?:\w|[^\x00-\x7f])*"
_NUMBER_TAIL = r"(?:[\w.']|(?<=[eEpP])[+-])*"
_RAW_PREFIXES = frozenset({'u8R"', 'uR"', 'UR"', 'LR"', 'R"'})
# <: 是 [ 的二合字符，但 <:: 后面不是 : 或 > 时，< 单独成为一个记号（[lex.pptoken]），
# 所以 std::vector<::Foo> 中的 < 后面是 ::。
# <: is the digraph of [, but in <:: followed by neither : nor >, the < is a token by itself
# ([lex.pptoken]), so std::vector<::Foo> has :: after the <.
_PUNCTUATOR_PATTERNS = [
    r"<:(?!:(?![:>]))" if item == "<:" else re.escape(item) for item in _PUNCTUATORS
]
_TOKEN = re.compile(
    r"\r\n?|\n"
    r"|[^\S\r\n]+"
    r"|//[^\r\n]*"
    r"|/\*.*?(?:\*/|\Z)"
    r'|(?:u8|u|U|L)?R"'
    r'|(?:u8|u|U|L)?"(?:(?:[^"\\\r\n]|\\(?:\r\n|.))*"'
    + _IDENTIFIER_TAIL
    + r"|(?:[^\\\r\n]|\\(?:\r\n|.))*)"
    r"|(?:u8|u|U|L)?'(?:(?:[^'\\\r\n]|\\(?:\r\n|.))*'"
    + _IDENTIFIER_TAIL
    + r"|(?:[^\\\r\n]|\\(?:\r\n|.))*)"
    r"|[A-Za-z_\x80-\U0010ffff]"
    + _IDENTIFIER_TAIL
    + r"|[0-9]"
    + _NUMBER_TAIL
    # 以 . 开头的数字（.5）。
    # A number that starts with . (.5).
    + r"|\.(?=\d)"
    + _NUMBER_TAIL
    + "|"
    + "|".join(_PUNCTUATOR_PATTERNS)
    + r"|.",
    re.DOTALL,
)
_IDENTIFIER_TAIL_PATTERN = re.compile(_IDENTIFIER_TAIL)
_LINE_BREAK = re.compile(rb"\r\n?|\n")
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
# 只缓存短文本，进程里出现过的长注释和长字符串不会一直留在内存里；每次扫描开始前，超过条目
# 上限的缓存清空重来，解析大量不同文件的进程（例如遍历整个工程）占用的内存因此有上限。同一次
# 扫描内不清空，一个文件里成批不同的短文本（大数值表）不会让缓存反复失效。
# Only short texts are cached, so long comments and strings seen by the process are not kept;
# before each lexing pass a cache past its entry limit is emptied, which bounds the memory of a
# process that parses many different files (walking a whole project, for example). A cache is
# not emptied during a pass, so one file with masses of distinct short texts (a large table of
# numbers) does not make the cache miss again and again.
_CACHED_LENGTH = 64
_CACHED_ENTRIES = 100_000
_OPENING_BRACKETS = frozenset({"(", "[", "{"})
_CLOSING_BRACKETS = frozenset({")", "]", "}"})


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
_CACHES = (_INFOS, _PLAIN_EDGES, _SIGNIFICANCE)


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
        diagnostics: 未闭合的块注释或原始字符串。
            Unclosed block comments or raw strings.
    """

    __slots__ = (
        "diagnostics",
        "infos",
        "offsets",
        "special",
        "texts",
        "_lexemes",
        "_line_starts",
    )

    def __init__(
        self,
        texts: list[str],
        infos: list[_Info],
        offsets: list[int],
        special: list[int],
    ) -> None:
        """保存扫描结果；诊断由 lex() 随后填入。
        Store the lexing result; lex() fills in the diagnostics afterwards.
        """
        self.texts = texts
        self.infos = infos
        self.offsets = offsets
        self.special = special
        self.diagnostics: list[Diagnostic] = []
        self._lexemes: list[_Lexeme] | None = None
        self._line_starts: list[int] | None = None

    def diagnostic(self, message: str, span: SourceSpan) -> Diagnostic:
        """一条覆盖 span 的诊断，带起止处的行号和字节列号。
        A diagnostic covering span, with the row and byte column where it starts and ends.
        """
        return Diagnostic(message, span, self._point(span.start), self._point(span.end))

    def _point(self, offset: int) -> SourcePoint:
        """字节位置 offset 所在的行号和字节列号；行首表在首次使用时建立。
        The row and byte column of byte position offset; the line-start table is built on first
        use.

        行首表在源码字节上找换行，块注释和原始字符串内部的换行也算在内。
        The line-start table finds the line breaks in the source bytes, so the line breaks inside
        block comments and raw strings count too.
        """
        if self._line_starts is None:
            data = "".join(self.texts).encode("utf-8", errors="surrogateescape")
            self._line_starts = [0] + [match.end() for match in _LINE_BREAK.finditer(data)]
        row = bisect.bisect_right(self._line_starts, offset) - 1
        return SourcePoint(row, offset - self._line_starts[row])

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
    for cache in _CACHES:
        if len(cache) > _CACHED_ENTRIES:
            cache.clear()
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
    if ">>" in texts and "template" in texts:
        closers = _template_closers(texts)
        if closers:
            for index in reversed(closers):
                texts[index : index + 1] = [">", ">"]
            special[:] = [index + bisect.bisect_left(closers, index) for index in special]
    infos = list(map(_INFOS.__getitem__, texts))
    for index in special:
        infos[index] = _BYTE_ORDER_MARK if index == 0 and texts[0] == "﻿" else _RAW_STRING
    widths = map(len, texts) if text.isascii() else map(_byte_width, texts)
    offsets = list(accumulate(widths, initial=0))
    if not messages and texts:
        message = _unclosed(texts[-1], infos[-1])
        if message is not None:
            messages.append(message)
    lexed = _Lexed(texts, infos, offsets, special)
    lexed.diagnostics = [
        lexed.diagnostic(message, SourceSpan(offsets[-2], offsets[-1])) for message in messages
    ]
    return lexed


def _with_raw_strings(
    text: str, texts: list[str], special: list[int], messages: list[str]
) -> list[str]:
    """把 findall 切出的原始字符串前缀（R"、u8R" 等）展开成完整的原始字符串 lexeme。
    Expand the raw string prefixes (R", u8R" and so on) that findall produced into complete raw
    string lexemes.

    原始字符串的结束符取决于分隔符，正则无法在不分组的前提下表达，所以从前缀处在 Python 里扫描
    到结束符。之后从结束符处重新切分，直到某个 lexeme 的起点与原来的切分重合，再继续使用原来的
    结果；从同一位置开始，两次切分得到的结果相同。
    A raw string ends at a delimiter-dependent sequence that the group-free pattern cannot express,
    so the literal is scanned in Python from its prefix. Lexing then restarts at its end until a
    lexeme starts where one of the original lexemes starts, and the original result is used from
    there on; lexing from the same position gives the same result.
    """
    starts = list(accumulate(map(len, texts), initial=0))
    count = len(texts)
    result: list[str] = []
    index = 0
    relexed: Iterator[re.Match[str]] | None = None
    while True:
        if relexed is None:
            if index == count:
                return result
            token, start = texts[index], starts[index]
            index += 1
        else:
            match = next(relexed, None)
            if match is None:
                return result
            start = match.start()
            aligned = bisect.bisect_left(starts, start)
            if aligned < count and starts[aligned] == start:
                relexed, index = None, aligned
                continue
            token = match.group()
        if token not in _RAW_PREFIXES:
            result.append(token)
            continue
        end, message = _raw_string_end(text, start, token)
        special.append(len(result))
        result.append(text[start:end])
        if message is not None:
            messages.append(message)
            return result
        aligned = bisect.bisect_left(starts, end)
        if aligned < count and starts[aligned] == end:
            relexed, index = None, aligned
        else:
            relexed = _TOKEN.finditer(text, end)


def _template_closers(texts: list[str]) -> list[int]:
    """template 参数列表中同时关闭一层模板实参列表和参数列表本身的 >> 的下标，按顺序排列。
    The indices, in order, of the >> lexemes in template parameter lists that close one template
    argument list and the parameter list itself.

    模板实参列表中第一个不嵌套的 >> 是两个 > 记号（[temp.names]），所以
    template <typename T = A<int>> 中的 >> 是默认值的结尾加上参数列表的结尾。括号内的尖括号不计。
    The first non-nested >> in a template argument list is two > tokens ([temp.names]), so the >>
    in template <typename T = A<int>> ends the default and then the parameter list. Angles inside
    brackets do not count.
    """
    closers: list[int] = []
    count = len(texts)
    keyword = -1
    while True:
        try:
            keyword = texts.index("template", keyword + 1)
        except ValueError:
            return sorted(set(closers))
        opening = keyword + 1
        while opening < count and not _SIGNIFICANCE[texts[opening]]:
            opening += 1
        if opening >= count or texts[opening] != "<":
            continue
        angles = brackets = 0
        for index in range(opening, count):
            text = texts[index]
            if text in _OPENING_BRACKETS:
                brackets += 1
            elif text in _CLOSING_BRACKETS:
                brackets -= 1
                if brackets < 0:
                    break
            elif brackets:
                continue
            elif text == "<":
                angles += 1
            elif text == ">":
                angles -= 1
            elif text == ">>":
                if angles == 2:
                    closers.append(index)
                angles -= 2
            elif text == ";":
                break
            else:
                continue
            if angles <= 0:
                break


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
    # 该模式能匹配空串。
    # The pattern matches the empty string.
    assert match is not None
    return match.end(), None


def _unclosed(last: str, info: _Info) -> str | None:
    """最后一个 lexeme 是未闭合的块注释时返回诊断消息；只有最后一个 lexeme 可能如此。
    The diagnostic message when the last lexeme is an unclosed block comment; only the last
    lexeme can be one.
    """
    if (
        info[0] == "comment"
        and last.startswith("/*")
        and not (len(last) >= 4 and last.endswith("*/"))
    ):
        return tr("unclosed block comment", "未闭合的块注释")
    return None
