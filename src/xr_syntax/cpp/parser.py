"""xr-syntax 自有 C++ 结构解析器。
xr-syntax native C++ structural parser. It builds source-level syntax without Tree-sitter, Clang, or compiler semantics.
"""

from __future__ import annotations

import sys
from itertools import accumulate, compress

from xr_syntax.core import (
    GreenElement,
    GreenNode,
    SyntaxTree,
    decode_source,
    encode_source,
)
from xr_syntax.core.green import green_token
from xr_syntax.cpp._declaration import BEFORE_INITIALIZERS, DeclarationMixin
from xr_syntax.cpp._declarator import ATTRIBUTE_WORDS, TYPE_KEYWORDS, DeclaratorMixin
from xr_syntax.cpp._expression import ExpressionMixin
from xr_syntax.cpp._ranges import RangeMixin, deduplicate_replacements
from xr_syntax.cpp._support import Replacement
from xr_syntax.cpp.lexer import CONTROL, Lexed, lex
from xr_syntax.i18n import tr

_CLASS_KEYWORDS = frozenset({"class", "struct", "union"})
_ACCESS_KEYWORDS = frozenset({"public", "private", "protected"})
_CLASS_KINDS = {
    "class": "class_specifier",
    "struct": "struct_specifier",
    "union": "union_specifier",
}
_PREPROCESSOR_KINDS = {
    "include": "preproc_include",
    "define": "preproc_def",
    "if": "preproc_if",
    "ifdef": "preproc_ifdef",
    "ifndef": "preproc_ifdef",
}
_CONTROL_OR_DO = frozenset(CONTROL | {"do"})
# _find_unit_end 关心的记号；其他记号直接跳过。
# The tokens _find_unit_end looks at; other tokens are skipped.
_UNIT_TOKENS = frozenset({"(", ")", "[", "]", ";", "{", ":"} | TYPE_KEYWORDS)
_OPENING_DELIMITERS = {"(": ")", "[": "]", "{": "}"}
_CLOSING_DELIMITERS = {")": "(", "]": "[", "}": "{"}

# 嵌套上限。作用域和表达式每嵌套一层，解析器用的 Python 调用不超过 _FRAMES_PER_NESTING 层
# （实测最多 8 层）。上限按当前可用的递归深度计算，最多 _MAX_NESTING 层；实际源码最深约 22 层
# （CMSIS DSP）。更深的内容保持为未结构化的源码并给出诊断，不会触发 RecursionError。
# The nesting limit. Each nested scope or expression costs the parser at most _FRAMES_PER_NESTING
# Python calls (8 measured at most). The limit follows from the recursion depth available at the
# time and is at most _MAX_NESTING; real source nests about 22 levels at most (CMSIS DSP). Deeper
# source stays unstructured with a diagnostic instead of raising RecursionError.
_FRAMES_PER_NESTING = 10
_MAX_NESTING = 100
_RESERVED_FRAMES = 64


# 每次解析都创建独立的 _StructuralParser，同一个 CppParser 可以被多个线程同时使用。
# Every parse creates its own _StructuralParser, so threads can share one CppParser.
class CppParser:
    """无损的 C++ 解析器：词法扫描、结构解析，再检查结果逐字节还原源码。
    Lossless C++ parser: lexing, structural parsing, then a check that the result reproduces
    the source byte for byte.
    """

    def parse(self, source: str | bytes, *, source_name: str | None = None) -> SyntaxTree:
        """解析源码并保证结果可逐字节还原。
        Parse source text or bytes into the corresponding immutable syntax representation.
        """
        return parse_with_lexing(source, source_name)[0]


def parse_with_lexing(source: str | bytes, source_name: str | None) -> tuple[SyntaxTree, Lexed]:
    """解析源码，同时返回词法结果，供文档复用。
    Parse source and also return the lexing result for the document to reuse.
    """
    data = encode_source(source) if isinstance(source, str) else bytes(source)
    # 词法器给出保持源码的 lexeme 和基础诊断；结构解析只在 lexeme 区间上建立结构，不再切分源码。
    # The lexer produces source-preserving lexemes and basic diagnostics; the structural parser
    # only builds structure over lexeme ranges and never re-splits the source text.
    lexed = lex(decode_source(data))
    parser = _StructuralParser(lexed)
    root = parser.parse_translation_unit()
    tree = SyntaxTree("cpp", root, tuple(parser.diagnostics), source_name)
    if tree.render_bytes() != data:
        raise AssertionError(
            tr(
                "the C++ parser did not reproduce the source byte for byte",
                "C++ 解析结果没有逐字节还原源码",
            )
        )
    return tree, lexed


# 结构层拆成 declaration / declarator / expression / range 四个 mixin；
# 这里仅负责阶段调度和 translation-unit 级控制流，避免单文件变成巨型 parser。
# The structural layer is split into the declaration / declarator / expression / range mixins;
# this class only schedules the stages and handles translation-unit level control flow.
class _StructuralParser(DeclarationMixin, ExpressionMixin, DeclaratorMixin, RangeMixin):
    """组合声明、declarator、表达式和区间解析阶段，构成原生 C++ 结构 parser。
    Combine declaration, declarator, expression, and range parsing stages into the native C++ structural parser.
    """

    def __init__(self, lexed: Lexed) -> None:
        """建立有效 lexeme 数组、位置表、叶子边和括号配对表。
        Build the significant-lexeme arrays, the position table, the leaf edges and the
        delimiter-pair tables.
        """
        texts = lexed.texts
        self._texts = texts
        self._infos = lexed.infos
        self._offsets = lexed.offsets
        self._lexed = lexed
        self._count = len(texts)
        self.diagnostics = list(lexed.diagnostics)
        significant = lexed.significance()
        self._sig = list(compress(range(len(texts)), significant))
        self._rank = list(accumulate(significant, initial=0))
        self._stext = list(map(texts.__getitem__, self._sig))
        self._plain = lexed.plain_children()
        self._pairs = {}
        self._reverse_pairs = {}
        self._dirty = set()
        self._variable_names = {}
        self._depth = 0
        self._depth_limit = _nesting_limit()
        self._too_deep = False
        self._build_delimiter_pairs()

    def parse_translation_unit(self) -> GreenNode:
        """解析整个 translation unit；未知顶层片段原样保留。
        Parse the complete translation unit while preserving unknown top-level fragments verbatim.
        """
        replacements = self._parse_scope(0, self._count, context="top")
        return self._compose("translation_unit", 0, self._count, replacements)

    def _build_delimiter_pairs(self) -> None:
        """对 (), [] 和 {} 建立配对，并对不平衡输入产生诊断。
        Pair (), [], and {} delimiters and emit diagnostics for unbalanced input.
        """
        stack: list[tuple[str, int]] = []
        sig = self._sig
        stext = self._stext
        pairs = self._pairs
        reverse_pairs = self._reverse_pairs
        # 先用 list.index（在 C 里查找）收集全部括号的位置，再按源码顺序配对。
        # Collect the positions of all delimiters with list.index (which searches in C) first,
        # then pair them in source order.
        positions: list[int] = []
        for delimiter in "()[]{}":
            position = -1
            try:
                while True:
                    position = stext.index(delimiter, position + 1)
                    positions.append(position)
            except ValueError:
                pass
        positions.sort()
        for position in positions:
            text = stext[position]
            if text in _OPENING_DELIMITERS:
                stack.append((text, sig[position]))
            else:
                index = sig[position]
                if not stack or stack[-1][0] != _CLOSING_DELIMITERS[text]:
                    self._diagnostic(
                        tr("unmatched closing delimiter", "不匹配的闭合符号"), index, index + 1
                    )
                    # 此刻未闭合的开括号以后若配对，组内就有这个多余的闭括号。
                    # Opening delimiters still open now contain this stray closing delimiter
                    # if they are paired later.
                    self._dirty.update(opening for _, opening in stack)
                    continue
                _, opening = stack.pop()
                pairs[opening] = index
                reverse_pairs[index] = opening
        for _, opening in stack:
            self._diagnostic(tr("unclosed delimiter", "未闭合的分隔符"), opening, opening + 1)

    def _enter(self, start: int, end: int) -> bool:
        """进入一层作用域或表达式嵌套；超过嵌套上限时记录一次诊断并返回 False。
        Enter one level of scope or expression nesting; past the nesting limit, record one
        diagnostic and return False.
        """
        if self._depth < self._depth_limit:
            self._depth += 1
            return True
        if not self._too_deep:
            self._too_deep = True
            self._diagnostic(
                tr(
                    "nesting too deep; the inner source is kept unstructured",
                    "嵌套过深，内层源码保持未结构化",
                ),
                start,
                end,
            )
        return False

    def _parse_scope(self, start: int, end: int, *, context: str) -> list[Replacement]:
        """按顶层语句/声明边界解析一个连续作用域。
        Parse one continuous scope using top-level statement/declaration boundaries.
        """
        if not self._enter(start, end):
            return []
        result: list[Replacement] = []
        replacement: Replacement | None
        texts = self._texts
        cursor = start
        while True:
            current = self._next_significant(cursor, end)
            if current is None:
                break
            text = texts[current]

            # scope 解析按“明确结构优先”处理：预处理、template、class、
            # namespace、access label 都先于通用 unit/declaration fallback。
            # Explicit structures come first: preprocessor lines, templates, classes,
            # namespaces and access labels precede the generic unit/declaration fallback.
            if text == "#" and self._line_prefix_is_trivia(current, start):
                replacement = self._parse_preprocessor(current, end)
                result.append(replacement)
                cursor = replacement[1]
                continue

            if text == "template":
                replacement = self._parse_template(current, end, context=context)
                if replacement is not None:
                    result.append(replacement)
                    cursor = replacement[1]
                    continue

            if text in _CLASS_KEYWORDS:
                replacement = self._parse_class(current, end)
                if replacement is not None:
                    result.append(replacement)
                    cursor = replacement[1]
                    semicolon = self._next_significant(cursor, end)
                    if semicolon is not None and texts[semicolon] == ";":
                        cursor = semicolon + 1
                    continue

            if text == "namespace" or text == "inline":
                replacement = self._parse_namespace(current, end)
                if replacement is not None:
                    result.append(replacement)
                    cursor = replacement[1]
                    continue

            if text == "extern":
                replacement = self._parse_linkage(current, end)
                if replacement is not None:
                    result.append(replacement)
                    cursor = replacement[1]
                    continue

            if context == "class" and text in _ACCESS_KEYWORDS:
                colon = self._next_significant(current + 1, end)
                if colon is not None and texts[colon] == ":":
                    node = self._compose("access_specifier", current, colon + 1, [])
                    result.append((current, colon + 1, node, None))
                    cursor = colon + 1
                    continue

            unit_end = self._find_unit_end(current, end, context=context)
            if unit_end <= current:
                cursor = current + 1
                continue
            replacement = self._parse_unit(current, unit_end, context=context)
            if replacement is not None:
                result.append(replacement)
            cursor = unit_end
        self._depth -= 1
        return deduplicate_replacements(result)

    def _find_unit_end(self, start: int, end: int, *, context: str) -> int:
        """从当前 unit 起点向后扫描到顶层声明/语句边界。
        Scan forward from one unit start until its top-level declaration/statement boundary.
        """
        first = self._next_significant(start, end)
        if first is None:
            return end
        texts = self._texts
        first_text = texts[first]
        if first_text in _CONTROL_OR_DO:
            return self._control_unit_end(first, end)
        if first_text == "case" or first_text == "default":
            # case 和 default 标签单独成为一个单元，标签后的语句另起一个单元。
            # A case or default label is a unit by itself; the statement after it is another.
            colon = self._find_top_level_token(first + 1, end, ":")
            if colon is not None:
                return colon + 1

        stext = self._stext
        sig = self._sig
        pairs = self._pairs
        infos = self._infos
        depth_round = depth_square = 0
        initializers = type_body = False
        low, high = self._span(first, end)
        position = low
        while position < high:
            text = stext[position]
            if text not in _UNIT_TOKENS:
                position += 1
                continue
            if text in TYPE_KEYWORDS:
                # typedef struct {...} Name; 中，类型关键字之后、参数列表之前的 { 是类型体。
                # In typedef struct {...} Name;, a { after a type keyword and before any
                # parameter list is a type body.
                if not (depth_round or depth_square):
                    type_body = True
                position += 1
                continue
            if text == ":":
                # 参数列表之后的 : 开始构造函数的成员初始化列表。
                # A : after the parameter list starts a constructor's member initializer list.
                if (
                    not (depth_round or depth_square)
                    and position > low
                    and stext[position - 1] in BEFORE_INITIALIZERS
                ):
                    initializers = True
                position += 1
                continue
            if (
                initializers
                and text == "{"
                and not (depth_round or depth_square)
                and (stext[position - 1] == ">" or infos[sig[position - 1]][0] == "identifier")
            ):
                # 成员初始化列表里紧跟名字的 { 是一项初始化，函数体在其后。
                # In a member initializer list, a { right after a name is one initializer; the
                # function body comes after it.
                position = self._skip_group(position, high)
                continue
            if text == "(" or text == "[":
                if not (depth_round or depth_square):
                    if text == "(" and stext[position - 1] not in ATTRIBUTE_WORDS:
                        type_body = False
                    skipped = self._skip_group(position, high)
                    if skipped != position + 1:
                        position = skipped
                        continue
                if text == "(":
                    depth_round += 1
                else:
                    depth_square += 1
            elif text == ")":
                depth_round = max(0, depth_round - 1)
            elif text == "]":
                depth_square = max(0, depth_square - 1)
            elif depth_round == 0 and depth_square == 0:
                index = sig[position]
                if text == ";":
                    return index + 1
                if index in pairs:
                    close = pairs[index]
                    if first_text in TYPE_KEYWORDS:
                        semicolon = self._next_significant(close + 1, end)
                        return (
                            semicolon + 1
                            if semicolon is not None and texts[semicolon] == ";"
                            else close + 1
                        )
                    if type_body and stext[position - 1] != "=":
                        type_body = False
                        position = self._skip_group(position, high)
                        continue
                    # direct-list initialization 要继续找到 ;，函数/namespace 则在 } 结束。
                    # Direct-list initialization continues through the semicolon, while function
                    # and namespace bodies end at the closing brace.
                    if (
                        position > low
                        and stext[position - 1] not in (")", "try", "else", "do")
                        and first_text not in ("namespace", "extern")
                    ):
                        semicolon = self._next_significant(close + 1, end)
                        if semicolon is not None and texts[semicolon] == ";":
                            return semicolon + 1
                    return close + 1
            position += 1
        return end

    def _control_unit_end(self, start: int, end: int) -> int:
        """寻找控制流语句末尾，避免把 body 内分号误当外层结束。
        Find the end of a control-flow statement without treating body semicolons as the outer
        terminator.

        不带花括号的嵌套控制语句和 else if 链用栈迭代处理，链再长也不会递归；栈里记录每层的关键字，
        结束时从最内层起为 if 配上后面的 else、为 do 接上后面的 while (...);，悬空的 else 因此归最近
        的 if。
        Unbraced nested control statements and else-if chains are handled iteratively with a
        stack, so no chain length recurses; the stack records the keyword of each level, and on
        the way out each if from the innermost on takes a following else and each do its
        following while (...);, so a dangling else belongs to the nearest if.
        """
        texts = self._texts
        pairs = self._pairs
        pending: list[str] = []
        cursor = start
        while True:
            keyword = texts[cursor]
            after = cursor + 1
            open_paren = self._next_significant(after, end)
            if (
                keyword != "do"
                and open_paren is not None
                and texts[open_paren] == "("
                and open_paren in pairs
            ):
                after = pairs[open_paren] + 1
            body = self._next_significant(after, end)
            if body is None:
                return end
            pending.append(keyword)
            if texts[body] in _CONTROL_OR_DO:
                cursor = body
                continue
            result = self._body_end(body, end)
            while pending:
                keyword = pending.pop()
                if keyword == "do":
                    result = self._do_tail_end(result, end)
                    continue
                if keyword != "if":
                    continue
                else_index = self._next_significant(result, end)
                if else_index is None or texts[else_index] != "else":
                    continue
                else_body = self._next_significant(else_index + 1, end)
                if else_body is None:
                    continue
                if texts[else_body] in _CONTROL_OR_DO:
                    cursor = else_body
                    break
                result = self._body_end(else_body, end)
            else:
                return result

    def _do_tail_end(self, body_end: int, end: int) -> int:
        """do 语句的 body 之后 while (...); 结束的位置；后面不是 while 时就是 body_end。
        Where the while (...); after the body of a do statement ends; body_end when no while
        follows.
        """
        texts = self._texts
        keyword = self._next_significant(body_end, end)
        if keyword is None or texts[keyword] != "while":
            return body_end
        open_paren = self._next_significant(keyword + 1, end)
        if open_paren is None or texts[open_paren] != "(" or open_paren not in self._pairs:
            return body_end
        close = self._pairs[open_paren]
        semicolon = self._next_significant(close + 1, end)
        return semicolon + 1 if semicolon is not None and texts[semicolon] == ";" else close + 1

    def _body_end(self, body: int, end: int) -> int:
        """不是控制语句的 body 结束的位置：花括号块到右括号之后，其他语句到其末尾。
        Where a body that is no control statement ends: a braced block after its closing brace,
        another statement at its end.
        """
        if self._texts[body] == "{" and body in self._pairs:
            return self._pairs[body] + 1
        return self._find_unit_end(body, end, context="block")

    def _parse_preprocessor(self, start: int, end: int) -> Replacement:
        """解析一条逻辑预处理行，并对 #include 暴露 path field。
        Parse one logical preprocessor line and expose a path field for #include.
        """
        texts = self._texts
        infos = self._infos
        line_end = start + 1
        while line_end < end:
            if infos[line_end][0] == "newline":
                previous = line_end - 1
                while previous >= start and infos[previous][2]:
                    previous -= 1
                # 反斜杠续行仍属于同一条逻辑预处理指令，不能在物理换行处
                # 提前结束，否则宏 body 会被误当成普通 translation-unit 源码。
                # A backslash continuation stays in the same logical directive; ending at the
                # physical line break would turn the macro body into translation-unit source.
                line_end += 1
                if previous >= start and texts[previous] == "\\":
                    continue
                break
            line_end += 1

        low, high = self._span(start, line_end)
        kind = _PREPROCESSOR_KINDS.get(
            self._stext[low + 1] if high - low > 1 else "", "preproc_call"
        )
        replacements: list[Replacement] = []
        if kind == "preproc_include" and high - low > 2:
            path_start = self._sig[low + 2]
            if texts[path_start] == "<":
                path_end = path_start + 1
                while path_end < line_end and texts[path_end] != ">":
                    path_end += 1
                if path_end < line_end:
                    path_end += 1
                    path = green_token("system_lib_string", self._text(path_start, path_end), True)
                    replacements.append((path_start, path_end, path, "path"))
            else:
                replacements.append(
                    (path_start, path_start + 1, self._plain[path_start].element, "path")
                )

        node = self._compose(kind, start, line_end, replacements)
        return (start, line_end, node, None)

    def _parse_template(self, start: int, end: int, *, context: str) -> Replacement | None:
        """解析 template<...> 及其紧随的声明。
        Parse template<...> together with the declaration that immediately follows it.
        """
        open_angle = self._next_significant(start + 1, end)
        if open_angle is None or self._texts[open_angle] != "<":
            return None
        close_angle = self._match_angle(open_angle, end)
        if close_angle is None:
            return None
        parameters = self._parse_template_parameters(open_angle, close_angle)
        declaration_start = self._next_significant(close_angle + 1, end)
        if declaration_start is None:
            return None

        declaration_end = self._find_unit_end(declaration_start, end, context=context)
        if declaration_end <= declaration_start:
            return None

        nested: Replacement | None
        if self._texts[declaration_start] in _CLASS_KEYWORDS:
            nested = self._parse_class(declaration_start, declaration_end)
        else:
            nested = self._parse_unit(declaration_start, declaration_end, context=context)
        if nested is None:
            return None

        node = self._compose(
            "template_declaration",
            start,
            declaration_end,
            [
                (open_angle, close_angle + 1, parameters, "parameters"),
                (nested[0], nested[1], nested[2], None),
            ],
        )
        return (start, declaration_end, node, None)

    def _parse_template_parameters(self, open_angle: int, close_angle: int) -> GreenNode:
        """把模板参数列表拆成带 name/default 的参数节点。
        Split a template parameter list into parameter nodes carrying name/default fields.
        """
        replacements: list[Replacement] = []
        for part in self._split_top_level(open_angle + 1, close_angle, ",", angle_brackets=True):
            trimmed = self._trim(*part)
            if trimmed is None:
                continue
            node = self._parse_parameter(*trimmed, template=True)
            replacements.append((*trimmed, node, None))
        return self._compose("template_parameter_list", open_angle, close_angle + 1, replacements)

    def _parse_class(self, start: int, end: int) -> Replacement | None:
        """解析 class/struct/union 定义并递归解析成员列表；不是定义时返回 None。
        Parse a class/struct/union definition and recursively parse its member list; None when
        the keyword does not start a definition.
        """
        low, high = self._span(start + 1, end)
        head = self._class_head(low, high)
        if head is None:
            return None
        name, open_brace = head
        close_brace = self._pairs.get(open_brace, end)
        if close_brace >= end:
            return None

        body_replacements = self._parse_scope(open_brace + 1, close_brace, context="class")
        body = self._compose(
            "field_declaration_list", open_brace, close_brace + 1, body_replacements
        )
        replacements: list[Replacement] = [(open_brace, close_brace + 1, body, "body")]
        if name is not None:
            first, last = name
            element: GreenElement = (
                green_token("type_identifier", self._texts[first], True)
                if first == last
                else self._compose("qualified_identifier", first, last + 1, [])
            )
            replacements.append((first, last + 1, element, "name"))
        class_end = close_brace + 1
        node = self._compose(_CLASS_KINDS[self._texts[start]], start, class_end, replacements)

        # 普通顶层/成员 class 声明的分号不属于 specifier；保持与原 view 兼容。
        # Keep the semicolon of a normal top-level/member class declaration outside the
        # specifier to preserve compatibility with the existing views.
        return (start, class_end, node, None)

    def _class_head(self, low: int, high: int) -> tuple[tuple[int, int] | None, int] | None:
        """识别类头，直到类体的 {。
        Recognize a class head up to the { of the class body.

        类头包括属性、可带 :: 限定和模板实参的类名（名前的宏名跳过）、final、基类列表。
        不是类定义（前向声明、详细类型说明符、函数）时返回 None。
        Recognize a class head: attributes, a class name that may be ::-qualified and carry
        template arguments (macro names before it are skipped), final and a base clause, up to
        the { of the body. None when the keyword does not start a definition (a forward
        declaration, an elaborated type specifier, a function).

        Args:
            low: 类关键字之后第一个有效 lexeme 的位置。
                The position of the first significant lexeme after the class keyword.
            high: 作用域末尾对应的位置。
                The position matching the end of the scope.

        Returns:
            ((类名第一个 token, 最后一个 token) 或匿名类为 None, 类体 { 的下标)。
            ((first token, last token) of the class name, or None for an anonymous class,
            index of the body's {).
        """
        sig = self._sig
        stext = self._stext
        infos = self._infos
        position = self._skip_class_attributes(low, high, low)
        name: tuple[int, int] | None = None
        while position < high:
            index = sig[position]
            if infos[index][0] != "identifier" or stext[position] == "final":
                break
            # 名字序列：identifier (<...>)? (:: identifier (<...>)?)*；最后一段才是类名。
            # A name sequence: identifier (<...>)? (:: identifier (<...>)?)*.
            first = last = index
            position += 1
            while position < high:
                following = stext[position]
                if following == "<":
                    closing = self._match_angle(sig[position], sig[high - 1] + 1)
                    if closing is None:
                        return None
                    while position < high and sig[position] <= closing:
                        position += 1
                    continue
                if (
                    following == "::"
                    and position + 1 < high
                    and infos[sig[position + 1]][0] == "identifier"
                ):
                    last = sig[position + 1]
                    position += 2
                    continue
                break
            # 名字前的 identifier（导出宏）不属于类名，下一个 identifier 才是。
            # An identifier before the name (an export macro) is not the class name.
            name = (first, last)
            position = self._skip_class_attributes(low, high, position)
        if position < high and stext[position] == "final":
            position += 1
        if position >= high:
            return None
        text = stext[position]
        if text == "{":
            return name, sig[position]
        if text != ":":
            return None
        # 基类列表：直到顶层的 {；其中出现顶层 ; 说明这不是类定义。
        # The base clause runs to the top-level {; a top-level ; means this is no definition.
        depth = 0
        for base in range(position + 1, high):
            text = stext[base]
            if text in ("(", "["):
                depth += 1
            elif text in (")", "]"):
                depth -= 1
            elif depth == 0 and text == "{":
                return name, sig[base]
            elif depth == 0 and text == ";":
                return None
        return None

    def _skip_class_attributes(self, low: int, high: int, position: int) -> int:
        """跳过 [[...]]、alignas(...)、__attribute__((...)) 和 __declspec(...)，返回其后的位置。
        Skip [[...]], alignas(...), __attribute__((...)) and __declspec(...) and return the
        position after them.
        """
        sig = self._sig
        stext = self._stext
        pairs = self._pairs
        while position < high:
            index = sig[position]
            text = stext[position]
            following = stext[position + 1] if position + 1 < high else None
            skip_to = None
            if text == "[" and index in pairs:
                if following != "[":
                    return position
                skip_to = pairs[index]
            elif text in ATTRIBUTE_WORDS and self._infos[index][0] == "identifier":
                if following == "(":
                    skip_to = pairs.get(sig[position + 1])
            if skip_to is None:
                return position
            while position < high and sig[position] <= skip_to:
                position += 1
        return position

    def _parse_namespace(self, start: int, end: int) -> Replacement | None:
        """解析命名空间定义（可带 inline），使内部声明仍可结构化查询；不是定义时返回 None。
        Parse a namespace definition (inline allowed) so declarations inside remain structurally
        queryable; None when the source is no definition.

        名字可以是嵌套名 a::b 和 a::inline b，此时 name 是 nested_namespace_specifier。
        命名空间别名 namespace fs = std::filesystem; 不是定义。
        The name may be a nested name a::b or a::inline b; name is then a
        nested_namespace_specifier. A namespace alias namespace fs = std::filesystem; is no
        definition.
        """
        sig = self._sig
        stext = self._stext
        infos = self._infos
        low, high = self._span(start + 1, end)
        if self._texts[start] == "inline":
            if low >= high or stext[low] != "namespace":
                return None
            low += 1
        position = self._skip_class_attributes(low, high, low)
        name: tuple[int, int] | None = None
        if position < high and infos[sig[position]][0] == "identifier":
            last = position
            while last + 2 < high and stext[last + 1] == "::":
                following = last + 2
                if stext[following] == "inline" and following + 1 < high:
                    following += 1
                if infos[sig[following]][0] != "identifier":
                    break
                last = following
            name = (sig[position], sig[last])
            position = self._skip_class_attributes(low, high, last + 1)
        if position >= high or stext[position] != "{":
            return None
        open_brace = sig[position]
        close_brace = self._pairs.get(open_brace)
        if close_brace is None:
            return None
        replacements = self._parse_scope(open_brace + 1, close_brace, context="top")
        body = self._compose("declaration_list", open_brace, close_brace + 1, replacements)
        nested: list[Replacement] = [(open_brace, close_brace + 1, body, "body")]
        if name is not None:
            first, last = name
            element: GreenElement = (
                self._plain[first].element
                if first == last
                else self._compose("nested_namespace_specifier", first, last + 1, [])
            )
            nested.append((first, last + 1, element, "name"))
        node = self._compose("namespace_definition", start, close_brace + 1, nested)
        return (start, close_brace + 1, node, None)

    def _parse_linkage(self, start: int, end: int) -> Replacement | None:
        """解析 extern "C" { ... } 这样的链接说明块，块内按顶层作用域解析；其他 extern 返回 None。
        Parse a linkage specification block such as extern "C" { ... }, whose inside is parsed
        as a top-level scope; None for any other extern.
        """
        literal = self._next_significant(start + 1, end)
        if literal is None or self._infos[literal][0] != "string_literal":
            return None
        open_brace = self._next_significant(literal + 1, end)
        if open_brace is None or self._texts[open_brace] != "{":
            return None
        close_brace = self._pairs.get(open_brace)
        if close_brace is None or close_brace >= end:
            return None
        replacements = self._parse_scope(open_brace + 1, close_brace, context="top")
        body = self._compose("declaration_list", open_brace, close_brace + 1, replacements)
        node = self._compose(
            "linkage_specification",
            start,
            close_brace + 1,
            [
                (literal, literal + 1, self._plain[literal].element, "value"),
                (open_brace, close_brace + 1, body, "body"),
            ],
        )
        return (start, close_brace + 1, node, None)


def _nesting_limit() -> int:
    """当前调用栈下可安全使用的嵌套层数。
    The nesting depth that can be used safely from the current call stack.
    """
    depth = 0
    frame = sys._getframe()
    while frame is not None:
        depth += 1
        frame = frame.f_back  # type: ignore[assignment]
    available = sys.getrecursionlimit() - depth - _RESERVED_FRAMES
    return max(1, min(_MAX_NESTING, available // _FRAMES_PER_NESTING))
