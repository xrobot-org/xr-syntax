"""C++ parser 内部的语句与表达式结构解析。
Internal C++ parser implementation for statements and expression structure.
"""

from __future__ import annotations

from xr_syntax.core import GreenElement, GreenNode
from xr_syntax.core.green import green_token
from xr_syntax.cpp._ranges import BRACKETS, deduplicate_replacements, empty_expression
from xr_syntax.cpp._support import ParserSupport, Replacement
from xr_syntax.cpp.lexer import BINARY_PRECEDENCE, LITERAL_KINDS

# 出现在表达式开头或这些 token 之后的 + - * & 是一元运算符。
# + - * & at the start of an expression or after these tokens are unary operators.
_UNARY_CAPABLE = frozenset({"+", "-", "*", "&"})
_OPERAND_OPENERS = frozenset({"(", "[", "{", ",", "?", ":"})
_COMPARISONS_ENDING_IN_EQUAL = frozenset({"==", "!=", "<=", ">="})
# 二元运算符 token 按文本共享：kind 就是运算符文本（and/or/xor 也一样），不是 named。
# Binary operator tokens are shared by text: the kind is the operator text (and/or/xor too) and
# they are not named.
_OPERATOR_TOKENS = {text: green_token(text, text, False) for text in BINARY_PRECEDENCE}
_CONTROL_KINDS = {
    "if": "if_statement",
    "for": "for_statement",
    "while": "while_statement",
    "switch": "switch_statement",
    "catch": "catch_clause",
}
_MEMBER_ACCESS = ("::", ".", "->")


# 这一层只对能够可靠判断的结构做细分；无法安全分类的表达式统一保留为
# source_expression，并继续尽量识别内部不重叠调用，避免“猜错 AST”。
# This layer only refines structures it can classify reliably; anything else stays a
# source_expression, and calls inside it that do not overlap are still recognized.
class ExpressionMixin(ParserSupport):
    """解析 compound statement、控制流、调用和常见表达式结构。
    Parse compound statements, control flow, calls, and common expression structures.
    """

    def _expression_replacement(
        self,
        start: int,
        end: int,
        field: str | None = None,
    ) -> Replacement | None:
        """构造与 expression 实际覆盖范围严格一致的 replacement。
        Create an expression replacement whose span exactly matches the trivia-trimmed expression node.
        """
        trimmed = self._trim(start, end)
        if trimmed is None:
            return None
        return (trimmed[0], trimmed[1], self._parse_expression(*trimmed), field)

    def _parse_compound(self, open_brace: int, close_brace: int) -> GreenNode:
        """解析函数/控制流复合语句，并递归结构化内部声明与调用。
        Parse a function/control-flow compound statement and recursively structure declarations and calls inside it.
        """
        replacements = self._parse_scope(open_brace + 1, close_brace, context="block")
        return self._compose("compound_statement", open_brace, close_brace + 1, replacements)

    def _parse_return(self, start: int, end: int) -> Replacement:
        """解析 return 语句及返回表达式。
        Parse a return statement together with its returned expression.
        """
        low, high = self._span(start, end)
        semicolon = self._sig[high - 1] if self._stext[high - 1] == ";" else end
        expression_start = self._next_significant(self._sig[low] + 1, semicolon)
        replacements: list[Replacement] = []
        if expression_start is not None:
            replacement = self._expression_replacement(expression_start, semicolon)
            if replacement is not None:
                replacements.append(replacement)
        return (start, end, self._compose("return_statement", start, end, replacements), None)

    def _parse_control(self, start: int, end: int, keyword: str) -> Replacement:
        """解析 if/for/while/switch/catch 的条件和复合 body。
        Parse the condition and compound body of if/for/while/switch/catch constructs.
        """
        low, high = self._span(start, end)
        replacements: list[Replacement] = []
        cursor = start + 1
        try:
            open_paren: int | None = self._sig[self._stext.index("(", low + 1, high)]
        except ValueError:
            open_paren = None
        close_paren = self._pairs.get(open_paren, end) if open_paren is not None else end
        if open_paren is not None and close_paren < end:
            condition_start = self._next_significant(open_paren + 1, close_paren)
            if condition_start is not None:
                replacement = self._expression_replacement(
                    condition_start, close_paren, "condition"
                )
                if replacement is not None:
                    replacements.append(replacement)
            cursor = close_paren + 1

        body_open = self._next_significant(cursor, end)
        if body_open is not None and self._texts[body_open] == "{":
            body_close = self._pairs.get(body_open, end)
            if body_close < end:
                body = self._parse_compound(body_open, body_close)
                replacements.append((body_open, body_close + 1, body, "consequence"))

        node = self._compose(_CONTROL_KINDS[keyword], start, end, replacements)
        return (start, end, node, None)

    def _parse_do(self, start: int, end: int) -> Replacement:
        """解析 do/while 结构；body 内部仍递归解析。
        Parse a do/while construct while recursively structuring its body.
        """
        replacements: list[Replacement] = []
        body_open = self._next_significant(start + 1, end)
        if body_open is not None and self._texts[body_open] == "{" and body_open in self._pairs:
            body_close = self._pairs[body_open]
            body = self._parse_compound(body_open, body_close)
            replacements.append((body_open, body_close + 1, body, "body"))
        return (start, end, self._compose("do_statement", start, end, replacements), None)

    def _parse_concept(self, start: int, end: int) -> Replacement:
        """解析 concept 定义，并继续解析等号后的表达式。
        Parse a concept definition and continue parsing the expression after =.
        """
        equal = self._find_top_level_token(start, end, "=")
        replacements: list[Replacement] = []
        if equal is not None:
            value_end = self._before_trailing_semicolon(start, end)
            value_start = self._next_significant(equal + 1, value_end)
            if value_start is not None:
                replacement = self._expression_replacement(value_start, value_end, "value")
                if replacement is not None:
                    replacements.append(replacement)
        return (start, end, self._compose("concept_definition", start, end, replacements), None)

    def _parse_expression(
        self, start: int, end: int, operators: list[tuple[int, int]] | None = None
    ) -> GreenElement:
        """解析常见表达式；不能细分时保留为 source_expression。
        Parse common expression forms, falling back to source_expression when finer classification is unsafe.

        Args:
            start: 区间起点（lexeme 下标）。
                The start of the range (a lexeme index).
            end: 区间终点（不含）。
                The end of the range (exclusive).
            operators: 已知时传入区间顶层运算符（_operators 的结果），省去重新扫描。
                The top-level operators of the range (as _operators returns them) when already
                known, which saves scanning them again.
        """
        low, high = self._span(start, end)
        if low >= high:
            return empty_expression()
        start = self._sig[low]
        end = self._sig[high - 1] + 1
        if not self._enter(start, end):
            return self._compose("source_expression", start, end, [])
        node = self._atomic_expression(start, end, low, high)
        if node is None:
            if operators is None:
                operators = self._operators(low, high)
            if operators:
                node = self._binary(start, end, low, high, operators)
            if node is None:
                node = self._expression_tail(start, end, low, high)
        self._depth -= 1
        return node

    def _atomic_expression(self, start: int, end: int, low: int, high: int) -> GreenElement | None:
        """由开头 token 整体决定的表达式：lambda、requires、co_await/new/delete、括号表达式。
        Expressions decided as a whole by their first token: lambda, requires, co_await/new/delete
        and parenthesized expressions.

        Args:
            start: 去掉两端空白后的起点；low/high 是对应的有效 lexeme 位置范围。
                The trimmed start; low/high is the matching position range of significant
                lexemes.
            end: 去掉两端空白后的终点。
                The trimmed end.
            low: 第一个有效 lexeme 的位置。
                The position of the first significant lexeme.
            high: 最后一个有效 lexeme 之后的位置。
                The position after the last significant lexeme.

        Returns:
            表达式节点；开头 token 不决定整体时为 None。
            The expression node, or None when the first token does not decide the whole.
        """
        first_text = self._stext[low]
        pairs = self._pairs
        # 先处理有明显前导关键字/定界符的表达式，这些形式不需要依赖
        # 名称解析或类型信息即可安全识别。
        # Expressions with an obvious leading keyword or delimiter come first; they are
        # recognized safely without name lookup or type information.
        if first_text == "[" and start in pairs:
            body_open = self._first_paired(low, high, "{")
            if body_open is not None and pairs[body_open] < end:
                body_close = pairs[body_open]
                body = self._parse_compound(body_open, body_close)
                return self._compose(
                    "lambda_expression", start, end, [(body_open, body_close + 1, body, "body")]
                )
        if first_text == "requires":
            body_open = self._first_paired(low, high, "{")
            replacements: list[Replacement] = []
            if body_open is not None and pairs[body_open] < end:
                body_close = pairs[body_open]
                body = self._parse_compound(body_open, body_close)
                replacements.append((body_open, body_close + 1, body, "body"))
            return self._compose("requires_expression", start, end, replacements)
        if first_text in ("co_await", "new", "delete"):
            return self._compose(first_text + "_expression", start, end, [])
        if first_text == "(" and pairs.get(start) == end - 1:
            if "..." in self._stext[low:high]:
                return self._compose("fold_expression", start, end, [])
            replacements = []
            inner_start = self._next_significant(start + 1, end - 1)
            if inner_start is not None:
                replacement = self._expression_replacement(inner_start, end - 1)
                if replacement is not None:
                    replacements.append(replacement)
            return self._compose("parenthesized_expression", start, end, replacements)
        return None

    def _first_paired(self, low: int, high: int, text: str) -> int | None:
        """位置范围内第一个已配对的指定开括号。
        The first paired opening delimiter with the given text in a position range.
        """
        stext = self._stext
        sig = self._sig
        pairs = self._pairs
        position = low
        while True:
            try:
                position = stext.index(text, position, high)
            except ValueError:
                return None
            if sig[position] in pairs:
                return sig[position]
            position += 1

    def _operators(self, low: int, high: int) -> list[tuple[int, int]]:
        """表达式顶层的二元/赋值运算符：(优先级, 位置)，按源码顺序。
        The top-level binary and assignment operators of an expression as (precedence,
        position), in source order.

        出现在表达式开头或另一个运算符之后的一元 +/-/*/& 不算二元运算符。深度为 0 的括号组整组跳过。
        Unary +/-/*/& at the start of the expression or after another operator are not binary
        operators. Delimiter groups at depth 0 are skipped as a whole.
        """
        stext = self._stext
        result: list[tuple[int, int]] = []
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
            elif not (round_depth or square_depth or brace_depth):
                precedence = BINARY_PRECEDENCE.get(text)
                if precedence is not None and not (
                    text in _UNARY_CAPABLE
                    and (
                        position == low
                        or stext[position - 1] in BINARY_PRECEDENCE
                        or stext[position - 1] in _OPERAND_OPENERS
                    )
                ):
                    result.append((precedence, position))
            position += 1
        return result

    def _binary(
        self, start: int, end: int, low: int, high: int, operators: list[tuple[int, int]]
    ) -> GreenElement | None:
        """按绑定最弱的运算符把表达式拆成二元/赋值表达式；无法拆分时返回 None。
        Split an expression at its weakest-binding operators into binary or assignment
        expressions; None when it cannot be split.

        同一优先级的一串运算符用循环建树，不随运算符个数递归：赋值右结合（a = (b = c)），
        其余左结合（(a + b) + c）。各段表达式直接拿到自己那一段的运算符，不再重新扫描。
        A run of operators of the same precedence is built in a loop instead of recursing once per
        operator: assignment is right-associative (a = (b = c)), the rest left-associative
        ((a + b) + c). Each operand segment gets its own slice of the operators instead of being
        scanned again.
        """
        minimum = min(precedence for precedence, _ in operators)
        chain = [index for index, (precedence, _) in enumerate(operators) if precedence == minimum]
        if minimum == BINARY_PRECEDENCE["="]:
            return self._assignment_chain(start, end, low, high, operators, chain)
        return self._left_chain(start, end, low, high, operators, chain)

    def _left_chain(
        self,
        start: int,
        end: int,
        low: int,
        high: int,
        operators: list[tuple[int, int]],
        chain: list[int],
    ) -> GreenElement | None:
        """左结合的一串同优先级运算符：每个运算符左边是前面整串，右边是到下一个运算符为止的一段。
        A left-associative run of operators of one precedence: the left operand of each operator
        is everything before it, the right operand the segment up to the next operator.

        与逐层在最右边的最弱运算符处拆分得到的树相同，包括某一层左段或右段为空时，
        那一层整体退回调用/源码表达式。chain 是这串运算符在 operators 中的下标。
        The tree is the same as splitting level by level at the rightmost weakest operator,
        including that a level whose left or right part is empty falls back as a whole to a
        call/source expression. chain holds the indices of the run in operators.
        """
        sig = self._sig
        count = len(chain)
        positions = [operators[index][1] for index in chain]
        # 每层的终点：最外层是整个表达式，其余是下一个运算符之前最后一个有效 lexeme 之后。
        # Each level's end: the whole expression for the outermost level, otherwise just after
        # the last significant lexeme before the next operator.
        ends = [sig[positions[level + 1] - 1] + 1 for level in range(count - 1)] + [end]
        limits = positions[1:] + [high]
        # 自外向内找第一层拆不开的：左段为空（运算符在开头）或右段为空。
        # Find, from the outside in, the first level that cannot be split: an empty left part
        # (the operator comes first) or an empty right part.
        failed = -1
        for level in range(count - 1, -1, -1):
            if positions[level] == low or positions[level] + 1 >= limits[level]:
                failed = level
                break
        if failed == count - 1:
            return None
        if failed >= 0:
            node = self._expression_tail(start, ends[failed], low, limits[failed])
        else:
            node = self._parse_expression(start, sig[positions[0] - 1] + 1, operators[: chain[0]])
        for level in range(failed + 1, count):
            position = positions[level]
            right_start = sig[position + 1]
            following = chain[level + 1] if level + 1 < count else len(operators)
            right = self._parse_expression(
                right_start, ends[level], operators[chain[level] + 1 : following]
            )
            node = self._binary_node(
                start,
                ends[level],
                (start, sig[position - 1] + 1, node),
                sig[position],
                (right_start, ends[level], right),
            )
        return node

    def _assignment_chain(
        self,
        start: int,
        end: int,
        low: int,
        high: int,
        operators: list[tuple[int, int]],
        chain: list[int],
    ) -> GreenElement | None:
        """右结合的一串赋值运算符：每个赋值左边是前一段，右边是其后的整个表达式。
        A right-associative run of assignment operators: the left operand of each assignment is
        the segment before it, the right operand everything after it.

        右侧每一段先按完整表达式的开头规则检查（lambda、new、括号等）；左段或右段为空的那一层
        整体退回调用/源码表达式。chain 是这串运算符在 operators 中的下标。
        Each right-hand part is first checked against the rules for the start of a whole
        expression (lambda, new, parentheses and so on); a level whose left or right part is empty
        falls back as a whole to a call/source expression. chain holds the indices of the run in
        operators.
        """
        sig = self._sig
        levels: list[tuple[int, int, GreenElement]] = []
        tail: GreenElement | None = None
        level_start = start
        level_low = low
        previous = -1
        for number, index in enumerate(chain):
            position = operators[index][1]
            if number:
                tail = self._atomic_expression(level_start, end, level_low, high)
                if tail is not None:
                    break
            if position == level_low or position + 1 >= high:
                if not number:
                    return None
                tail = self._expression_tail(level_start, end, level_low, high)
                break
            left = self._parse_expression(
                level_start, sig[position - 1] + 1, operators[previous + 1 : index]
            )
            levels.append((level_start, position, left))
            level_start = sig[position + 1]
            level_low = position + 1
            previous = index
        if tail is None:
            tail = self._parse_expression(level_start, end, operators[previous + 1 :])
        node = tail
        for level_start, position, left in reversed(levels):
            node = self._binary_node(
                level_start,
                end,
                (level_start, sig[position - 1] + 1, left),
                sig[position],
                (sig[position + 1], end, node),
            )
        return node

    def _binary_node(
        self,
        start: int,
        end: int,
        left: tuple[int, int, GreenElement],
        operator: int,
        right: tuple[int, int, GreenElement],
    ) -> GreenNode:
        """组合一个二元或赋值表达式节点。
        Compose one binary or assignment expression node.
        """
        text = self._texts[operator]
        assignment = text.endswith("=") and text not in _COMPARISONS_ENDING_IN_EQUAL
        return self._compose(
            "assignment_expression" if assignment else "binary_expression",
            start,
            end,
            [
                (left[0], left[1], left[2], "left"),
                (operator, operator + 1, _OPERATOR_TOKENS[text], "operator"),
                (right[0], right[1], right[2], "right"),
            ],
        )

    def _expression_tail(self, start: int, end: int, low: int, high: int) -> GreenElement:
        """没有可拆分的运算符时：调用表达式、单个 token，或保留为 source_expression。
        Without an operator to split at: a call expression, a single token, or a
        source_expression.
        """
        # call suffix 只在顶层括号匹配明确时识别，callee 自身只建立
        # qualified/field/source_expression 等源码结构，不做 name lookup。
        # A call suffix is only recognized when its top-level parentheses match clearly; the
        # callee gets only source structure (qualified/field/source_expression), no name lookup.
        call = self._find_call_suffix(start, end)
        if call is not None:
            open_paren, close_paren = call
            callee_range = self._trim(start, open_paren)
            if callee_range is not None:
                callee = self._parse_callee(*callee_range)
                arguments = self._parse_argument_list(open_paren, close_paren)
                return self._compose(
                    "call_expression",
                    start,
                    end,
                    [
                        (callee_range[0], callee_range[1], callee, "function"),
                        (open_paren, close_paren + 1, arguments, "arguments"),
                    ],
                )

        if high - low == 1:
            index = self._sig[low]
            kind = self._infos[index][0]
            if kind == "identifier" or kind in LITERAL_KINDS:
                return self._plain[index].element

        # 最后保守 fallback：整体仍是 source_expression，但把其中可以确定
        # 边界的调用提升成子节点，供 XR_REGISTER 等查询使用。
        # The conservative fallback: the whole stays a source_expression, but calls whose bounds
        # are certain become child nodes for queries such as XR_REGISTER.
        return self._compose("source_expression", start, end, self._scan_nested_calls(start, end))

    def _parse_callee(self, start: int, end: int) -> GreenElement:
        """给调用目标建立轻量结构；不做名称解析。
        Build lightweight structure for a call target without performing name resolution.
        """
        low, high = self._span(start, end)
        if high - low == 1 and self._infos[self._sig[low]][0] == "identifier":
            return self._plain[self._sig[low]].element
        texts = self._stext[low:high]
        if "::" in texts:
            return self._compose("qualified_identifier", start, end, [])
        if "." in texts or "->" in texts:
            return self._compose("field_expression", start, end, [])
        return self._compose("source_expression", start, end, [])

    def _parse_argument_list(self, open_paren: int, close_paren: int) -> GreenNode:
        """解析调用实参列表，使每个实参都可单独查询/重写。
        Parse a call argument list so each argument can be queried or rewritten independently.
        """
        replacements: list[Replacement] = []
        for part_start, part_end in self._split_top_level(open_paren + 1, close_paren, ","):
            trimmed = self._trim(part_start, part_end)
            if trimmed is not None:
                argument = self._parse_expression(*trimmed)
                replacements.append((trimmed[0], trimmed[1], argument, None))
        return self._compose("argument_list", open_paren, close_paren + 1, replacements)

    def _scan_nested_calls(self, start: int, end: int) -> list[Replacement]:
        """在未完整分类的表达式中保守识别不重叠的调用。
        Conservatively recognize non-overlapping calls inside an expression that remains otherwise generic.

        先只按区间选出互不重叠的调用（更早、更大的优先），再只解析选中的那些；
        被更大调用包含的内层调用会在外层调用里解析。
        First the non-overlapping calls are chosen by range alone (earlier and larger first), and
        only those are parsed; inner calls contained in a larger call are parsed inside it.
        """
        stext = self._stext
        sig = self._sig
        infos = self._infos
        pairs = self._pairs
        low, high = self._span(start, end)
        candidates: list[tuple[int, int]] = []
        position = low
        while True:
            try:
                position = stext.index("(", position, high)
            except ValueError:
                break
            close = pairs.get(sig[position], end)
            if close < end and position != low:
                previous = position - 1
                if infos[sig[previous]][0] == "identifier" or stext[previous] in (">", ")", "]"):
                    callee = previous
                    while callee - 2 >= low and stext[callee - 1] in _MEMBER_ACCESS:
                        callee -= 2
                    candidates.append((sig[callee], close + 1))
            position += 1
        result: list[Replacement] = []
        for call_start, call_end in deduplicate_replacements(candidates):
            result.append(
                (call_start, call_end, self._parse_expression(call_start, call_end), None)
            )
        return result
