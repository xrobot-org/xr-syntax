"""C++ parser 内部的函数/变量 declarator 识别辅助。
Internal C++ parser helpers for recognizing function and variable declarators.
"""

from __future__ import annotations

from xr_syntax.core import GreenElement
from xr_syntax.core.green import _node, _token

from ._support import _ParserSupport, _Replacement
from .lexer import _CONTROL, _LITERAL_KINDS, _QUALIFIERS, _STORAGE, _TYPE_WORDS

# 这些名字后面的括号不是函数参数列表。
# Parentheses after these names are no function parameter list.
_NOT_FUNCTION_NAMES = frozenset({"sizeof", "alignof", "decltype", "noexcept", "requires"})
_TYPE_STORAGE_QUALIFIER = frozenset(_TYPE_WORDS | _STORAGE | _QUALIFIERS)
_DECLARATION_START = frozenset(
    _STORAGE
    | _QUALIFIERS
    | _TYPE_WORDS
    | {"constexpr", "consteval", "constinit", "using", "typedef"}
)
# 名字之前出现这些运算符时不再猜成声明；pointer/reference punctuator 属于 declarator。
# These operators before the name stop the declaration guess; pointer/reference punctuators belong
# to the declarator.
_EXPRESSION_OPERATORS = frozenset(
    {"+", "-", "/", "%", "^", "|", "||", "and", "or", "xor", "?", "=", "==", "!=", "<=>"}
)
_FUNCTION_SPECIFIERS = frozenset(
    _STORAGE | {"inline", "constexpr", "consteval", "extern", "friend", "virtual", "explicit"}
)
_ARGUMENT_OPERATORS = frozenset({"+", "-", "/", "%", "?"})
_AFTER_VARIABLE_NAME = frozenset({"=", "(", "{", "[", ",", ";"})


class _DeclaratorMixin(_ParserSupport):
    """提供函数、参数、变量名称与声明形态的 source-level 判定。
    Provide source-level recognition of function/parameter/variable names and declarator shapes.
    """

    _variable_names: dict[tuple[int, int], int | None]

    def _find_function_parameter_list(
        self, start: int, end: int
    ) -> tuple[int, int, int, int] | None:
        """找到声明中的主 function parameter list 及函数名区间。
        Locate the primary function parameter list and the source range of the function name.
        """
        stext = self._stext
        sig = self._sig
        pairs = self._pairs
        low, high = self._span(start, end)
        position = low
        while True:
            # list.index 在 C 里找下一个 (。
            # list.index finds the next ( in C.
            try:
                position = stext.index("(", position, high)
            except ValueError:
                return None
            index = sig[position]
            close = pairs.get(index)
            if close is not None and close < end and position != low:
                name_start, name_end = self._function_name_range(start, sig[position - 1] + 1)
                if name_start is not None:
                    name_text = self._text(name_start, name_end).strip()
                    if name_text not in _CONTROL and name_text not in _NOT_FUNCTION_NAMES:
                        return index, close, name_start, name_end
            position += 1

    def _function_name_range(self, start: int, end: int) -> tuple[int | None, int]:
        """识别普通函数名、析构名和 operator 名称的源码范围。
        Locate the source range of a normal function, destructor, or operator name.
        """
        last = self._previous_significant(end - 1, start)
        if last is None:
            return None, end
        before = self._previous_significant(last - 1, start)
        before_text = None if before is None else self._texts[before]
        if self._infos[last][0] == "identifier":
            if before_text in ("~", "operator"):
                return before, last + 1
            return last, last + 1
        if before_text == "operator":
            return before, last + 1
        return None, end

    def _name_element(self, start: int, end: int) -> GreenElement:
        """为函数名范围选择 identifier/destructor_name/operator_name。
        Choose the syntax element kind for a function, destructor, or operator name.
        """
        stripped = self._text(start, end).strip()
        if stripped.startswith("operator") or stripped.startswith("~"):
            kind = "operator_name" if stripped.startswith("operator") else "destructor_name"
            offsets = self._offsets
            return _node(kind, tuple(self._plain[start:end]), offsets[end] - offsets[start])
        return _token("identifier", stripped, True)

    def _prototype_is_function(
        self,
        start: int,
        end: int,
        open_paren: int,
        close_paren: int,
        name_start: int,
        context: str,
    ) -> bool:
        """区分函数声明和 `Type object(args);` 直接初始化。
        Distinguish a function declaration from direct object initialization.
        """
        name_text = self._text(name_start, open_paren).strip()
        if name_text.startswith("operator"):
            return True
        if context == "class" and name_text.startswith("~"):
            return True
        return self._parameter_list_looks_declarative(open_paren, close_paren)

    def _parameter_list_looks_declarative(self, open_paren: int, close_paren: int) -> bool:
        """粗粒度判断括号内容更像参数声明还是构造实参。
        Conservatively decide whether parentheses contain parameter declarations rather than constructor arguments.
        """
        stext = self._stext
        sig = self._sig
        infos = self._infos
        for start, end in self._split_top_level(open_paren + 1, close_paren, ","):
            # 默认实参属于 parameter initializer，不参与“声明还是实参”的判定。
            # Default arguments belong to the parameter initializer and do not make a
            # function prototype look like a call.
            equal = self._find_top_level_token(start, end, "=")
            low, high = self._span(start, equal if equal is not None else end)
            for position in range(low, high):
                if (
                    infos[sig[position]][0] in _LITERAL_KINDS
                    or stext[position] in _ARGUMENT_OPERATORS
                ):
                    return False
            # `f(Type)` 合法，`object(arg)` 也可能；按 C++ most-vexing-parse 倾向函数。
            # Both forms are possible; follow the C++ most-vexing-parse bias toward a function
            # declaration.
        return True

    def _find_parameter_name(self, start: int, end: int) -> int | None:
        """从参数 declarator 中定位名字，不把函数指针后面的参数类型误认成名字。
        Locate a parameter declarator name without mistaking function-pointer parameter types for the name.
        """
        low, high = self._span(start, end)
        if low >= high:
            return None
        sig = self._sig
        stext = self._stext
        infos = self._infos

        # 优先识别 `(*cb)` / `(&arr)` / `(C::*cb)` 这类嵌套 declarator。
        # Recognize nested declarators such as `(*cb)`, `(&arr)`, and `(C::*cb)` first.
        for position in range(low + 1, high):
            index = sig[position]
            if (
                infos[index][0] == "identifier"
                and stext[position] not in _TYPE_WORDS
                and stext[position - 1] in ("*", "&", "&&")
                and self._enclosing_open(sig[position - 1], "(", start) is not None
            ):
                return index

        candidates: list[int] = []
        angle_depth = 0
        for position in range(low, high):
            text = stext[position]
            if text == "<":
                angle_depth += 1
                continue
            if angle_depth:
                if text == ">":
                    angle_depth -= 1
                elif text == ">>":
                    angle_depth = max(0, angle_depth - 2)
                continue
            index = sig[position]
            if (
                infos[index][0] == "identifier"
                and text not in _TYPE_WORDS
                and (position == low or stext[position - 1] != "::")
                and (position + 1 == high or stext[position + 1] != "::")
            ):
                candidates.append(index)
        if not candidates:
            return None
        if len(candidates) == 1:
            if stext[low] in ("typename", "class"):
                return candidates[0]
            # 单个自定义类型且没有 declarator 时通常是匿名参数。
            # A lone custom type without a declarator is usually an unnamed parameter.
            if candidates[0] == sig[low] and high - low == 1:
                return None
        return candidates[-1]

    def _find_variable_name(self, start: int, end: int) -> int | None:
        """识别常见变量 declarator 的名字，并忽略 initializer 内部的标识符。
        Recognize a common variable declarator name while ignoring identifiers inside its initializer.

        声明判断和声明解析对同一区间各问一次，结果按区间缓存。
        The declaration test and the declaration parse ask once each for the same range, so the
        result is cached per range.
        """
        key = (start, end)
        cached = self._variable_names.get(key, -1)
        if cached != -1:
            return cached
        result = self._variable_name(start, end)
        self._variable_names[key] = result
        return result

    def _variable_name(self, start: int, end: int) -> int | None:
        """_find_variable_name 的实际计算。
        The actual computation behind _find_variable_name.
        """
        stext = self._stext
        sig = self._sig
        infos = self._infos
        search_end = end
        equal = self._find_top_level_token(start, end, "=")
        if equal is not None:
            search_end = equal
        else:
            # direct-init/list-init 的第一个顶层括号属于 initializer，名字一定在它之前。
            # The first top-level direct/list-init delimiter starts the initializer, so the
            # declarator name must appear before it.
            pairs = self._pairs
            low, high = self._span(start, end)
            for position in range(low, high):
                if stext[position] in ("(", "{") and pairs.get(sig[position], end) < end:
                    search_end = sig[position]
                    break
        low, high = self._span(start, search_end)
        candidates: list[int] = []
        for position in range(low, high):
            index = sig[position]
            if infos[index][0] != "identifier":
                continue
            if stext[position] in _TYPE_STORAGE_QUALIFIER:
                continue
            if position > low and stext[position - 1] == "::":
                continue
            if position + 1 < high and stext[position + 1] == "::":
                continue
            candidates.append(position)
        if len(candidates) < 2 and high > low and stext[low] not in _TYPE_STORAGE_QUALIFIER:
            return None
        for position in reversed(candidates):
            if position + 1 >= high or stext[position + 1] in _AFTER_VARIABLE_NAME:
                return sig[position]
        return sig[candidates[-1]] if len(candidates) >= 2 else None

    def _looks_like_declaration(self, start: int, end: int, *, context: str) -> bool:
        """用保守启发式判断一个分号单元是否像声明。
        Conservatively decide whether a semicolon-terminated source unit should be treated as a declaration without name lookup.
        """
        low, high = self._span(start, end)
        if low >= high:
            return False
        stext = self._stext
        first_index = self._sig[low]
        first = stext[low]
        if first in _DECLARATION_START:
            return True

        content_end = self._before_trailing_semicolon(start, end)
        name = self._find_variable_name(start, content_end)
        if name is None:
            return False

        # 名字之前出现真正的表达式运算符时，不再猜成声明。
        # If a real expression operator appears before the candidate name, stop treating
        # the source as a declaration.
        name_low, name_high = self._span(first_index + 1, name)
        for position in range(name_low, name_high):
            if stext[position] in _EXPRESSION_OPERATORS:
                return False

        if context in ("top", "class"):
            return True

        prefix = self._text(first_index, name).strip()
        if "::" in prefix or first.endswith("_t"):
            return True
        if first and first[0].isupper():
            return True

        # `Foo value;` 这类两个 identifier 连续出现，本身不构成合法普通表达式。
        # Two adjacent identifiers such as `Foo value;` do not form a normal valid
        # expression by themselves.
        before_name = self._previous_significant(name - 1, first_index)
        return before_name is not None and self._infos[before_name][0] == "identifier"

    def _specifier_replacements(self, start: int, end: int) -> list[_Replacement]:
        """把 storage/type qualifier 包装成稳定 named node，供 convenience view 查询。
        Build structured replacements for storage-class and type qualifiers.
        """
        result: list[_Replacement] = []
        stext = self._stext
        low, high = self._span(start, end)
        for position in range(low, high):
            word = stext[position]
            if word in _STORAGE or word in _QUALIFIERS:
                kind = "storage_class_specifier" if word in _STORAGE else "type_qualifier"
                index = self._sig[position]
                result.append((index, index + 1, self._compose(kind, index, index + 1, []), None))
        return result

    def _type_range(self, start: int, name_start: int) -> tuple[int, int] | None:
        """提取函数声明中 return type 的源码区间。
        Extract the source range spelling the function return type.
        """
        low, high = self._span(start, name_start)
        stext = self._stext
        position = low
        while position < high and stext[position] in _FUNCTION_SPECIFIERS:
            position += 1
        if position >= high:
            return None
        return self._sig[position], name_start

    def _special_member_clause(self, start: int, end: int) -> _Replacement | None:
        """识别 `= delete` / `= default` 子句。
        Recognize an = delete or = default special-member clause.
        """
        equal = self._find_top_level_token(start, end, "=")
        if equal is None:
            return None
        word = self._next_significant(equal + 1, end)
        if word is None:
            return None
        text = self._texts[word]
        if text not in ("delete", "default"):
            return None
        kind = "delete_method_clause" if text == "delete" else "default_method_clause"
        return (equal, word + 1, self._compose(kind, equal, word + 1, []), None)

    def _find_call_suffix(self, start: int, end: int) -> tuple[int, int] | None:
        """如果整个表达式以一次函数调用结束，返回其实参括号。
        Return the argument-parenthesis pair when the entire expression ends in one function call.
        """
        low, high = self._span(start, end)
        if high - low < 3:
            return None
        stext = self._stext
        if stext[high - 1] != ")":
            return None
        sig = self._sig
        last = sig[high - 1]
        opening = self._reverse_pairs.get(last)
        if opening is None or opening <= sig[low]:
            return None
        position = self._rank[opening] - 1
        if self._infos[sig[position]][0] == "identifier" or stext[position] in (">", ")", "]"):
            return opening, last
        return None
