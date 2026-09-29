"""实现类似 Prettier 的小型布局 IR，用于新生成源码的确定性换行和缩进。
Small Prettier-style layout IR for deterministic line breaking and indentation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# 布局文档 IR
# Layout document IR
# ---------------------------------------------------------------------------


class Doc:
    """所有语言无关布局文档节点的基类。
    Base type for the language-neutral layout document IR.
    """

    pass


@dataclass(frozen=True)
class Text(Doc):
    """表示不会参与自动换行决策的字面输出文本。
    Literal output text that never participates in line breaking.
    """

    value: str


@dataclass(frozen=True)
class Line(Doc):
    """表示可平铺为空格/空串、也可在 break 模式下输出换行的布局节点。
    Potential line break. In flat mode it emits flat; in break mode it emits a newline.
    """

    flat: str = " "
    hard: bool = False


@dataclass(frozen=True)
class Concat(Doc):
    """表示多个布局文档按顺序拼接。
    Ordered concatenation of layout documents.
    """

    parts: tuple[Doc, ...]


@dataclass(frozen=True)
class Indent(Doc):
    """表示 content 内发生换行时需要增加的缩进层级。
    Increase indentation for line breaks inside content.
    """

    content: Doc
    levels: int = 1


@dataclass(frozen=True)
class Group(Doc):
    """表示优先尝试单行平铺、宽度不足时整体进入 break 模式的布局组。
    Prefer a flat rendering when the complete group fits the remaining width.
    """

    content: Doc


@dataclass(frozen=True)
class IfBreak(Doc):
    """根据外层 group 是否换行选择不同的布局内容。
    Select different layout content depending on whether the enclosing group breaks.
    """

    broken: Doc
    flat: Doc


# 渲染过程在 FLAT/BREAK 两种模式间切换。只有 Group 能决定模式；
# Line 节点只服从外层已经选定的模式。
# Rendering alternates between FLAT and BREAK modes. Only Group decides which
# mode to use; Line nodes simply obey that decision.
class _Mode(Enum):
    """表示布局渲染当前采用 FLAT 或 BREAK 两种模式之一。
    Represent one of the FLAT or BREAK layout-rendering modes.
    """

    FLAT = 1
    BREAK = 2


def text(value: str) -> Doc:
    """把字面字符串包装成 Text 布局节点。
    Wrap literal text as a layout document.
    """
    return Text(value)


softline = Line("", False)
line = Line(" ", False)
hardline = Line("", True)


def concat(*parts: Doc | str) -> Doc:
    """顺序拼接字符串和布局节点，但不立即决定换行。
    Concatenate strings/documents without deciding line breaks.
    """
    docs = tuple(Text(part) if isinstance(part, str) else part for part in parts)
    if len(docs) == 1:
        return docs[0]
    return Concat(docs)


def verbatim(value: str) -> Doc:
    """把已有多行文本转换为布局节点，同时保持原有行内容。
    Represent existing multi-line text without normalizing its contents.
    """
    lines = value.splitlines()
    if not lines:
        return Text("")
    parts: list[Doc] = []
    for index, item in enumerate(lines):
        if index:
            parts.append(hardline)
        parts.append(Text(item))
    if value.endswith(("\n", "\r")):
        parts.append(hardline)
    return Concat(tuple(parts))


def join(separator: Doc | str, docs: Iterable[Doc | str]) -> Doc:
    """用一个布局分隔符连接一组文档节点。
    Join a sequence of documents with one layout separator.
    """
    sep = Text(separator) if isinstance(separator, str) else separator
    result: list[Doc] = []
    for item in docs:
        if result:
            result.append(sep)
        result.append(Text(item) if isinstance(item, str) else item)
    return Concat(tuple(result))


# 布局计算绝不修改已解析源码的 trivia。已有源码直接走普通 render()；
# 这里的 formatter 只负责新生成源码的排版。
# Resolve layout decisions without touching parsed source trivia. Parsed source
# uses normal render(); this formatter is for newly generated source.
def render(doc: Doc, *, width: int = 88, indent: str = "  ") -> str:
    """按目标宽度和缩进单位解析 group/line 决策并输出最终文本。
    Resolve groups/line breaks into final text for the requested width and indent unit.
    """
    output: list[str] = []
    column = 0
    stack: list[tuple[int, _Mode, Doc]] = [(0, _Mode.BREAK, doc)]

    while stack:
        level, mode, current = stack.pop()
        if isinstance(current, Text):
            output.append(current.value)
            if "\n" in current.value:
                column = len(current.value.rsplit("\n", 1)[1])
            else:
                column += len(current.value)
        elif isinstance(current, Line):
            if mode is _Mode.FLAT and not current.hard:
                output.append(current.flat)
                column += len(current.flat)
            else:
                padding = indent * level
                output.extend(("\n", padding))
                column = len(padding)
        elif isinstance(current, Concat):
            for part in reversed(current.parts):
                stack.append((level, mode, part))
        elif isinstance(current, Indent):
            stack.append((level + current.levels, mode, current.content))
        elif isinstance(current, IfBreak):
            stack.append((level, mode, current.flat if mode is _Mode.FLAT else current.broken))
        elif isinstance(current, Group):
            # Group 是唯一能在平铺与换行之间做选择的节点；内部 Line 只执行
            # 已经选定的模式，避免局部节点各自做宽度决策。
            # A group is the only place that chooses between flat and broken
            # layout. Nested Line nodes merely obey the selected mode.
            trial = (level, _Mode.FLAT, current.content)
            selected = _Mode.FLAT if _fits(width - column, [trial, *stack]) else _Mode.BREAK
            stack.append((level, selected, current.content))
        else:
            raise TypeError(type(current))
    return "".join(output)


def _fits(remaining: int, stack: list[tuple[int, _Mode, Doc]]) -> bool:
    # 以 FLAT 模式试走待处理文档来估算当前行是否容得下。遇到真实换行后
    # 可以停止测量：后续文本会从新行开始，不再影响当前行宽。
    # Probe pending documents in FLAT mode to estimate whether they fit on the current
    # line. Stop at a real line break because later text starts on a new line and no
    # longer affects the current width.
    """在不真正输出文本的情况下试算待处理文档能否放入当前剩余行宽。
    Probe whether pending layout documents fit in the remaining line width without emitting text.
    """
    work = list(stack)
    while remaining >= 0 and work:
        level, mode, current = work.pop(0)
        if isinstance(current, Text):
            if "\n" in current.value:
                return True
            remaining -= len(current.value)
        elif isinstance(current, Line):
            if current.hard or mode is _Mode.BREAK:
                return True
            remaining -= len(current.flat)
        elif isinstance(current, Concat):
            work[0:0] = [(level, mode, part) for part in current.parts]
        elif isinstance(current, Indent):
            work.insert(0, (level + current.levels, mode, current.content))
        elif isinstance(current, IfBreak):
            work.insert(
                0,
                (level, mode, current.flat if mode is _Mode.FLAT else current.broken),
            )
        elif isinstance(current, Group):
            work.insert(0, (level, _Mode.FLAT, current.content))
    return remaining >= 0
