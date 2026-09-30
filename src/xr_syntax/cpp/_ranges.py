"""C++ parser 内部的区间、分隔符与 green-tree compose 工具。
Internal C++ parser helpers for source ranges, delimiters, replacements, and green-tree composition.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass

from xr_syntax.core import Diagnostic, GreenChild, GreenElement, GreenNode, SourcePoint, SourceSpan
from xr_syntax.core.green import _child, _node
from xr_syntax.i18n import tr

from ._support import _ParserSupport
from .lexer import _BINARY_PRECEDENCE, _CONTROL


@dataclass(frozen=True)
class _Replacement:
    """描述 compose 时用结构节点替换连续 lexeme 区间。
    Describe a contiguous lexeme range replaced by a structured node during composition.
    """

    start: int
    end: int
    element: GreenElement
    field: str | None = None


class _RangeMixin(_ParserSupport):
    """提供 parser 各阶段共享的区间扫描、匹配、compose 与诊断操作。
    Provide shared range scanning, delimiter matching, composition, and diagnostics for parser stages.
    """

    def _lowest_precedence_operator(self, start: int, end: int) -> int | None:
        """寻找表达式顶层绑定最弱的二元/赋值运算符。
        Find the top-level binary or assignment operator with the weakest binding precedence.
        """
        significant = self._significant(start, end)
        depth_round = depth_square = depth_brace = 0
        best: tuple[int, int] | None = None
        for position, index in enumerate(significant):
            text = self.lexemes[index].text
            if text == "(":
                depth_round += 1
                continue
            if text == ")":
                depth_round = max(0, depth_round - 1)
                continue
            if text == "[":
                depth_square += 1
                continue
            if text == "]":
                depth_square = max(0, depth_square - 1)
                continue
            if text == "{":
                depth_brace += 1
                continue
            if text == "}":
                depth_brace = max(0, depth_brace - 1)
                continue
            if depth_round or depth_square or depth_brace:
                continue
            precedence = _BINARY_PRECEDENCE.get(text)
            if precedence is None:
                continue
            # 一元 +/-/*/& 出现在表达式开头或另一个运算符之后，不当成 binary。
            # Unary +/-/*/& at expression start or after another operator is not binary.
            if text in {"+", "-", "*", "&"}:
                previous = significant[position - 1] if position else None
                if (
                    previous is None
                    or self.lexemes[previous].text in _BINARY_PRECEDENCE
                    or self.lexemes[previous].text in {"(", "[", "{", ",", "?", ":"}
                ):
                    continue
            if best is None or precedence <= best[0]:
                best = (precedence, index)
        return None if best is None else best[1]

    def _find_unit_end(self, start: int, end: int, *, context: str) -> int:
        """从当前 unit 起点向后扫描到顶层声明/语句边界。
        Scan forward from one unit start until its top-level declaration/statement boundary.
        """
        first = self._next_significant(start, end)
        if first is None:
            return end
        first_text = self.lexemes[first].text

        if first_text in _CONTROL | {"do"}:
            return self._control_unit_end(first, end)

        depth_round = depth_square = 0
        for index in range(first, min(end, len(self.lexemes))):
            item = self.lexemes[index]
            if item.trivia or item.kind == "comment":
                continue
            text = item.text
            if text == "(":
                depth_round += 1
            elif text == ")":
                depth_round = max(0, depth_round - 1)
            elif text == "[":
                depth_square += 1
            elif text == "]":
                depth_square = max(0, depth_square - 1)
            elif text == ";" and depth_round == 0 and depth_square == 0:
                return index + 1
            elif text == "{" and depth_round == 0 and depth_square == 0 and index in self._pairs:
                close = self._pairs[index]
                if first_text in {"class", "struct", "union", "enum"}:
                    semicolon = self._next_significant(close + 1, end)
                    return (
                        semicolon + 1
                        if semicolon is not None and self.lexemes[semicolon].text == ";"
                        else close + 1
                    )
                # direct-list initialization 要继续找到 ;，函数/namespace 则在 } 结束。
                # Direct-list initialization continues through the semicolon, while function and
                # namespace bodies end at the closing brace.
                previous = self._previous_significant(index - 1, start)
                if (
                    previous is not None
                    and self.lexemes[previous].text not in {")", "try", "else", "do"}
                    and first_text not in {"namespace", "extern"}
                ):
                    semicolon = self._next_significant(close + 1, end)
                    if semicolon is not None and self.lexemes[semicolon].text == ";":
                        return semicolon + 1
                return close + 1
        return end

    def _control_unit_end(self, start: int, end: int) -> int:
        """寻找控制流语句末尾，避免把 body 内分号误当外层结束。
        Find the end of a control-flow statement without treating body semicolons as the outer terminator.
        """
        cursor = start + 1
        open_paren = self._next_significant(cursor, end)
        if (
            open_paren is not None
            and self.lexemes[open_paren].text == "("
            and open_paren in self._pairs
        ):
            cursor = self._pairs[open_paren] + 1
        body = self._next_significant(cursor, end)
        if body is None:
            return end
        if self.lexemes[body].text == "{" and body in self._pairs:
            result = self._pairs[body] + 1
        else:
            result = self._find_unit_end(body, end, context="block")
        if self.lexemes[start].text == "if":
            else_index = self._next_significant(result, end)
            if else_index is not None and self.lexemes[else_index].text == "else":
                else_body = self._next_significant(else_index + 1, end)
                if (
                    else_body is not None
                    and self.lexemes[else_body].text == "{"
                    and else_body in self._pairs
                ):
                    result = self._pairs[else_body] + 1
                elif else_body is not None:
                    result = self._find_unit_end(else_body, end, context="block")
        return result

    def _split_top_level(
        self,
        start: int,
        end: int,
        separator: str,
        *,
        angle_brackets: bool = False,
    ) -> list[tuple[int, int]]:
        """按不位于嵌套分隔符内的 separator 切分连续源码区间。
        Split a source range on separators outside the requested nested delimiters.
        """
        result: list[tuple[int, int]] = []
        part_start = start
        round_depth = square_depth = brace_depth = angle_depth = 0
        for index in self._significant(start, end):
            text = self.lexemes[index].text
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
            elif angle_brackets and text == "<":
                angle_depth += 1
            elif angle_brackets and text == ">" and angle_depth:
                angle_depth -= 1
            elif angle_brackets and text == ">>" and angle_depth:
                angle_depth = max(0, angle_depth - 2)
            elif text == separator and not (
                round_depth or square_depth or brace_depth or angle_depth
            ):
                result.append((part_start, index))
                part_start = index + 1
        if part_start <= end:
            result.append((part_start, end))
        return result

    def _find_top_level_token(self, start: int, end: int, token: str) -> int | None:
        """在当前区间顶层寻找指定 token。
        Find the requested token at the current nesting level.
        """
        round_depth = square_depth = brace_depth = 0
        for index in self._significant(start, end):
            text = self.lexemes[index].text
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
            elif text == token and not (round_depth or square_depth or brace_depth):
                return index
        return None

    def _match_angle(self, opening: int, end: int) -> int | None:
        """为 template 参数列表匹配角括号，并正确处理 `>>`。
        Match template angle brackets, including a >> token that closes two nested levels.
        """
        depth = 0
        for index in self._significant(opening, end):
            text = self.lexemes[index].text
            if text == "<":
                depth += 1
            elif text == ">":
                depth -= 1
            elif text == ">>":
                depth -= 2
            if depth <= 0:
                return index
        self._diagnostic(
            tr("unclosed template argument list", "未闭合的模板参数列表"),
            opening,
            min(opening + 1, end),
        )
        return None

    def _enclosing_open(self, index: int, token: str, lower_bound: int) -> int | None:
        """向左寻找包围某 token 的指定开括号。
        Find the matching enclosing opening delimiter to the left of a token.
        """
        for candidate in range(index, lower_bound - 1, -1):
            if (
                self.lexemes[candidate].text == token
                and candidate in self._pairs
                and self._pairs[candidate] >= index
            ):
                return candidate
        return None

    def _before_trailing_semicolon(self, start: int, end: int) -> int:
        """返回去掉尾部分号后的 lexeme 结束位置。
        Return the lexeme position immediately before a trailing semicolon.
        """
        last = self._previous_significant(end - 1, start)
        if last is not None and self.lexemes[last].text == ";":
            return last
        return end

    def _trim(self, start: int, end: int) -> tuple[int, int] | None:
        """去掉区间两端 trivia/comment，但不改变内部源码。
        Trim trivia/comments from both ends of a range without modifying its interior source.
        """
        first = self._next_significant(start, end)
        if first is None:
            return None
        last = self._previous_significant(end - 1, first)
        if last is None:
            return None
        return first, last + 1

    def _index_significant(self) -> None:
        """预先算出有效 lexeme（非空白、非注释）的下标，以及每个位置前后最近的有效 lexeme。
        Precompute the indices of significant lexemes (not whitespace, not comments) and the
        nearest significant lexeme before and after each position.
        """
        count = len(self.lexemes)
        significant = [
            index
            for index, item in enumerate(self.lexemes)
            if not item.trivia and item.kind != "comment"
        ]
        following = [count] * (count + 1)
        preceding = [-1] * count
        cursor = 0
        for index in significant:
            for position in range(cursor, index + 1):
                following[position] = index
            cursor = index + 1
        cursor = -1
        for index in significant:
            for position in range(cursor + 1, index):
                preceding[position] = cursor
            preceding[index] = index
            cursor = index
        for position in range(cursor + 1, count):
            preceding[position] = cursor
        self._significant_indices = significant
        self._following = following
        self._preceding = preceding
        # 普通 lexeme 在 compose 中总是以同一条无 field 的边出现，预先建好以便整段复用。
        # A plain lexeme always appears in compose as the same edge without a field, so the
        # edges are built once and reused in slices.
        self._plain_children = [_child(item.green()) for item in self.lexemes]

    def _significant(self, start: int, end: int) -> list[int]:
        """返回排除空白和注释后的 lexeme 索引。
        Return lexeme indices after excluding trivia and comments.
        """
        indices = self._significant_indices
        low = bisect_left(indices, max(0, start))
        high = bisect_left(indices, min(end, len(self.lexemes)))
        return indices[low:high]

    def _next_significant(self, start: int, end: int) -> int | None:
        """向右寻找下一个非 trivia/comment lexeme。
        Find the next non-trivia, non-comment lexeme to the right.
        """
        start = max(0, start)
        limit = min(end, len(self.lexemes))
        if start >= limit:
            return None
        index = self._following[start]
        return index if index < limit else None

    def _previous_significant(self, start: int, lower_bound: int) -> int | None:
        """向左寻找上一个非 trivia/comment lexeme。
        Find the previous non-trivia, non-comment lexeme to the left.
        """
        upper = min(start, len(self.lexemes) - 1)
        if upper < lower_bound or upper < 0:
            return None
        index = self._preceding[upper]
        return index if index >= max(lower_bound, 0) else None

    def _line_prefix_is_trivia(self, index: int, lower_bound: int) -> bool:
        """判断 `#` 前直到行首是否只有空白。
        Return whether only whitespace appears between the line start and the # token.
        """
        cursor = index - 1
        while cursor >= lower_bound:
            item = self.lexemes[cursor]
            if item.trivia and ("\n" in item.text or "\r" in item.text):
                return True
            if not item.trivia:
                return False
            cursor -= 1
        return True

    def _text(self, start: int, end: int) -> str:
        """返回 lexeme 区间的原始源码文本。
        Return the original source text for a lexeme range.
        """
        return "".join(item.text for item in self.lexemes[start:end])

    def _compose(
        self,
        kind: str,
        start: int,
        end: int,
        replacements: Iterable[_Replacement],
    ) -> GreenNode:
        """用不重叠结构节点替换原 token 区间并构造一个 GreenNode。
        Compose non-overlapping structured replacements into a GreenNode while preserving untouched source.
        """
        ordered = _deduplicate_replacements(
            replacement
            for replacement in replacements
            if start <= replacement.start < replacement.end <= end
        )
        plain = self._plain_children
        children: list[GreenChild] = []
        cursor = start
        for replacement in ordered:
            children += plain[cursor : replacement.start]
            children.append(_child(replacement.element, replacement.field))
            cursor = replacement.end
        children += plain[cursor:end]
        return _node(kind, tuple(children))

    def _diagnostic(self, message: str, start: int, end: int) -> None:
        """以 lexeme 字节范围记录结构 parser 诊断。
        Record a parser diagnostic for the current lexeme byte range.
        """
        if not self.lexemes:
            span = SourceSpan(0, 0)
        else:
            start_byte = self.lexemes[min(start, len(self.lexemes) - 1)].start
            end_index = min(max(start, end - 1), len(self.lexemes) - 1)
            end_byte = self.lexemes[end_index].end
            span = SourceSpan(start_byte, end_byte)
        self.diagnostics.append(Diagnostic(message, span, SourcePoint(0, 0), None))


def _deduplicate_replacements(replacements: Iterable[_Replacement]) -> list[_Replacement]:
    """按源码顺序保留互不重叠的 replacement；优先更早、更大的结构。
    Keep non-overlapping replacements in source order, preferring earlier and larger structures.
    """
    ordered = sorted(replacements, key=lambda item: (item.start, -(item.end - item.start)))
    result: list[_Replacement] = []
    cursor = -1
    for replacement in ordered:
        if replacement.start < cursor:
            continue
        result.append(replacement)
        cursor = replacement.end
    return result
