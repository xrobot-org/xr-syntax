"""Native C++ parser 各结构阶段共享的严格类型合同。
Strict internal typing contract shared by the native C++ parser mixins.
"""

from __future__ import annotations

from xr_syntax.core import Diagnostic, GreenChild, GreenElement, GreenNode

# ---------------------------------------------------------------------------
# 模块实现：Native C++ parser 各结构阶段共享的严格类型合同。
# ---------------------------------------------------------------------------

# (start, end, element, field)：用 element 替换 lexeme 区间 [start, end)，边上带 field。
# (start, end, element, field): element replaces the lexeme range [start, end), with field on the
# edge.
_Replacement = tuple[int, int, GreenElement, "str | None"]


class _ParserSupport:
    """描述 native parser mixin 之间互相依赖的内部状态和接口。
    Describe the internal state and interface shared by native parser mixins.

    Attributes:
        _texts: 每个 lexeme 的文本。
            The text of each lexeme.
        _infos: 每个 lexeme 的 (kind, named, trivia)。
            The (kind, named, trivia) of each lexeme.
        _offsets: 每个 lexeme 起点的字节位置，最后一项是源码总字节数。
            The byte position where each lexeme starts; the last item is the source size.
        _count: lexeme 个数。
            The number of lexemes.
        _sig: 有效 lexeme（非空白、非注释）的下标，按顺序排列。
            The indices of the significant lexemes (not whitespace, not comments), in order.
        _stext: 有效 lexeme 的文本，与 _sig 一一对应。
            The texts of the significant lexemes, parallel to _sig.
        _rank: _rank[i] 是下标 i 之前的有效 lexeme 个数（长度为 lexeme 个数加一）。
            _rank[i] is the number of significant lexemes before index i (one longer than the
            lexemes).
        _plain: 每个 lexeme 的 green 叶子边。
            The green leaf edge of each lexeme.
        _pairs: 已配对的开括号下标到闭括号下标。
            Paired opening delimiter index to closing delimiter index.
        _reverse_pairs: 闭括号下标到开括号下标。
            Closing delimiter index to opening delimiter index.
        _dirty: 组内含有多余闭括号的开括号下标。
            Opening delimiters whose group contains a stray closing delimiter.
        diagnostics: 词法和结构诊断。
            Lexer and structural diagnostics.
    """

    _texts: list[str]
    _infos: list[tuple[str, bool, bool]]
    _offsets: list[int]
    _count: int
    _sig: list[int]
    _stext: list[str]
    _rank: list[int]
    _plain: list[GreenChild]
    _pairs: dict[int, int]
    _reverse_pairs: dict[int, int]
    _dirty: set[int]
    _depth: int
    diagnostics: list[Diagnostic]

    def _span(self, start: int, end: int) -> tuple[int, int]:
        """lexeme 区间内有效 lexeme 的位置范围。
        The position range of the significant lexemes in a lexeme range.
        """
        raise NotImplementedError

    def _significant(self, start: int, end: int) -> list[int]:
        """返回区间内非 trivia/comment 的 lexeme 索引。
        Return lexeme indices after excluding trivia and comments.
        """
        raise NotImplementedError

    def _next_significant(self, start: int, end: int) -> int | None:
        """向右寻找下一个有效 lexeme。
        Find the next non-trivia, non-comment lexeme to the right.
        """
        raise NotImplementedError

    def _previous_significant(self, start: int, lower_bound: int) -> int | None:
        """向左寻找上一个有效 lexeme。
        Find the previous non-trivia, non-comment lexeme to the left.
        """
        raise NotImplementedError

    def _skip_group(self, position: int, high: int) -> int:
        """跳过从 position 开始的配对括号组。
        Skip the paired delimiter group that starts at position.
        """
        raise NotImplementedError

    def _split_top_level(
        self,
        start: int,
        end: int,
        separator: str,
        *,
        angle_brackets: bool = False,
    ) -> list[tuple[int, int]]:
        """按不位于嵌套分隔符内的 separator 拆分区间；angle_brackets 时模板尖括号也算嵌套。
        Split a source range on separators that are not nested inside (), [] or {}, and with
        angle_brackets also not inside template angle brackets.
        """
        raise NotImplementedError

    def _find_top_level_token(
        self,
        start: int,
        end: int,
        token: str,
    ) -> int | None:
        """查找当前层级的指定 token。
        Find the requested token at the current nesting level.
        """
        raise NotImplementedError

    def _enclosing_open(
        self,
        index: int,
        token: str,
        lower_bound: int,
    ) -> int | None:
        """查找包围当前位置的指定开分隔符。
        Find the matching enclosing opening delimiter to the left of a token.
        """
        raise NotImplementedError

    def _before_trailing_semicolon(self, start: int, end: int) -> int:
        """返回排除尾部分号后的区间末端。
        Return the lexeme position immediately before a trailing semicolon.
        """
        raise NotImplementedError

    def _trim(self, start: int, end: int) -> tuple[int, int] | None:
        """去除区间两端 trivia/comment。
        Trim trivia/comments from both ends of a range without modifying its interior source.
        """
        raise NotImplementedError

    def _text(self, start: int, end: int) -> str:
        """还原 lexeme 区间源码文本。
        Return the original source text for a lexeme range.
        """
        raise NotImplementedError

    def _compose(
        self,
        kind: str,
        start: int,
        end: int,
        replacements: list[_Replacement],
    ) -> GreenNode:
        """把不重叠 replacement 组合成 green node。
        Compose non-overlapping structured replacements into a GreenNode while preserving untouched source.
        """
        raise NotImplementedError

    def _diagnostic(self, message: str, start: int, end: int) -> None:
        """记录结构诊断。
        Record a structural diagnostic.
        """
        raise NotImplementedError

    def _enter(self, start: int, end: int) -> bool:
        """进入一层嵌套；超过嵌套上限时返回 False。
        Enter one nesting level; False when the nesting limit is exceeded.
        """
        raise NotImplementedError

    def _find_unit_end(self, start: int, end: int, *, context: str) -> int:
        """寻找当前声明/语句单元的结束位置。
        Find where the current declaration/statement unit ends.
        """
        raise NotImplementedError

    def _find_call_suffix(self, start: int, end: int) -> tuple[int, int] | None:
        """识别覆盖整个表达式的调用实参括号。
        Return the argument-parenthesis pair when the entire expression ends in one function call.
        """
        raise NotImplementedError

    def _parse_scope(
        self,
        start: int,
        end: int,
        *,
        context: str,
    ) -> list[_Replacement]:
        """解析连续源码作用域。
        Parse one continuous scope using top-level statement/declaration boundaries.
        """
        raise NotImplementedError

    def _parse_expression(
        self, start: int, end: int, operators: list[tuple[int, int]] | None = None
    ) -> GreenElement:
        """解析表达式结构。
        Parse common expression forms, falling back to source_expression when finer classification is unsafe.
        """
        raise NotImplementedError

    def _expression_replacement(
        self,
        start: int,
        end: int,
        field: str | None = None,
    ) -> _Replacement | None:
        """构造不吞掉 expression 两端 trivia 的 replacement。
        Create an expression replacement whose span exactly matches the trivia-trimmed expression node.
        """
        raise NotImplementedError

    def _parse_compound(self, open_brace: int, close_brace: int) -> GreenNode:
        """解析复合语句。
        Parse a function/control-flow compound statement and recursively structure declarations and calls inside it.
        """
        raise NotImplementedError

    def _parse_return(self, start: int, end: int) -> _Replacement:
        """解析 return 语句。
        Parse a return statement together with its returned expression.
        """
        raise NotImplementedError

    def _parse_control(
        self,
        start: int,
        end: int,
        keyword: str,
    ) -> _Replacement:
        """解析控制流语句。
        Parse the condition and compound body of if/for/while/switch/catch constructs.
        """
        raise NotImplementedError

    def _parse_do(self, start: int, end: int) -> _Replacement:
        """解析 do/while 语句。
        Parse a do/while construct while recursively structuring its body.
        """
        raise NotImplementedError

    def _parse_concept(self, start: int, end: int) -> _Replacement:
        """解析 concept 定义。
        Parse a concept definition and continue parsing the expression after =.
        """
        raise NotImplementedError

    def _parse_parameter(self, start: int, end: int, *, template: bool) -> GreenNode:
        """解析一个函数或模板参数。
        Parse one function or template parameter.
        """
        raise NotImplementedError

    def _find_function_parameter_list(
        self,
        start: int,
        end: int,
    ) -> tuple[int, int, int, int] | None:
        """定位函数主参数列表与函数名范围。
        Locate the primary function parameter list and the source range of the function name.
        """
        raise NotImplementedError

    def _prototype_is_function(
        self,
        start: int,
        end: int,
        open_paren: int,
        close_paren: int,
        name_start: int,
        context: str,
    ) -> bool:
        """区分函数声明与直接初始化。
        Distinguish a function declaration from direct object initialization.
        """
        raise NotImplementedError

    def _name_element(self, start: int, end: int) -> GreenElement:
        """构造函数名/析构名/operator 名称元素。
        Choose the syntax element kind for a function, destructor, or operator name.
        """
        raise NotImplementedError

    def _find_parameter_name(self, start: int, end: int) -> int | None:
        """定位参数 declarator 名称。
        Locate a parameter declarator name without mistaking function-pointer parameter types for the name.
        """
        raise NotImplementedError

    def _find_variable_name(self, start: int, end: int) -> int | None:
        """定位变量 declarator 名称。
        Recognize a common variable declarator name while ignoring identifiers inside its initializer.
        """
        raise NotImplementedError

    def _looks_like_declaration(
        self,
        start: int,
        end: int,
        *,
        context: str,
    ) -> bool:
        """保守判断源码单元是否属于声明。
        Conservatively decide whether a semicolon-terminated source unit should be treated as a declaration without name lookup.
        """
        raise NotImplementedError

    def _specifier_replacements(
        self,
        start: int,
        end: int,
    ) -> list[_Replacement]:
        """返回 storage/type qualifier 的结构化 replacement。
        Build structured replacements for storage-class and type qualifiers.
        """
        raise NotImplementedError

    def _type_range(
        self,
        start: int,
        name_start: int,
    ) -> tuple[int, int] | None:
        """提取函数返回类型源码区间。
        Extract the source range spelling the function return type.
        """
        raise NotImplementedError

    def _special_member_clause(
        self,
        start: int,
        end: int,
    ) -> _Replacement | None:
        """识别 = delete/default 子句。
        Recognize an = delete or = default special-member clause.
        """
        raise NotImplementedError
