"""C++ parser 内部的函数/变量 declarator 识别辅助。
Internal C++ parser helpers for recognizing function and variable declarators.
"""

from __future__ import annotations

from xr_syntax.core import GreenElement
from xr_syntax.core.green import green_node, green_token
from xr_syntax.cpp._support import ParserSupport, Replacement
from xr_syntax.cpp.lexer import CONTROL, LITERAL_KINDS, QUALIFIERS, STORAGE, TYPE_WORDS

# 这些名字后面的括号不是函数参数列表。
# Parentheses after these names are no function parameter list.
_NOT_FUNCTION_NAMES = frozenset(
    {
        "sizeof",
        "alignof",
        "alignas",
        "decltype",
        "noexcept",
        "requires",
        "explicit",
        "static_assert",
        "__attribute__",
        "__declspec",
    }
)
# 函数参数列表之前不会出现的顶层记号。
# Top-level tokens that never come before a function parameter list.
_DECLARATOR_STOPS = frozenset({"=", "{", ";"})
_TYPE_STORAGE_QUALIFIER = frozenset(TYPE_WORDS | STORAGE | QUALIFIERS)
_DECLARATION_START = frozenset(
    STORAGE | QUALIFIERS | TYPE_WORDS | {"constexpr", "consteval", "constinit", "using", "typedef"}
)
# 名字之前出现这些运算符时不再猜成声明；pointer/reference punctuator 属于 declarator。
# These operators before the name stop the declaration guess; pointer/reference punctuators belong
# to the declarator.
_EXPRESSION_OPERATORS = frozenset(
    {
        "+",
        "-",
        "/",
        "%",
        "^",
        "|",
        "||",
        "and",
        "or",
        "xor",
        "?",
        "=",
        "==",
        "!=",
        "<=>",
        "<<",
        ".",
        "->",
    }
)
_FUNCTION_SPECIFIERS = frozenset(
    STORAGE | {"inline", "constexpr", "consteval", "extern", "friend", "virtual", "explicit"}
)
_ARGUMENT_OPERATORS = frozenset({"+", "-", "/", "%", "?"})
TYPE_KEYWORDS = frozenset({"class", "struct", "union", "enum"})
# 后面括号里是属性的词。
# Words whose following parentheses hold attributes.
ATTRIBUTE_WORDS = frozenset({"alignas", "__attribute__", "__declspec"})
_ELABORATED = frozenset(TYPE_KEYWORDS | {"typename"})
_POINTER_OPERATORS = frozenset({"*", "&", "&&"})
_OPENING = frozenset({"(", "[", "{"})
_AFTER_VARIABLE_NAME = frozenset({"=", "(", "{", "[", ",", ";"})


class DeclaratorMixin(ParserSupport):
    """提供函数、参数、变量名称与声明形态的 source-level 判定。
    Provide source-level recognition of function/parameter/variable names and declarator shapes.
    """

    _variable_names: dict[tuple[int, int], int | None]

    def _find_function_parameter_list(
        self, start: int, end: int
    ) -> tuple[int, int, int, int] | None:
        """找到声明中的主 function parameter list 及函数名区间。
        Locate the primary function parameter list and the source range of the function name.

        参数列表在顶层的 =、{ 和 ; 之前（int x_ = compute(y); 和 Foo bar_{make(z)}; 都不是
        函数），也不在模板实参里（std::function<void()> cb_; 不是函数）。
        The parameter list comes before a top-level =, { and ; (neither int x_ = compute(y); nor
        Foo bar_{make(z)}; is a function) and outside template arguments
        (std::function<void()> cb_; is no function).

        Returns:
            (参数列表的 (, 其 ), 函数名起点, 函数名终点)，都是 lexeme 下标。
            (the ( of the parameter list, its ), name start, name end), all lexeme indices.
        """
        stext = self._stext
        sig = self._sig
        pairs = self._pairs
        low, high = self._span(start, end)
        angles = 0
        position = low
        while position < high:
            text = stext[position]
            if text == "operator" and not angles:
                return self._operator_parameter_list(position, high, end)
            if text == "(":
                index = sig[position]
                close = pairs.get(index)
                if not angles and close is not None and close < end and position != low:
                    name = self._function_name_range(start, sig[position - 1] + 1)
                    if name is not None:
                        return index, close, name[0], name[1]
                position = self._skip_group(position, high)
                continue
            if text == "[" or (angles and text == "{"):
                position = self._skip_group(position, high)
                continue
            if text == "<":
                angles += 1
            elif text == ">" or text == ">>":
                angles = max(0, angles - len(text))
            elif not angles and text in _DECLARATOR_STOPS:
                return None
            position += 1
        return None

    def _operator_parameter_list(
        self, position: int, high: int, end: int
    ) -> tuple[int, int, int, int] | None:
        """operator 函数的参数列表和名字：名字从 operator 到参数列表的 ( 之前。
        The parameter list and the name of an operator function: the name runs from operator to
        the ( of the parameter list.

        operator() 的第一对括号属于名字；operator bool、operator const char* 这样的转换函数
        名字含类型。
        The first pair of parentheses of operator() belongs to the name; conversion functions
        such as operator bool and operator const char* have a type in the name.
        """
        stext = self._stext
        sig = self._sig
        following = position + 1
        if following + 1 < high and stext[following] == "(" and stext[following + 1] == ")":
            following += 2
        while following < high and stext[following] != "(":
            following += 1
        if following >= high or following == position + 1:
            return None
        index = sig[following]
        close = self._pairs.get(index)
        if close is None or close >= end:
            return None
        return index, close, sig[position], sig[following - 1] + 1

    def _function_name_range(self, start: int, end: int) -> tuple[int, int] | None:
        """紧挨 end 之前的函数名或析构函数名的源码范围；不像函数名时返回 None。
        The source range of the function or destructor name right before end; None when it does
        not look like a function name.
        """
        last = self._previous_significant(end - 1, start)
        if last is not None and self._texts[last] == ")":
            # 括号里的函数名 bool (isinf)(T x) 避开同名函数式宏；名字范围包括括号。
            # A parenthesized function name bool (isinf)(T x) avoids a function-like macro of
            # the same name; the name range includes the parentheses.
            opening = self._reverse_pairs.get(last)
            inner = None if opening is None else self._next_significant(opening + 1, last)
            if (
                opening is None
                or inner is None
                or self._next_significant(inner + 1, last) is not None
                or self._infos[inner][0] != "identifier"
                or self._texts[inner] in TYPE_WORDS
            ):
                return None
            return opening, last + 1
        if last is None or self._infos[last][0] != "identifier":
            return None
        text = self._texts[last]
        if text in TYPE_WORDS or text in CONTROL or text in _NOT_FUNCTION_NAMES:
            return None
        before = self._previous_significant(last - 1, start)
        if before is not None and self._texts[before] == "~":
            return before, last + 1
        return last, last + 1

    def _name_element(self, start: int, end: int) -> GreenElement:
        """函数名范围的语法元素：普通名字、析构函数名、运算符函数名或带括号的名字。
        The syntax element of a function name range: an identifier, destructor_name,
        operator_name or parenthesized_declarator.
        """
        if self._texts[start] == "(":
            inner = self._next_significant(start + 1, end)
            assert inner is not None
            name = green_token("identifier", self._texts[inner], True)
            return self._compose(
                "parenthesized_declarator", start, end, [(inner, inner + 1, name, "declarator")]
            )
        stripped = self._text(start, end).strip()
        if stripped.startswith("operator") or stripped.startswith("~"):
            kind = "operator_name" if stripped.startswith("operator") else "destructor_name"
            offsets = self._offsets
            return green_node(kind, tuple(self._plain[start:end]), offsets[end] - offsets[start])
        return green_token("identifier", stripped, True)

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
        for start, end in self._split_top_level(
            open_paren + 1, close_paren, ",", angle_brackets=True
        ):
            # 默认实参属于 parameter initializer，不参与“声明还是实参”的判定；模板实参和数组
            # 边界里的字面量属于类型（std::array<int, 2> a、int (&a)[3]）。
            # Default arguments belong to the parameter initializer and do not make a
            # function prototype look like a call; literals in template arguments and array
            # bounds belong to the type (std::array<int, 2> a, int (&a)[3]).
            equal = self._find_top_level_token(start, end, "=")
            low, high = self._span(start, equal if equal is not None else end)
            # 参数以类型开头；(*cb_) 这样的括号是声明子，不是参数列表。
            # A parameter starts with its type; parentheses such as (*cb_) are a declarator,
            # not a parameter list.
            if low < high and stext[low] in _POINTER_OPERATORS:
                return False
            angles = 0
            position = low
            while position < high:
                text = stext[position]
                if text == "[" or (angles and text in ("(", "{")):
                    position = self._skip_group(position, high)
                    continue
                if text == "<":
                    angles += 1
                elif text == ">" or text == ">>":
                    angles = max(0, angles - len(text))
                elif not angles and (
                    infos[sig[position]][0] in LITERAL_KINDS or text in _ARGUMENT_OPERATORS
                ):
                    return False
                position += 1
            # `f(Type)` 合法，`object(arg)` 也可能；按 C++ most-vexing-parse 倾向函数。
            # Both forms are possible; follow the C++ most-vexing-parse bias toward a function
            # declaration.
        return True

    def _find_parameter_name(self, start: int, end: int, *, template: bool) -> int | None:
        """从参数 declarator 中定位名字，不把函数指针后面的参数类型误认成名字。
        Locate a parameter declarator name without mistaking function-pointer parameter types for
        the name.

        名字是类型之后的标识符：int x 和 Foo x 的名字是 x，Foo& 和 const uint8_t* 没有名字。
        模板参数中 typename 和 class 之后就是名字。
        The name is an identifier after the type: the name of int x and Foo x is x, Foo& and
        const uint8_t* have no name. In a template parameter the name follows typename or class.
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
                and stext[position] not in TYPE_WORDS
                and stext[position - 1] in _POINTER_OPERATORS
                and self._enclosing_open(sig[position - 1], "(", start) is not None
            ):
                return index

        name: int | None = None
        typed = False
        angles = 0
        position = low
        while position < high:
            text = stext[position]
            if text in _OPENING:
                position = self._skip_group(position, high)
                continue
            if text == "<":
                angles += 1
            elif text == ">" or text == ">>":
                angles = max(0, angles - len(text))
            elif angles or infos[sig[position]][0] != "identifier" or text in QUALIFIERS:
                pass
            elif text in _ELABORATED:
                typed = typed or (template and text in ("typename", "class"))
            elif (
                typed
                and text not in TYPE_WORDS
                and (position == low or stext[position - 1] != "::")
                and (position + 1 == high or stext[position + 1] != "::")
            ):
                name = sig[position]
            else:
                typed = True
            position += 1
        return name

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

    def _parenthesized_declarator_name(self, start: int, end: int) -> int | None:
        """void (*fp)(int) 和 int (&a)[3] 这类括号声明子里的名字；没有时返回 None。
        The name inside a parenthesized declarator such as void (*fp)(int) or int (&a)[3]; None
        without one.

        括号前有类型，括号后是参数列表或数组边界，括号里名字紧跟 *、& 或 &&；只看顶层的 =、{
        和 ; 之前。
        A type comes before the parentheses, a parameter list or an array bound after them, and
        inside them the name follows *, & or &&; only the part before a top-level =, { or ; is
        searched.
        """
        stext = self._stext
        sig = self._sig
        infos = self._infos
        rank = self._rank
        low, high = self._span(start, end)
        position = low + 1
        while position < high:
            text = stext[position]
            if text in _DECLARATOR_STOPS:
                return None
            if text == "(":
                close = self._pairs.get(sig[position])
                if close is not None and close < end:
                    after = rank[close] + 1
                    if after < high and stext[after] in ("(", "["):
                        inner = position + 1
                        while inner < after - 1:
                            if stext[inner] in _OPENING:
                                inner = self._skip_group(inner, after - 1)
                                continue
                            if (
                                stext[inner - 1] in _POINTER_OPERATORS
                                and infos[sig[inner]][0] == "identifier"
                                and stext[inner] not in TYPE_WORDS
                            ):
                                return sig[inner]
                            inner += 1
            if text in _OPENING:
                position = self._skip_group(position, high)
                continue
            position += 1
        return None

    def _variable_name(self, start: int, end: int) -> int | None:
        """_find_variable_name 的实际计算。
        The actual computation behind _find_variable_name.
        """
        nested = self._parenthesized_declarator_name(start, end)
        if nested is not None:
            return nested
        stext = self._stext
        sig = self._sig
        infos = self._infos
        search_end = end
        equal = self._find_top_level_token(start, end, "=")
        if equal is not None:
            search_end = equal
        else:
            # direct-init/list-init 的第一个顶层括号属于 initializer，名字一定在它之前；
            # 类型关键字之后的 { 是类型体（typedef struct {...} Name;），名字在它之后。
            # The first top-level direct/list-init delimiter starts the initializer, so the
            # declarator name must appear before it; a { after a type keyword is a type body
            # (typedef struct {...} Name;) and the name comes after it.
            pairs = self._pairs
            low, high = self._span(start, end)
            type_body = False
            position = low
            while position < high:
                text = stext[position]
                if text in TYPE_KEYWORDS:
                    type_body = True
                elif text in ("(", "{") and pairs.get(sig[position], end) < end:
                    if text == "(" and position > low and stext[position - 1] in ATTRIBUTE_WORDS:
                        position = self._skip_group(position, high)
                        continue
                    if text == "{" and type_body:
                        type_body = False
                        position = self._skip_group(position, high)
                        continue
                    search_end = sig[position]
                    break
                position += 1
        low, high = self._span(start, search_end)
        candidates: list[int] = []
        position = low
        while position < high:
            text = stext[position]
            if text in _OPENING:
                position = self._skip_group(position, high)
                continue
            # 限定名的最后一段在声明子位置上时是名字（Foo::count_ = 0），否则属于类型
            # （std::string s）。
            # The last part of a qualified name is the name in declarator position
            # (Foo::count_ = 0), and part of the type otherwise (std::string s).
            at_end = position + 1 >= high or stext[position + 1] in _AFTER_VARIABLE_NAME
            if (
                infos[sig[position]][0] == "identifier"
                and text not in _TYPE_STORAGE_QUALIFIER
                and text not in ATTRIBUTE_WORDS
                and not (position > low and stext[position - 1] == "::" and not at_end)
                and not (position + 1 < high and stext[position + 1] == "::")
            ):
                candidates.append(position)
            position += 1
        # 开头的属性（[[nodiscard]]、alignas(4)）之后的第一个记号决定单个候选能否是名字。
        # The first token after leading attributes ([[nodiscard]], alignas(4)) decides whether a
        # single candidate can be the name.
        lead = low
        while lead < high:
            if stext[lead] == "[":
                lead = self._skip_group(lead, high)
            elif stext[lead] in ATTRIBUTE_WORDS and lead + 1 < high and stext[lead + 1] == "(":
                lead = self._skip_group(lead + 1, high)
            else:
                break
        if not candidates or (
            len(candidates) == 1
            and stext[lead] not in _TYPE_STORAGE_QUALIFIER
            and not self._follows_type(candidates[0], lead)
        ):
            return None
        for position in reversed(candidates):
            if position + 1 >= high or stext[position + 1] in _AFTER_VARIABLE_NAME:
                return sig[position]
        return sig[candidates[-1]] if len(candidates) >= 2 else None

    def _follows_type(self, position: int, low: int) -> bool:
        """名字前面像类型：跳过名字的限定、*、&、&& 和 cv 限定后是标识符或 >（std::string s）。
        Whether a type seems to come before the name at position: after skipping the name's
        qualification, *, &, && and cv-qualifiers, an identifier or > (std::string s,
        std::vector<int> v).
        """
        stext = self._stext
        infos = self._infos
        sig = self._sig
        before = position - 1
        while (
            before - 1 >= low
            and stext[before] == "::"
            and infos[sig[before - 1]][0] == "identifier"
        ):
            before -= 2
        while before >= low and (
            stext[before] in _POINTER_OPERATORS or stext[before] in QUALIFIERS
        ):
            before -= 1
        return before >= low and (
            stext[before] in (">", ">>") or infos[sig[before]][0] == "identifier"
        )

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

    def _specifier_replacements(self, start: int, end: int) -> list[Replacement]:
        """把 storage/type qualifier 包装成稳定 named node，供 convenience view 查询。
        Build structured replacements for storage-class and type qualifiers.
        """
        result: list[Replacement] = []
        stext = self._stext
        low, high = self._span(start, end)
        for position in range(low, high):
            word = stext[position]
            if word in STORAGE or word in QUALIFIERS:
                kind = "storage_class_specifier" if word in STORAGE else "type_qualifier"
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

    def _special_member_clause(self, start: int, end: int) -> Replacement | None:
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
