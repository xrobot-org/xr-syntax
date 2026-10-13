"""按 LibXR 的 clang-format 风格（Google、列宽 90、Allman）排版生成的 C++。
Lay out generated C++ in the clang-format style of LibXR (Google based, column limit 90, Allman).

生成器不在运行时调用 clang-format（版本不同，输出就可能不同），而是在这里按 clang-format 的规则
自己排版。引擎有两种输入形态，都产出同一份风格的结果，测试用固定版本的 clang-format 核对：

- `layout_statement()`：一条 `头部(参数, ...);` 语句，参数是不可拆分的文本或花括号列表；取断行
  代价最小的排版（CodeGenerator 的三个生成器用它排版外设对象构造语句）。
- `layout_value()` / `layout_declaration()` / `layout_call()` / `layout_macro()` /
  `sort_includes()` / `wrap_comment()`：一段 C++ 值文本、声明、调用、宏、include 块和注释；值文本
  先被解析成花括号列表、调用和指定初始化项，再按 clang-format 的填行、对齐与列对齐规则排版
  （XRobot 的 `xrobot_main.hpp` 生成用它）。

The generators do not call clang-format at run time, because another version may format differently.
They lay out their output here, by the rules of clang-format, instead. The engine takes two input
forms that both produce the same style, and the tests check the output against a pinned
clang-format:

- `layout_statement()`: one ``head(argument, ...);`` statement whose arguments are unbreakable text
  or braced lists; the cheapest set of breaks wins (the three CodeGenerator generators use it for
  the peripheral-object statements).
- `layout_value()` / `layout_declaration()` / `layout_call()` / `layout_macro()` /
  `sort_includes()` / `wrap_comment()`: a piece of C++ value text, a declaration, a call, a macro,
  an include block and a comment; the value text is first split into brace lists, calls and
  designated entries and then laid out by clang-format's fill, alignment and column rules (XRobot
  uses them for `xrobot_main.hpp`).
"""

from __future__ import annotations

import heapq
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from xr_syntax.cpp import CppLexicalToken, code_tokens, matching_delimiter, split_source_list

# LibXR 的 .clang-format：列宽 90、缩进 2、续行缩进 4。
# LibXR's .clang-format: column limit 90, indent 2, continuation indent 4.
COLUMN_LIMIT = 90
INDENT = 2
CONTINUATION_INDENT = 4
# 超出列宽的每个字符的代价；比任何断行都大，所以只有无处可断时才超出。
# The penalty of each character past the column limit; it exceeds any break, so a line goes
# past the limit only when nothing can break.
EXCESS_PENALTY = 1_000_000
# 嵌套每深一层，断行代价加 20。
# A break costs 20 more for each level of nesting.
NESTING_PENALTY = 20

# 花括号或括号前可以出现的类型写法：限定名，可带模板实参。
# What may precede a brace or a parenthesis: a qualified name with optional template arguments.
# 排版状态：括号层栈，以及各行的起始词法单元与缩进列。
# The layout state: the stack of bracket levels, and the start token and indent column of each line.
_Stack = tuple["_Scope", ...]
_Starts = tuple[tuple[int, int], ...]

_TYPE_PREFIX = re.compile(
    r"[A-Za-z_][A-Za-z_0-9]*(?:\s*::\s*[A-Za-z_][A-Za-z_0-9]*)*(?:\s*<.*>)?", re.S
)
_DESIGNATOR = re.compile(r"\.\s*([A-Za-z_][A-Za-z_0-9]*)\s*=(?!=)")


# ---------------------------------------------------------------------------
# 语句排版：结构化参数，代价最小的断行
# Statement layout: structured arguments, cheapest breaks
# ---------------------------------------------------------------------------


class Braces:
    """一个花括号列表参数，元素是文本或另一个 Braces。
    A braced list argument whose items are text or another Braces.
    """

    def __init__(self, *items: str | Braces) -> None:
        """记下列表的元素。
        Keep the items of the list.
        """
        self.items = items

    def text(self) -> str:
        """列表写在一行时的文本，例如 ``{a, b}``。
        The list written on one line, such as ``{a, b}``.
        """
        return "{" + ", ".join(_flat_item(item) for item in self.items) + "}"


def _flat_item(argument: str | Braces) -> str:
    """参数写在一行时的文本。
    An argument written on one line.
    """
    return argument if isinstance(argument, str) else argument.text()


@dataclass(frozen=True)
class _Token:
    """排版用的一个词法单元。
    One token for the layout.

    kind 为 atom、comma、open、close、assign 或 semi；depth 是它外面的括号层数；items 是
    open 所开列表的元素个数，boxed 表示这个列表有元素是花括号列表，last 表示该列表是本层的最后一项。
    kind is atom, comma, open, close, assign or semi; depth is the number of brackets around it;
    items is the number of items of the list that an open opens, boxed says that some item of that
    list is a braced list, and last that the list is the last item of its level.
    """

    text: str
    kind: str
    depth: int
    items: int = 0
    boxed: bool = False
    last: bool = False


@dataclass(frozen=True)
class _Scope:
    """一层括号的排版状态：续行缩进、本层最近一行的起始列和断行标记。
    The layout state of one bracket level: the continuation indent, the start column of its latest
    line and the break flags.

    pending 为真表示这一层之内断过行，下一个参数必须换行；boxed_mode 对有元素是花括号列表的
    列表记录各元素是否都换行：0 未决定，1 都换行，2 都不换行；commas 是这一层已有的逗号数；
    late 表示这个列表接在同一行的其他参数之后开始，clang-format 不让这样的列表跨行。
    pending means a break inside this level has happened and the next argument must start a new
    line; boxed_mode records, for a list with a braced list among its items, whether every item
    starts a line: 0 undecided, 1 all, 2 none; commas is the number of commas of this level so far;
    late means the list starts after other arguments on its line, which clang-format does not let
    span lines.
    """

    indent: int
    last_space: int
    pending: bool = False
    boxed: bool = False
    boxed_mode: int = 0
    commas: int = 0
    late: bool = False


def _tokens(head: str, args: Sequence[str | Braces]) -> list[_Token]:
    """语句 ``head(args);`` 的词法单元；head 中的 `` = `` 把它分成赋值号两侧。
    The tokens of the statement ``head(args);``; a `` = `` in head splits it around the assignment.
    """
    tokens: list[_Token] = []
    if " = " in head:
        target, callee = head.split(" = ", 1)
        tokens += [_Token(target, "atom", 0), _Token("=", "assign", 0), _Token(callee, "atom", 0)]
    else:
        tokens.append(_Token(head, "atom", 0))
    tokens.append(_Token("(", "open", 0, len(args)))

    def emit(items: Sequence[str | Braces], depth: int) -> None:
        """追加一组以逗号分隔的元素。
        Append a comma-separated group of items.
        """
        for position, item in enumerate(items):
            if position:
                tokens.append(_Token(",", "comma", depth))
            if isinstance(item, str):
                tokens.append(_Token(item, "atom", depth))
                continue
            boxed = any(isinstance(inner, Braces) for inner in item.items)
            last = position == len(items) - 1
            tokens.append(_Token("{", "open", depth, len(item.items), boxed, last))
            emit(item.items, depth + 1)
            tokens.append(_Token("}", "close", depth + 1))

    emit(args, 1)
    tokens.append(_Token(")", "close", 1))
    tokens.append(_Token(";", "semi", 0))
    return tokens


def _space_before(previous: _Token, token: _Token) -> int:
    """token 与 previous 写在同一行时它们之间的空格数。
    The number of spaces between previous and token when they share a line.
    """
    if token.kind in ("comma", "close", "semi") or token.text == "(":
        return 0
    if previous.kind in ("comma", "assign") or token.kind == "assign":
        return 1
    return 0


def _break_penalty(tokens: list[_Token], index: int) -> int:
    """在 tokens[index] 之前断行的代价：嵌套层数的代价加上断行位置的代价。
    The penalty of a break before tokens[index]: the nesting penalty plus the penalty of the place
    of the break.
    """
    token, previous = tokens[index], tokens[index - 1]
    base = NESTING_PENALTY * (token.depth + 1)
    if previous.kind == "comma":
        return base + 1
    if previous.kind == "assign":
        return base + 2
    if previous.kind == "open":
        return base + 19
    return base + 3


def _can_break(tokens: list[_Token], index: int) -> bool:
    """tokens[index] 之前是否允许断行：逗号、圆括号和赋值号之后可以，花括号之后和收尾之前不可。
    Whether a break before tokens[index] is allowed: after a comma, an opening parenthesis or an
    assignment, but not after a brace or before a closer.
    """
    token, previous = tokens[index], tokens[index - 1]
    if token.kind in ("close", "semi", "comma"):
        return False
    if previous.kind == "open":
        return previous.text == "("
    return previous.kind in ("comma", "assign")


def _place(
    tokens: list[_Token], index: int, column: int, stack: _Stack, newline: bool
) -> tuple[int, int, _Stack, int | None] | None:
    """把 tokens[index] 放在当前行或新的一行；不允许时为 None。
    Put tokens[index] on the current line or on a new one; None when that is not allowed.

    返回 (增加的代价, 新的列, 新的括号层, 本词法单元起始的列或 None)。
    Returns (added penalty, new column, new bracket levels, the start column of the token when it
    starts a line, else None).
    """
    token, previous = tokens[index], tokens[index - 1]
    top = stack[-1]
    penalty = 0
    if newline:
        if not _can_break(tokens, index) or any(scope.late for scope in stack):
            return None
        # 有元素是花括号列表的列表，只要其中断过行，各元素就都换行。
        # A list with a braced list among its items breaks at every item as soon as a line breaks
        # inside it.
        if any(scope.boxed and scope.boxed_mode == 2 for scope in stack):
            return None
        stack = tuple(
            replace(scope, boxed_mode=1) if scope.boxed and scope.boxed_mode == 0 else scope
            for scope in stack
        )
        top = stack[-1]
        start = top.indent
        penalty += _break_penalty(tokens, index)
        outer = tuple(replace(scope, pending=True) for scope in stack[:-1])
        top = replace(top, pending=False, last_space=start)
        stack = outer + (top,)
        new_column = start + len(token.text)
        line_start = start
    else:
        # 内部断过行的一层，其下一个参数必须换行；选了各元素都换行的列表，每个元素必须换行。
        # After a break inside a level, its next argument must start a new line; a list that chose
        # to break at every item must break before each item.
        if previous.kind == "comma" and (top.pending or (top.boxed and top.boxed_mode == 1)):
            return None
        if top.boxed and previous.kind == "comma":
            top = replace(top, boxed_mode=2)
        spaces = _space_before(previous, token)
        position = column + spaces
        if previous.kind == "open":
            top = replace(top, indent=position, last_space=position)
        if token.kind == "comma":
            top = replace(top, commas=top.commas + 1)
        stack = stack[:-1] + (top,)
        new_column = position + len(token.text)
        line_start = None
    if new_column > COLUMN_LIMIT:
        penalty += EXCESS_PENALTY * (new_column - COLUMN_LIMIT)
    if token.kind == "open":
        parent = stack[-1]
        # 列表接在同一行的其他参数之后时，只有它是第二个也是最后一个参数才可以跨行。
        # A list that follows other arguments on its line may span lines only as the second and last
        # argument.
        late = previous.kind == "comma" and not newline and not (parent.commas == 1 and token.last)
        scope = _Scope(
            indent=parent.last_space + CONTINUATION_INDENT,
            last_space=parent.last_space,
            boxed=token.boxed,
            late=late,
        )
        stack = stack + (scope,)
    elif token.kind == "close":
        stack = stack[:-1]
    return penalty, new_column, stack, line_start


def layout_statement(head: str, args: Sequence[str | Braces], indent: int = INDENT) -> list[str]:
    """排版语句 ``head(args);``，返回缩进 indent 列的各行。
    Lay out the statement ``head(args);`` and return its lines indented by indent columns.

    取断行代价最小的排版，能写在一行时写在一行。head 是圆括号之前的全部文本，例如
    ``static STM32UART usart1``；它含 `` = `` 时，赋值号之后也可以断行。
    The layout with the cheapest breaks wins, and a statement that fits on one line stays on one
    line. head is all the text before the parenthesis, such as ``static STM32UART usart1``; when it
    holds `` = `` the line may also break after the assignment.
    """
    one_line = " " * indent + head + "(" + ", ".join(_flat_item(arg) for arg in args) + ");"
    if len(one_line) <= COLUMN_LIMIT:
        return [one_line]
    tokens = _tokens(head, args)
    start = _Scope(indent=indent + CONTINUATION_INDENT, last_space=indent)
    initial_column = indent + len(tokens[0].text)
    counter = 0
    # 队列项：(代价, 次序, 下一个词法单元, 列, 括号层, 各行的起始位置)。次序使代价相同时先展开
    # 先加入的状态，加入时先试不断行。
    # Queue entries: (penalty, sequence, next token, column, brackets, line starts). The sequence
    # makes equal penalties expand the state added first, and a state that does not break is added
    # first.
    queue: list[tuple[int, int, int, int, _Stack, _Starts]] = [
        (0, counter, 1, initial_column, (start,), ())
    ]
    seen: set[tuple[int, int, _Stack]] = set()
    while queue:
        penalty, _, index, column, stack, starts = heapq.heappop(queue)
        if index == len(tokens):
            return _render(tokens, indent, starts)
        key = (index, column, stack)
        if key in seen:
            continue
        seen.add(key)
        for newline in (False, True):
            placed = _place(tokens, index, column, stack, newline)
            if placed is None:
                continue
            added, new_column, new_stack, line_start = placed
            counter += 1
            # 只有换行的状态才有起始列，且那时它一定不是 None。
            # Only a state that broke a line has a start column, and then it is never None.
            new_starts = (
                starts + ((index, line_start),) if newline and line_start is not None else starts
            )
            heapq.heappush(
                queue, (penalty + added, counter, index + 1, new_column, new_stack, new_starts)
            )
    raise AssertionError("no layout")


def _render(tokens: list[_Token], indent: int, starts: _Starts) -> list[str]:
    """按各行的起始词法单元和缩进列拼出文本。
    Assemble the text from the start token and the indent column of each line.
    """
    breaks = dict(starts)
    lines: list[str] = []
    current = ""
    for index, token in enumerate(tokens):
        if index in breaks:
            lines.append(current)
            current = " " * breaks[index] + token.text
        elif index == 0:
            current = " " * indent + token.text
        else:
            current += " " * _space_before(tokens[index - 1], token) + token.text
    lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# 值、声明、调用、宏、include 与注释的排版
# Layout of values, declarations, calls, macros, includes and comments
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """初始化器或实参的结构：花括号列表、调用、指定初始化项，或原样保留的文本。
    The structure of an initializer or argument: a brace list, a call, a designated entry, or text
    kept as written.
    """

    kind: str  # 'text' | 'brace' | 'call' | 'designated'
    # 文本内容；brace 和 call 的前缀；designated 的字段名。
    # The text; the prefix of a brace or a call; the field name of a designated entry.
    text: str = ""
    items: list[Node] = field(default_factory=list)


def parse_node(text: str) -> Node:
    """把一段 C++ 文本拆成 Node；只拆顶层的花括号列表、调用和指定初始化项，其余原样保留。
    Split a piece of C++ text into a Node; only top-level brace lists, calls and designated entries
    are split, everything else is kept as written.
    """
    text = text.strip()
    items = code_tokens(text)
    if not items:
        return Node("text", text)
    designator = _DESIGNATOR.match(text)
    if designator and items[0].text == ".":
        return Node("designated", designator.group(1), [parse_node(text[designator.end() :])])
    for opening, kind in (("{", "brace"), ("(", "call")):
        start = next(
            (i for i, t in enumerate(items) if t.text in ("{", "(", "[") and _top_level(items, i)),
            None,
        )
        if start is None or items[start].text != opening:
            continue
        if matching_delimiter(items, start) != len(items) - 1:
            continue
        prefix = text[: items[start].start].strip()
        if prefix and not _TYPE_PREFIX.fullmatch(prefix):
            continue
        if kind == "call" and not prefix:
            continue
        body = text[items[start].end : items[-1].start]
        parts = [p for p in split_source_list(body, template_angles=True) if p.strip()]
        return Node(kind, prefix, [parse_node(p) for p in parts])
    return Node("text", text)


def _top_level(items: Sequence[CppLexicalToken], index: int) -> bool:
    """items[index] 前面没有未配对的括号（模板尖括号不算）。
    Whether no bracket is open before items[index] (template angle brackets do not count).
    """
    depth = 0
    for token in items[:index]:
        if token.text in ("{", "(", "["):
            depth += 1
        elif token.text in ("}", ")", "]"):
            depth -= 1
    return depth == 0


def flat(node: Node) -> str:
    """node 写在一行的文本。
    The text of node on one line.
    """
    if node.kind == "text":
        return node.text
    if node.kind == "designated":
        return f".{node.text} = {flat(node.items[0])}"
    opening, closing = ("{", "}") if node.kind == "brace" else ("(", ")")
    return node.text + opening + ", ".join(flat(item) for item in node.items) + closing


def _fits(head: str, text: str, trailer: str) -> bool:
    """head、text 和 trailer 接在一起是否不超过列宽，且 text 没有换行。
    Whether head, text and trailer together stay within the column limit and text has no line break.
    """
    return "\n" not in text and len(head) + len(text) + len(trailer) <= COLUMN_LIMIT


def layout_value(head: str, text: str, trailer: str, indent: int) -> list[str]:
    """把一个值接在 head 之后排版；返回的第一行以 head 开头，最后一行以 trailer 结尾。
    Lay out a value after head; the first returned line starts with head and the last ends with
    trailer.

    Args:
        head: 值之前已在这一行上的文本（含缩进）。
            The text already on the line before the value, indentation included.
        indent: 这一行的缩进，右花括号回到这里。
            The indentation of the line; the closing brace returns to it.

    全部是指定初始化项的最外层花括号列表每项一行，放得下也一样。
    An outermost brace list of designated entries has one entry per line even when it fits.
    """
    return _layout(parse_node(text), head, trailer, indent, 0, False)


def _layout(node: Node, head: str, trailer: str, indent: int, level: int, force: bool) -> list[str]:
    """layout_value 对解析后的 Node 的递归；level 是花括号的嵌套层数，force 要求展开。
    The recursion of layout_value over a parsed Node; level is the brace nesting depth and force
    requires the node to be expanded.
    """
    text = flat(node)
    designated = (
        node.kind == "brace"
        and bool(node.items)
        and all(item.kind == "designated" for item in node.items)
    )
    if not (force or (level == 0 and designated)) and _fits(head, text, trailer):
        return [head + text + trailer]
    if node.kind == "designated":
        child = node.items[0]
        if child.kind == "brace" and child.items:
            # Allman 花括号：字段名后换行，花括号另起一行并多缩进一级，每项一行。
            # Allman braces: break after the field name, and the brace starts a line one level
            # deeper with one entry per line.
            inner = indent + CONTINUATION_INDENT
            lines = [head + f".{node.text} ="]
            return lines + _layout(child, " " * inner, trailer, inner, level + 1, True)
        return _layout(child, head + f".{node.text} = ", trailer, indent, level, False)
    if node.kind == "brace" and node.items:
        inner = indent + CONTINUATION_INDENT
        lines = [head + node.text + "{"]
        rows = _columns([flat(item) for item in node.items], inner, level, node.items)
        if rows is None:
            for item in node.items:
                lines += _layout(item, " " * inner, ",", inner, level + 1, False)
        else:
            lines += rows
        lines.append(" " * indent + "}" + trailer)
        return lines
    if node.kind == "call" and node.items:
        lead = len(head) - len(head.lstrip(" "))
        return layout_call(
            head.lstrip(" ") + node.text + "(", [flat(i) for i in node.items], ")" + trailer, lead
        )
    return [head + text + trailer]


def _columns(items: list[str], indent: int, level: int, nodes: list[Node]) -> list[str] | None:
    """花括号列表的表格排版：clang-format 对有尾随逗号的列表按列对齐，选行数最少的列数。
    The table layout of a brace list: clang-format aligns a list with a trailing comma in columns
    and picks the column count with the fewest lines.

    只有最外层列表有 5 项以上、内层列表有 19 项以上，且每项都能放在一行时才用；返回 None 时每项一行。
    It applies only to an outermost list of five items or more, or a nested list of nineteen or more,
    whose items each fit on one line; None means one item per line.
    """
    if len(items) < (5 if level == 0 else 19):
        return None
    if any(
        "\n" in text or node.kind == "designated" for text, node in zip(items, nodes, strict=True)
    ):
        return None
    # 长度含逗号。
    # The length includes the comma.
    lengths = [len(text) + 1 for text in items]
    remaining = COLUMN_LIMIT - indent
    formats = []
    for columns in range(1, COLUMN_LIMIT // 3 + 1):
        sizes = [0] * columns
        smallest = [10**9] * columns
        count = 1
        for i, length in enumerate(lengths):
            column = i % columns
            if i and column == 0:
                count += 1
            sizes[column] = max(sizes[column], length)
            smallest[column] = min(smallest[column], length)
        if columns > len(items):
            break
        width = columns - 1 + sum(sizes)
        if any(sizes[c] - smallest[c] > 10 for c in range(columns - 1)):
            continue
        if width > COLUMN_LIMIT and columns > 1:
            continue
        formats.append((columns, sizes, width, count))
    best = None
    for columns, sizes, width, count in reversed(formats):
        if width <= remaining or columns == 1:
            if best is not None and count > best[3]:
                break
            best = (columns, sizes, width, count)
    if best is None or best[0] == 1:
        return None
    columns, sizes = best[0], best[1]
    rows = []
    for start in range(0, len(items), columns):
        cells = [text + "," for text in items[start : start + columns]]
        padded = [cell.ljust(sizes[c]) for c, cell in enumerate(cells[:-1])] + cells[-1:]
        rows.append(" " * indent + " ".join(padded))
    return rows


def layout_declaration(
    declaration: str, name: str, value: str, trailer: str, indent: int
) -> list[str]:
    """一个带初始值的变量声明：第一行放不下时，在类型和变量名之间换行。
    A variable declaration with an initial value: when its first line is too long, it breaks between
    the type and the name.

    Args:
        declaration: 变量名之前的部分，如 "static const T"。
            The part before the name, such as "static const T".
    """
    prefix = " " * indent
    lines = layout_value(f"{prefix}{declaration} {name} = ", value, trailer, indent)
    if len(lines[0]) <= COLUMN_LIMIT:
        return lines
    inner = indent + CONTINUATION_INDENT
    first = f"{prefix}{declaration} {name} ="
    if len(first) <= COLUMN_LIMIT:
        # 变量名放得下：值另起一行。
        # The name fits: the value starts a line of its own.
        return [first] + layout_value(" " * inner, value, trailer, inner)
    return [prefix + declaration] + layout_value(" " * inner + f"{name} = ", value, trailer, inner)


def wrap_comment(text: str, indent: int = 0) -> list[str]:
    """一行 // 注释；超过列宽时在空格处折成多行，与 clang-format 的 ReflowComments 一致。
    A // comment line; one longer than the column limit is broken at spaces into several lines, as
    clang-format's ReflowComments does.
    """
    prefix = " " * indent + "// "
    lines, current = [], prefix.rstrip()
    for word in text.split(" "):
        if current != prefix.rstrip() and len(current) + 1 + len(word) > COLUMN_LIMIT:
            lines.append(current)
            current = prefix.rstrip()
        current += " " + word
    lines.append(current)
    return lines


def layout_call(
    head: str,
    arguments: list[str],
    tail: str,
    indent: int = 0,
    extra: int = 0,
    hang_margin: int = 1,
) -> list[str]:
    """一个调用：实参放得下就在一行，否则按 clang-format 填满每一行。
    A call: the arguments share one line when they fit, otherwise every line is filled as
    clang-format does.

    Args:
        head: 到左括号为止的文本，不含缩进；整行的缩进是 indent。
            The text up to and including the opening parenthesis, without indentation.
        arguments: 每个实参的单行文本。
            The one-line text of each argument.
        tail: 最后一个实参之后的文本，如 ")" 或 ");"。
            The text after the last argument, such as ")" or ");".
        extra: 每行末尾之后要占用的宽度（宏的续行符）。
            Width reserved after every line (the line continuation of a macro).
        hang_margin: 左括号后换行比对齐少几行时才换行；函数声明比调用更不愿意换行。
            How many lines breaking after the parenthesis must save before it is chosen; a function
            declaration is more reluctant than a call.
    """
    prefix = " " * indent
    one_line = prefix + head + ", ".join(arguments) + tail
    if len(one_line) <= COLUMN_LIMIT and "\n" not in one_line:
        return [one_line]
    aligned = _pack(prefix + head, arguments, tail, len(prefix + head), extra)
    hanging = [prefix + head] + _pack(
        " " * (indent + CONTINUATION_INDENT),
        arguments,
        tail,
        indent + CONTINUATION_INDENT,
        extra,
        True,
    )
    limit = COLUMN_LIMIT - extra
    if any(len(line) > limit for line in aligned) or len(aligned) - len(hanging) >= hang_margin:
        return hanging
    return aligned


def _pack(
    first: str, arguments: list[str], tail: str, column: int, extra: int, fresh: bool = False
) -> list[str]:
    """把实参填进行：first 是第一行已有的文本，续行缩进 column 格。
    Fill lines with the arguments: first is the text already on the first line, and continuation
    lines are indented by column.

    fresh 为真时 first 只是缩进，第一个实参不加空格。
    With fresh, first is only indentation and the first argument gets no space before it.
    """
    limit = COLUMN_LIMIT - extra
    lines, current = [], first
    start = first
    for i, argument in enumerate(arguments):
        piece = argument + (tail if i + 1 == len(arguments) else ",")
        if current == start:
            current += piece
        elif len(current) + 1 + len(piece) <= limit:
            current += " " + piece
        else:
            lines.append(current)
            start = " " * column
            current = start + piece
    lines.append(current)
    return lines


def layout_macro(name: str, call: str, arguments: list[str]) -> list[str]:
    """#define name() call(arguments...)；放不下时调用另起一行并用续行符对齐。
    #define name() call(arguments...); when it does not fit the call starts on its own line and the
    line continuations are aligned.
    """
    one_line = f"#define {name}() {call}({', '.join(arguments)})"
    if len(one_line) <= COLUMN_LIMIT:
        return [one_line]
    body = layout_call(call + "(", arguments, ")", INDENT, extra=2)
    lines = [f"#define {name}()"] + body
    width = max(len(line) for line in lines[:-1]) + 1
    return [line.ljust(width) + "\\" for line in lines[:-1]] + [lines[-1]]


def sort_includes(names: list[str]) -> list[str]:
    """按 clang-format 的 Regroup 排好的 #include 行。
    The #include lines grouped as clang-format's Regroup does.

    顺序是 <*.h>、其他 <...>、"..."；组之间空一行，组内按名字的字节序排序并去重。
    The order is <*.h>, other <...>, then "..."; a blank line goes between groups, and each group is
    sorted bytewise by name without repeats.

    Args:
        names: 每个 include 的写法，如 "libxr.hpp"（带引号）或 <memory>。
            Each include as written, such as "libxr.hpp" with its quotes or <memory>.
    """
    groups: dict[int, list[str]] = {1: [], 2: [], 3: []}
    for name in sorted(set(names), key=lambda n: n.strip('"<>')):
        if re.match(r"<ext/.*\.h>", name):
            groups[2].append(name)
        elif re.match(r"<.*\.h>", name):
            groups[1].append(name)
        elif name.startswith("<"):
            groups[2].append(name)
        else:
            groups[3].append(name)
    lines: list[str] = []
    for group in groups.values():
        if group:
            if lines:
                lines.append("")
            lines += [f"#include {name}" for name in group]
    return lines
