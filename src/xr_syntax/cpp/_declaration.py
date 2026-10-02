"""C++ parser 内部的声明单元、函数与参数解析。
Internal C++ parser stages for declaration units, functions, and parameters.
"""

from __future__ import annotations

from xr_syntax.core import GreenElement, GreenNode
from xr_syntax.core.green import _token

from ._declarator import _TYPE_KEYWORDS
from ._support import _ParserSupport, _Replacement
from .lexer import _CONTROL, _STORAGE, _TYPE_WORDS

# 函数声明子 ) 之后仍属于 declarator 的修饰词。
# Words after the ) of a function declarator that still belong to the declarator.
_DECLARATOR_SUFFIXES = frozenset({"const", "volatile", "noexcept", "override", "final", "&", "&&"})
# 构造函数成员初始化列表的 : 之前的记号：参数列表的 )、noexcept 和函数 try 块的 try。
# The tokens before the : of a constructor's member initializer list: the ) of the parameter
# list, noexcept, and the try of a function try block.
_BEFORE_INITIALIZERS = frozenset({")", "noexcept", "try"})
_UNIT_CONTEXTS = frozenset({"top", "class", "block"})


class _DeclarationMixin(_ParserSupport):
    """把单元区间分类成声明、函数或语句，并解析参数列表。
    Classify unit ranges as declarations, functions, or statements and parse parameter lists.
    """

    def _parse_unit(self, start: int, end: int, *, context: str) -> _Replacement | None:
        """把一个完整声明/语句区间分类成具体结构节点。
        Classify one complete declaration/statement range into a concrete structural node.
        """
        low, high = self._span(start, end)
        if low >= high:
            return None
        first = self._stext[low]

        if first == "return":
            return self._parse_return(start, end)
        if first in _CONTROL:
            return self._parse_control(start, end, first)
        if first == "do":
            return self._parse_do(start, end)
        if first == "break" or first == "continue":
            return (start, end, self._compose(first + "_statement", start, end, []), None)
        if first == "{" and context == "block":
            # 函数体里单独的 { ... } 是一个复合语句。
            # A lone { ... } in a function body is a compound statement.
            opening = self._sig[low]
            close = self._pairs.get(opening)
            if close == self._sig[high - 1]:
                return (opening, close + 1, self._parse_compound(opening, close), None)
        if (first == "case" or first == "default") and self._stext[high - 1] == ":":
            # 标签之后的语句是同级的下一个节点。
            # The statement after the label is the next sibling node.
            replacements: list[_Replacement] = []
            if first == "case":
                value = self._expression_replacement(
                    self._sig[low + 1], self._sig[high - 1], "value"
                )
                if value is not None:
                    replacements.append(value)
            return (start, end, self._compose("case_label", start, end, replacements), None)
        if first == "concept":
            return self._parse_concept(start, end)

        # C++ 不允许 block-scope function definition；这里优先把 `foo(args);`
        # 解释为表达式调用，避免把普通调用误判成局部函数声明。
        # C++ forbids block-scope function definitions, so prefer interpreting
        # `foo(args);` as an expression call instead of a local function declaration.
        if context != "block":
            function = self._parse_function(start, end, context=context)
            if function is not None:
                return function

        if context in _UNIT_CONTEXTS and self._looks_like_declaration(start, end, context=context):
            declaration = self._parse_declaration(start, end)
            if declaration is not None:
                if context == "block":
                    wrapper = self._compose(
                        "declaration_statement",
                        start,
                        end,
                        [(start, end, declaration[2], None)],
                    )
                    return (start, end, wrapper, None)
                return declaration

        replacement = self._expression_replacement(
            start, self._before_trailing_semicolon(start, end)
        )
        node = self._compose(
            "expression_statement",
            start,
            end,
            [] if replacement is None else [replacement],
        )
        return (start, end, node, None)

    def _parse_function(self, start: int, end: int, *, context: str) -> _Replacement | None:
        """识别函数定义/声明，并构造 function_declarator 与参数结构。
        Recognize a function declaration/definition and build its function_declarator and parameter structure.
        """
        candidate = self._find_function_parameter_list(start, end)
        if candidate is None:
            return None
        open_paren, close_paren, name_start, name_end = candidate
        pairs = self._pairs
        body_open = self._function_body(close_paren, end)
        if body_open is None and not self._prototype_is_function(
            start, end, open_paren, close_paren, name_start, context
        ):
            return None

        parameters = self._parse_parameter_list(open_paren, close_paren)
        name_element = self._name_element(name_start, name_end)
        declarator_end = close_paren + 1
        while True:
            next_index = self._next_significant(
                declarator_end, body_open if body_open is not None else end
            )
            if next_index is None:
                break
            text = self._texts[next_index]
            if text in _DECLARATOR_SUFFIXES:
                declarator_end = next_index + 1
                continue
            if text == "requires":
                declarator_end = body_open if body_open is not None else end
            break

        function_declarator = self._compose(
            "function_declarator",
            name_start,
            declarator_end,
            [
                (name_start, name_end, name_element, "declarator"),
                (open_paren, close_paren + 1, parameters, "parameters"),
            ],
        )

        replacements: list[_Replacement] = [
            (name_start, declarator_end, function_declarator, "declarator")
        ]
        type_range = self._type_range(start, name_start)
        if type_range is not None:
            type_start, type_end = type_range
            type_node = self._compose("type_descriptor", type_start, type_end, [])
            replacements.append((type_start, type_end, type_node, "type"))
        replacements.extend(self._specifier_replacements(start, name_start))

        if body_open is not None:
            body_close = pairs[body_open]
            body = self._parse_compound(body_open, body_close)
            replacements.append((body_open, body_close + 1, body, "body"))
            node = self._compose("function_definition", start, body_close + 1, replacements)
            return (start, body_close + 1, node, None)

        clause = self._special_member_clause(close_paren + 1, end)
        if clause is not None:
            replacements.append(clause)
        return (start, end, self._compose("declaration", start, end, replacements), None)

    def _function_body(self, close_paren: int, end: int) -> int | None:
        """参数列表之后函数体的 {；遇到顶层的 = 或 ; 时没有函数体，返回 None。
        The { of the function body after the parameter list; None when a top-level = or ; comes
        first and there is no body.

        成员初始化列表里紧跟名字的 { 是一项初始化（: y_{2}），不是函数体。
        In a member initializer list, a { right after a name is one initializer (: y_{2}), not
        the body.
        """
        stext = self._stext
        sig = self._sig
        infos = self._infos
        initializers = False
        low, high = self._span(close_paren + 1, end)
        position = low
        while position < high:
            text = stext[position]
            if text == "{":
                index = sig[position]
                if self._pairs.get(index, end) >= end:
                    position += 1
                    continue
                if initializers and (
                    stext[position - 1] == ">" or infos[sig[position - 1]][0] == "identifier"
                ):
                    position = self._skip_group(position, high)
                    continue
                return index
            if text == "(" or text == "[":
                position = self._skip_group(position, high)
                continue
            if text == ":" and stext[position - 1] in _BEFORE_INITIALIZERS:
                initializers = True
            elif text == "=" or text == ";":
                return None
            position += 1
        return None

    def _parse_parameter_list(self, open_paren: int, close_paren: int) -> GreenNode:
        """解析函数参数列表并保留逗号与空白。
        Parse a function parameter list while preserving commas and whitespace.
        """
        replacements: list[_Replacement] = []
        # 参数类型中的模板实参含有逗号（std::pair<int, float> p），尖括号按嵌套处理。
        # Template arguments in parameter types contain commas (std::pair<int, float> p), so
        # angle brackets nest.
        for part in self._split_top_level(open_paren + 1, close_paren, ",", angle_brackets=True):
            # 参数节点不含两端的空白和注释。
            # A parameter node holds no whitespace or comments at either end.
            trimmed = self._trim(*part)
            if trimmed is None:
                continue
            parameter = self._parse_parameter(*trimmed, template=False)
            replacements.append((*trimmed, parameter, None))
        return self._compose("parameter_list", open_paren, close_paren + 1, replacements)

    def _parse_parameter(self, start: int, end: int, *, template: bool) -> GreenNode:
        """解析一个函数或模板参数，重点稳定提取 name/default/type spelling。
        Parse one function or template parameter and stably extract its name, default value, and type spelling.
        """
        low, high = self._span(start, end)
        stext = self._stext
        equal = self._find_top_level_token(start, end, "=")
        name = self._find_parameter_name(
            start, equal if equal is not None else end, template=template
        )
        first = stext[low] if low < high else ""
        replacements: list[_Replacement] = []
        if name is not None:
            text = self._texts[name]
            name_kind = "type_identifier" if template and text not in _TYPE_WORDS else "identifier"
            replacements.append((name, name + 1, _token(name_kind, text, True), "declarator"))
        if equal is not None:
            value_start = self._next_significant(equal + 1, end)
            if value_start is not None:
                field = (
                    "default_type"
                    if template and first in ("typename", "class")
                    else "default_value"
                )
                replacement = self._expression_replacement(value_start, end, field)
                if replacement is not None:
                    replacements.append(replacement)

        if template:
            optional = equal is not None
            if first in ("typename", "class"):
                kind = (
                    "optional_type_parameter_declaration"
                    if optional
                    else "type_parameter_declaration"
                )
            elif "..." in stext[low:high]:
                kind = "variadic_parameter_declaration"
            else:
                kind = "optional_parameter_declaration" if optional else "parameter_declaration"
        else:
            kind = (
                "optional_parameter_declaration" if equal is not None else "parameter_declaration"
            )
        return self._compose(kind, start, end, replacements)

    def _parse_type_declaration(
        self, start: int, end: int, content_end: int
    ) -> _Replacement | None:
        """只声明类型、没有声明子的声明，例如 enum { A = 1 };；其他情况返回 None。
        A declaration of a type alone without a declarator, such as enum { A = 1 };; None
        otherwise.
        """
        stext = self._stext
        low, high = self._span(start, content_end)
        position = low
        while position < high and stext[position] in _STORAGE:
            position += 1
        if position >= high or stext[position] not in _TYPE_KEYWORDS or stext[high - 1] != "}":
            return None
        type_start = self._sig[position]
        type_end = self._sig[high - 1] + 1
        replacements: list[_Replacement] = [
            (
                type_start,
                type_end,
                self._compose("type_descriptor", type_start, type_end, []),
                "type",
            )
        ]
        replacements.extend(self._specifier_replacements(start, type_start))
        return (start, end, self._compose("declaration", start, end, replacements), None)

    def _parse_declaration(self, start: int, end: int) -> _Replacement | None:
        """解析常见变量声明；无法稳定拆分时返回 None 让上层保留原文。
        Parse common variable declarations; return None when a stable split is not possible so the caller preserves the original source.
        """
        content_end = self._before_trailing_semicolon(start, end)
        if self._next_significant(start, end) is None:
            return None

        name = self._find_variable_name(start, content_end)
        if name is None:
            return self._parse_type_declaration(start, end, content_end)

        texts = self._texts
        type_start = self._next_significant(start, name)
        while type_start is not None and texts[type_start] in _STORAGE:
            type_start = self._next_significant(type_start + 1, name)
        if type_start is None:
            return None

        # 限定名 Foo::count_ 整个是声明子的名字。
        # A qualified name Foo::count_ as a whole is the declarator name.
        name_start = name
        separator = self._previous_significant(name - 1, type_start)
        while separator is not None and texts[separator] == "::":
            qualifier = self._previous_significant(separator - 1, type_start)
            if qualifier is None or self._infos[qualifier][0] != "identifier":
                break
            name_start = qualifier
            separator = self._previous_significant(qualifier - 1, type_start)

        # 括号声明子 (*fp)(int) 整个属于 declarator，类型到左括号为止。
        # A parenthesized declarator (*fp)(int) belongs to the declarator as a whole; the type
        # ends at its opening parenthesis.
        type_end = name_start
        opening = self._enclosing_open(name, "(", type_start)
        if opening is not None:
            type_end = opening
        before_name = self._previous_significant(type_end - 1, type_start)
        while before_name is not None and texts[before_name] in ("*", "&", "&&"):
            type_end = before_name
            before_name = self._previous_significant(before_name - 1, type_start)
        if type_end <= type_start:
            return None

        value_start: int | None = None
        equal = self._find_top_level_token(name + 1, content_end, "=")
        if equal is not None:
            value_start = self._next_significant(equal + 1, content_end)
        else:
            next_after_name = self._next_significant(name + 1, content_end)
            if (
                next_after_name is not None
                and texts[next_after_name] in ("(", "{")
                and self._pairs.get(next_after_name, content_end) < content_end
            ):
                value_start = next_after_name

        name_element: GreenElement = (
            self._plain[name].element
            if name_start == name
            else self._compose("qualified_identifier", name_start, name + 1, [])
        )
        declarator_replacements: list[_Replacement] = [
            (name_start, name + 1, name_element, "declarator")
        ]
        if value_start is not None:
            replacement = self._expression_replacement(value_start, content_end, "value")
            if replacement is not None:
                declarator_replacements.append(replacement)
        declarator = self._compose(
            "init_declarator", type_end, content_end, declarator_replacements
        )

        type_last = self._previous_significant(type_end - 1, type_start)
        if type_last is None:
            return None
        type_node = self._compose("type_descriptor", type_start, type_last + 1, [])
        replacements: list[_Replacement] = [
            (type_start, type_last + 1, type_node, "type"),
            (type_end, content_end, declarator, "declarator"),
        ]
        replacements.extend(self._specifier_replacements(start, type_start))
        return (start, end, self._compose("declaration", start, end, replacements), None)
