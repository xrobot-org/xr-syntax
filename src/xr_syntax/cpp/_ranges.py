"""C++ parser 内部的区间、分隔符与 green-tree compose 工具。
Internal C++ parser helpers for source ranges, delimiters, replacements, and green-tree composition.
"""

from __future__ import annotations

from typing import Any, TypeVar

from xr_syntax.core import GreenChild, GreenElement, GreenNode, SourceSpan
from xr_syntax.core.green import green_child, green_node
from xr_syntax.cpp._support import ParserSupport, Replacement
from xr_syntax.i18n import tr

_Ranged = TypeVar("_Ranged", bound=tuple[Any, ...])

# Replacement 是 (start, end, element, field)：用结构元素替换 lexeme 区间 [start, end)。
# 用普通元组而不是类，因为每次解析要创建上万个。
# Replacement is (start, end, element, field): a structural element replacing the lexeme range
# [start, end). It is a plain tuple rather than a class because one parse creates tens of
# thousands of them.

# _split_top_level / _find_top_level_token 关心的分隔符；其他 token 直接跳过。
# The delimiters _split_top_level and _find_top_level_token track; other tokens are skipped.
BRACKETS = frozenset("()[]{}")
_OPENING_BRACKETS = frozenset("([{")
_ANGLE_BRACKETS = frozenset(("<", ">", ">>"))


class RangeMixin(ParserSupport):
    """提供 parser 各阶段共享的区间扫描、匹配、compose 与诊断操作。
    Provide shared range scanning, delimiter matching, composition, and diagnostics for parser stages.

    区间用 lexeme 下标 [start, end) 表示；扫描在有效 lexeme（非空白、非注释）数组上按位置进行：
    _rank[i] 是下标 i 之前的有效 lexeme 个数，所以 [start, end) 内的有效 lexeme 是位置
    _rank[start] 到 _rank[end] 之间的 _sig 项。
    Ranges are lexeme indices [start, end); scanning walks the array of significant lexemes (not
    whitespace, not comments) by position: _rank[i] is the number of significant lexemes before
    index i, so the significant lexemes in [start, end) are the _sig items at positions _rank[start]
    up to _rank[end].
    """

    def _span(self, start: int, end: int) -> tuple[int, int]:
        """lexeme 区间 [start, end) 内有效 lexeme 的位置范围 [low, high)。
        The position range [low, high) of the significant lexemes in the lexeme range [start, end).
        """
        count = self._count
        rank = self._rank
        return (
            rank[0 if start < 0 else count if start > count else start],
            rank[0 if end < 0 else count if end > count else end],
        )

    def _significant(self, start: int, end: int) -> list[int]:
        """返回排除空白和注释后的 lexeme 索引。
        Return lexeme indices after excluding trivia and comments.
        """
        low, high = self._span(start, end)
        return self._sig[low:high]

    def _next_significant(self, start: int, end: int) -> int | None:
        """向右寻找下一个非 trivia/comment lexeme。
        Find the next non-trivia, non-comment lexeme to the right.
        """
        count = self._count
        if start < 0:
            start = 0
        limit = end if end < count else count
        if start >= limit:
            return None
        position = self._rank[start]
        sig = self._sig
        if position < len(sig):
            index = sig[position]
            if index < limit:
                return index
        return None

    def _previous_significant(self, start: int, lower_bound: int) -> int | None:
        """向左寻找上一个非 trivia/comment lexeme。
        Find the previous non-trivia, non-comment lexeme to the left.
        """
        upper = start if start < self._count - 1 else self._count - 1
        if upper < lower_bound or upper < 0:
            return None
        position = self._rank[upper + 1] - 1
        if position >= 0:
            index = self._sig[position]
            if index >= (lower_bound if lower_bound > 0 else 0):
                return index
        return None

    def _line_prefix_is_trivia(self, index: int, lower_bound: int) -> bool:
        """判断 `#` 前直到行首是否只有空白和注释；注释在预处理前已换成空格，跨行的块注释也一样。
        Return whether only whitespace and comments come between the line start and the # token;
        comments become a space before preprocessing, block comments across lines too.
        """
        texts = self._texts
        infos = self._infos
        cursor = index - 1
        while cursor >= lower_bound:
            kind, _, trivia = infos[cursor]
            if kind == "comment":
                cursor -= 1
                continue
            if not trivia:
                return False
            text = texts[cursor]
            if "\n" in text or "\r" in text:
                return True
            cursor -= 1
        return True

    def _text(self, start: int, end: int) -> str:
        """返回 lexeme 区间的原始源码文本。
        Return the original source text for a lexeme range.
        """
        return "".join(self._texts[start:end])

    def _trim(self, start: int, end: int) -> tuple[int, int] | None:
        """去掉区间两端 trivia/comment，但不改变内部源码。
        Trim trivia/comments from both ends of a range without modifying its interior source.
        """
        low, high = self._span(start, end)
        if low >= high:
            return None
        sig = self._sig
        return sig[low], sig[high - 1] + 1

    def _before_trailing_semicolon(self, start: int, end: int) -> int:
        """返回去掉尾部分号后的 lexeme 结束位置。
        Return the lexeme position immediately before a trailing semicolon.
        """
        low, high = self._span(start, end)
        if high > low and self._stext[high - 1] == ";":
            return self._sig[high - 1]
        return end

    def _skip_group(self, position: int, high: int) -> int:
        """跳过 position 处的括号组。
        Skip the delimiter group at position.

        position 处是已配对、内部没有多余闭括号的开括号时，返回其闭括号之后的位置（不超过
        high），否则返回 position + 1。
        The position after the closing delimiter when position holds a paired opening delimiter
        whose group contains no stray closing delimiter (at most high), and position + 1 otherwise.

        这样的括号组内部所有括号都成对出现，从各类深度都为 0 处进入时，跳过整组与逐个计数的结果
        相同：组内深度始终大于 0，出组后回到 0。
        Inside such a group every delimiter comes in pairs, so entered with every depth at 0,
        skipping the whole group gives the same result as counting through it: the depth stays
        above 0 inside and returns to 0 after it.
        """
        opening = self._sig[position]
        close = self._pairs.get(opening)
        if close is None or opening in self._dirty:
            return position + 1
        after = self._rank[close] + 1
        return after if after < high else high

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
        stext = self._stext
        sig = self._sig
        low, high = self._span(start, end)
        position = low
        while position < high:
            text = stext[position]
            if text in BRACKETS:
                # 深度为 0 时整组跳过；尖括号只在括号外计数，(1 > 2) 里的 > 不关闭模板实参。
                # At depth 0 a group is skipped as a whole; angle brackets count only outside
                # brackets, so the > in (1 > 2) closes no template argument list.
                if text in _OPENING_BRACKETS and not (round_depth or square_depth or brace_depth):
                    skipped = self._skip_group(position, high)
                    if skipped != position + 1:
                        position = skipped
                        continue
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
                else:
                    brace_depth = max(0, brace_depth - 1)
            elif (
                angle_brackets
                and text in _ANGLE_BRACKETS
                and not (round_depth or square_depth or brace_depth)
            ):
                if text == "<":
                    angle_depth += 1
                elif angle_depth:
                    angle_depth = angle_depth - 1 if text == ">" else max(0, angle_depth - 2)
            elif text == separator and not (
                round_depth or square_depth or brace_depth or angle_depth
            ):
                index = sig[position]
                result.append((part_start, index))
                part_start = index + 1
            position += 1
        if part_start <= end:
            result.append((part_start, end))
        return result

    def _find_top_level_token(self, start: int, end: int, token: str) -> int | None:
        """在当前区间顶层寻找指定 token。
        Find the requested token at the current nesting level.
        """
        stext = self._stext
        low, high = self._span(start, end)
        round_depth = square_depth = brace_depth = 0
        position = low
        while position < high:
            text = stext[position]
            if text in BRACKETS:
                if text in "([{" and not (round_depth or square_depth or brace_depth):
                    skipped = self._skip_group(position, high)
                    if skipped != position + 1:
                        position = skipped
                        continue
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
                else:
                    brace_depth = max(0, brace_depth - 1)
            elif text == token and not (round_depth or square_depth or brace_depth):
                return self._sig[position]
            position += 1
        return None

    def _match_angle(self, opening: int, end: int) -> int | None:
        """为 template 参数列表匹配角括号，并正确处理 `>>`；括号组内的 < 和 > 不计。
        Match template angle brackets, including a >> token that closes two nested levels;
        < and > inside a bracket group do not count.
        """
        stext = self._stext
        depth = 0
        low, high = self._span(opening, end)
        position = low
        while position < high:
            text = stext[position]
            if text in _OPENING_BRACKETS:
                position = self._skip_group(position, high)
                continue
            if text == "<":
                depth += 1
            elif text == ">":
                depth -= 1
            elif text == ">>":
                depth -= 2
            if depth <= 0:
                return self._sig[position]
            position += 1
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
        if index < lower_bound:
            return None
        pairs = self._pairs
        stext = self._stext
        sig = self._sig
        rank = self._rank
        count = self._count
        position = rank[index + 1 if index < count else count] - 1
        low = rank[lower_bound if lower_bound > 0 else 0]
        while position >= low:
            candidate = sig[position]
            if stext[position] == token and pairs.get(candidate, -1) >= index:
                return candidate
            position -= 1
        return None

    def _compose(
        self,
        kind: str,
        start: int,
        end: int,
        replacements: list[Replacement],
    ) -> GreenNode:
        """用不重叠结构节点替换原 token 区间并构造一个 GreenNode。
        Compose non-overlapping structured replacements into a GreenNode while preserving untouched source.

        区间外的 replacement 被忽略；重叠时按 deduplicate_replacements 取舍。
        Replacements outside the range are ignored; overlapping ones are chosen as
        deduplicate_replacements does.
        """
        plain = self._plain
        offsets = self._offsets
        children: list[GreenChild] = []
        cursor = start
        # 常见情况：replacement 都在区间内，按起点严格递增且互不重叠，一遍组合完成。
        # The common case: every replacement lies in the range, in strictly increasing start
        # order and without overlap, so one pass composes the node.
        for item_start, item_end, element, field in replacements:
            if item_start < cursor or not (start <= item_start < item_end <= end):
                break
            children += plain[cursor:item_start]
            children.append(green_child(element, field))
            cursor = item_end
        else:
            children += plain[cursor:end]
            return green_node(kind, tuple(children), offsets[end] - offsets[start])
        ordered = deduplicate_replacements(
            [item for item in replacements if start <= item[0] < item[1] <= end]
        )
        children = []
        cursor = start
        for item_start, item_end, element, field in ordered:
            children += plain[cursor:item_start]
            children.append(green_child(element, field))
            cursor = item_end
        children += plain[cursor:end]
        return green_node(kind, tuple(children), offsets[end] - offsets[start])

    def _diagnostic(self, message: str, start: int, end: int) -> None:
        """以 lexeme 字节范围记录结构 parser 诊断。
        Record a parser diagnostic for the current lexeme byte range.
        """
        if not self._count:
            span = SourceSpan(0, 0)
        else:
            last = self._count - 1
            offsets = self._offsets
            end_index = min(max(start, end - 1), last)
            span = SourceSpan(offsets[min(start, last)], offsets[end_index + 1])
        self.diagnostics.append(self._lexed.diagnostic(message, span))


def deduplicate_replacements(replacements: list[_Ranged]) -> list[_Ranged]:
    """按源码顺序保留互不重叠的 replacement；优先更早、更大的结构。
    Keep non-overlapping replacements in source order, preferring earlier and larger structures.

    项的前两项是区间 [start, end)；replacement 和只有区间的二元组都可以。
    The first two items of each entry are the range [start, end); replacements and plain range
    pairs both work.
    """
    # 调用方给出的 replacement 几乎总是已经按起点严格递增且互不重叠；这时排序和过滤都不改变结果。
    # The replacements callers pass are almost always already in strictly increasing start order
    # and non-overlapping; sorting and filtering then change nothing.
    previous_start = cursor = -1
    for item in replacements:
        if item[0] < cursor or item[0] <= previous_start:
            break
        previous_start = item[0]
        cursor = item[1]
    else:
        return replacements
    ordered = sorted(replacements, key=lambda item: (item[0], -(item[1] - item[0])))
    result: list[_Ranged] = []
    cursor = -1
    for item in ordered:
        if item[0] < cursor:
            continue
        result.append(item)
        cursor = item[1]
    return result


def empty_expression() -> GreenElement:
    """没有任何有效 token 的表达式。
    An expression without any significant token.
    """
    return GreenNode("source_expression", (), named=True)
