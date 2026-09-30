"""C++ parser 内部的函数、参数与变量声明解析。
Internal C++ parser implementation for functions, parameters, and variable declarations.
"""

from __future__ import annotations

from xr_syntax.core import GreenNode, GreenToken

from ._ranges import _Replacement
from ._support import _ParserSupport
from .lexer import _CONTROL, _STORAGE, _TYPE_WORDS


class _DeclarationMixin(_ParserSupport):
    """解析一个 source unit 中的函数声明/定义、参数与变量声明。
    Parse function declarations/definitions, parameters, and variable declarations within one source unit.
    """

    def _parse_unit(self, start: int, end: int, *, context: str) -> _Replacement | None:
        """把一个完整声明/语句区间分类成具体结构节点。
        Classify one complete declaration/statement range into a concrete structural node.
        """
        significant = self._significant(start, end)
        if not significant:
            return None
        first = self.lexemes[significant[0]].text

        if first == "return":
            return self._parse_return(start, end)
        if first in _CONTROL:
            return self._parse_control(start, end, first)
        if first == "do":
            return self._parse_do(start, end)
        if first in {"break", "continue"}:
            node = self._compose(first + "_statement", start, end, [])
            return _Replacement(start, end, node)
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

        if context in {"top", "class", "block"} and self._looks_like_declaration(
            start, end, context=context
        ):
            declaration = self._parse_declaration(start, end)
            if declaration is not None:
                if context == "block":
                    wrapper = self._compose(
                        "declaration_statement",
                        start,
                        end,
                        [_Replacement(start, end, declaration.element)],
                    )
                    return _Replacement(start, end, wrapper)
                return declaration

        expression_end = self._before_trailing_semicolon(start, end)
        replacement = self._expression_replacement(start, expression_end)
        node = self._compose(
            "expression_statement",
            start,
            end,
            [] if replacement is None else [replacement],
        )
        return _Replacement(start, end, node)

    def _parse_function(self, start: int, end: int, *, context: str) -> _Replacement | None:
        """识别函数定义/声明，并构造 function_declarator 与参数结构。
        Recognize a function declaration/definition and build its function_declarator and parameter structure.
        """
        significant = self._significant(start, end)
        if not significant:
            return None

        candidate = self._find_function_parameter_list(start, end)
        if candidate is None:
            return None
        open_paren, close_paren, name_start, name_end = candidate
        body_open = next(
            (
                index
                for index in significant
                if index > close_paren
                and self.lexemes[index].text == "{"
                and index in self._pairs
                and self._pairs[index] < end
            ),
            None,
        )

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
            text = self.lexemes[next_index].text
            if text in {"const", "volatile", "noexcept", "override", "final", "&", "&&"}:
                declarator_end = next_index + 1
                continue
            if text == "requires":
                declarator_end = body_open if body_open is not None else end
                break
            break

        function_declarator = self._compose(
            "function_declarator",
            name_start,
            declarator_end,
            [
                _Replacement(name_start, name_end, name_element, "declarator"),
                _Replacement(open_paren, close_paren + 1, parameters, "parameters"),
            ],
        )

        replacements: list[_Replacement] = [
            _Replacement(name_start, declarator_end, function_declarator, "declarator")
        ]
        type_range = self._type_range(start, name_start)
        if type_range is not None:
            type_start, type_end = type_range
            type_node = self._compose("type_descriptor", type_start, type_end, [])
            replacements.append(_Replacement(type_start, type_end, type_node, "type"))
        replacements.extend(self._specifier_replacements(start, name_start))

        if body_open is not None:
            body_close = self._pairs[body_open]
            body = self._parse_compound(body_open, body_close)
            replacements.append(_Replacement(body_open, body_close + 1, body, "body"))
            node = self._compose("function_definition", start, body_close + 1, replacements)
            return _Replacement(start, body_close + 1, node)

        clause = self._special_member_clause(close_paren + 1, end)
        if clause is not None:
            replacements.append(clause)
        node = self._compose("declaration", start, end, replacements)
        return _Replacement(start, end, node)

    def _parse_parameter_list(self, open_paren: int, close_paren: int) -> GreenNode:
        """解析函数参数列表并保留逗号与空白。
        Parse a function parameter list while preserving commas and whitespace.
        """
        replacements: list[_Replacement] = []
        # 参数类型中的模板实参含有逗号（std::pair<int, float> p），尖括号按嵌套处理。
        # Template arguments in parameter types contain commas (std::pair<int, float> p), so
        # angle brackets nest.
        for part_start, part_end in self._split_top_level(
            open_paren + 1, close_paren, ",", angle_brackets=True
        ):
            if self._next_significant(part_start, part_end) is None:
                continue
            parameter = self._parse_parameter(part_start, part_end, template=False)
            replacements.append(_Replacement(part_start, part_end, parameter))
        return self._compose("parameter_list", open_paren, close_paren + 1, replacements)

    def _parse_parameter(self, start: int, end: int, *, template: bool) -> GreenNode:
        """解析一个函数或模板参数，重点稳定提取 name/default/type spelling。
        Parse one function or template parameter and stably extract its name, default value, and type spelling.
        """
        significant = self._significant(start, end)
        equal = self._find_top_level_token(start, end, "=")
        declarator_end = equal if equal is not None else end
        name = self._find_parameter_name(start, declarator_end)
        replacements: list[_Replacement] = []
        if name is not None:
            name_kind = (
                "type_identifier"
                if template and self.lexemes[name].text not in _TYPE_WORDS
                else "identifier"
            )
            replacements.append(
                _Replacement(
                    name,
                    name + 1,
                    GreenToken(name_kind, self.lexemes[name].text, named=True),
                    "declarator",
                )
            )
        if equal is not None:
            value_start = self._next_significant(equal + 1, end)
            if value_start is not None:
                field = (
                    "default_type"
                    if template
                    and significant
                    and self.lexemes[significant[0]].text in {"typename", "class"}
                    else "default_value"
                )
                replacement = self._expression_replacement(value_start, end, field)
                if replacement is not None:
                    replacements.append(replacement)

        first = self.lexemes[significant[0]].text if significant else ""
        if template:
            optional = equal is not None
            if first in {"typename", "class"}:
                kind = (
                    "optional_type_parameter_declaration"
                    if optional
                    else "type_parameter_declaration"
                )
            elif "..." in (self.lexemes[index].text for index in significant):
                kind = "variadic_parameter_declaration"
            else:
                kind = "optional_parameter_declaration" if optional else "parameter_declaration"
        else:
            kind = (
                "optional_parameter_declaration" if equal is not None else "parameter_declaration"
            )
        return self._compose(kind, start, end, replacements)

    def _parse_declaration(self, start: int, end: int) -> _Replacement | None:
        """解析常见变量声明；无法稳定拆分时返回 None 让上层保留原文。
        Parse common variable declarations; return None when a stable split is not possible so the caller preserves the original source.
        """
        significant = self._significant(start, end)
        if not significant:
            return None
        terminator = significant[-1]
        content_end = terminator if self.lexemes[terminator].text == ";" else end

        name = self._find_variable_name(start, content_end)
        if name is None:
            return None

        type_start = self._next_significant(start, name)
        while type_start is not None and self.lexemes[type_start].text in _STORAGE:
            type_start = self._next_significant(type_start + 1, name)
        if type_start is None:
            return None

        type_end = name
        before_name = self._previous_significant(name - 1, type_start)
        while before_name is not None and self.lexemes[before_name].text in {"*", "&", "&&"}:
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
                and self.lexemes[next_after_name].text in {"(", "{"}
                and next_after_name in self._pairs
            ):
                close = self._pairs[next_after_name]
                if close < content_end:
                    value_start = next_after_name

        declarator_start = type_end
        declarator_end = content_end
        declarator_replacements: list[_Replacement] = [
            _Replacement(name, name + 1, self.lexemes[name].green(), "declarator")
        ]
        if value_start is not None:
            replacement = self._expression_replacement(
                value_start,
                content_end,
                "value",
            )
            if replacement is not None:
                declarator_replacements.append(replacement)
        declarator = self._compose(
            "init_declarator",
            declarator_start,
            declarator_end,
            declarator_replacements,
        )

        type_last = self._previous_significant(type_end - 1, type_start)
        if type_last is None:
            return None
        type_node_end = type_last + 1
        type_node = self._compose("type_descriptor", type_start, type_node_end, [])
        replacements: list[_Replacement] = [
            _Replacement(type_start, type_node_end, type_node, "type"),
            _Replacement(declarator_start, declarator_end, declarator, "declarator"),
        ]
        replacements.extend(self._specifier_replacements(start, type_start))
        node = self._compose("declaration", start, end, replacements)
        return _Replacement(start, end, node)
