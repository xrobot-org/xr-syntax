"""提供面向 CMake 的高层文档查询、区域与语句编辑，底层仍使用语言无关的不可变语法模型。
High-level CMake document queries plus region and statement editing over the same
language-neutral immutable syntax model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from xr_syntax.cmake.parser import CMakeParser
from xr_syntax.cmake.view import CMakeArgumentView, CMakeCommandView
from xr_syntax.core import (
    GreenToken,
    SourceRegion,
    SourceSpan,
    SyntaxDocument,
    SyntaxElement,
    SyntaxFragment,
    SyntaxNode,
    SyntaxTree,
)

# CMake 的 User Code 标记：与 C++ 侧的 User Code 完全一致地区分大小写，只是注释语法换成 #。
# The CMake User Code markers: case-sensitive exactly like the C++ User Code markers, with # as the
# comment syntax.
_USER_BEGIN = re.compile(r"#\s*User Code Begin(?:\s+(.+?))?\s*")
_USER_END = re.compile(r"#\s*User Code End(?:\s+(.+?))?\s*")

# bracket comment 的开头（`#[[` 或 `#[=[` 等）；找行末换行时要整段跳过。
# The start of a bracket comment (`#[[`, `#[=[` and so on); a whole one is skipped when the line
# ending is looked for.
_BRACKET_OPEN = re.compile(rb"#\[(=*)\[")

# 解析器组合出的块节点 kind；顶层语句可以是普通命令或这些块。
# The block node kinds the parser groups; a top-level statement is a normal command or one of these
# blocks.
_BLOCK_KINDS = frozenset(
    {"block", "foreach_loop", "function_def", "if_condition", "macro_def", "while_loop"}
)


@dataclass(frozen=True)
class CMakeStatementView:
    """一条顶层语句：一个命令，或 if/foreach/while/function/macro/block 到其结束命令的整块。
    One top-level statement: a command, or a whole block from
    if/foreach/while/function/macro/block to its end command.

    name 是开启该语句的命令名（保持源码大小写），arguments 是它的参数视图；span 是语句本体的字节
    范围（不含行末换行），leading_span 是紧上方连续注释行的起点，没有这样的注释时等于语句所在行的
    行首。
    name is the command that opens the statement, as written; arguments are its argument views; span
    is the byte range of the statement itself without the newline at its end, and leading_span is the
    start of the comment lines directly above it, or the start of its own line without any.
    """

    node: SyntaxNode
    name: str
    arguments: tuple[CMakeArgumentView, ...]
    span: SourceSpan
    leading_span: SourceSpan


def _end_of_line(source: bytes, start: int) -> tuple[int, bool]:
    """source 中 start 所在那一行的行末换行偏移（没有时为 -1），以及 start 之后这一行是否只有空白与注释。
    The offset of the newline that ends the line holding start in source, -1 without one, and
    whether the rest of that line after start holds only blanks and comments.

    bracket comment 可以跨行，跳过它之后找到的换行才是这一行的换行。
    A bracket comment may span lines, so the newline found after it is the one that ends this line.
    """
    cursor = start
    while cursor < len(source):
        char = source[cursor : cursor + 1]
        if char == b"\n":
            return cursor, True
        if char in (b" ", b"\t", b"\r"):
            cursor += 1
            continue
        if char != b"#":
            # 同一行上还有别的语句。
            # Another statement is on the same line.
            return source.find(b"\n", cursor), False
        bracket = _BRACKET_OPEN.match(source, cursor)
        if bracket is None:
            # 行注释到这一行的换行为止。
            # A line comment runs to the newline of this line.
            return source.find(b"\n", cursor), True
        closing = b"]" + bracket.group(1) + b"]"
        end = source.find(closing, bracket.end())
        if end < 0:
            return -1, True
        cursor = end + len(closing)
    return -1, True


def _line_start(source: bytes, offset: int) -> int:
    """source 中 offset 所在行的行首字节偏移。
    The byte offset of the start of the line holding offset in source.
    """
    return source.rfind(b"\n", 0, offset) + 1


def _leading_offset(source: bytes, start: int) -> int:
    """start 所在行紧上方连续注释行的起点；上方不是注释行时为 start。
    The start of the comment lines directly above the line of start; start itself when the line above
    is not a comment.
    """
    line_start = _line_start(source, start)
    leading = line_start
    while leading > 0:
        previous = _line_start(source, leading - 1)
        if not source[previous : leading - 1].lstrip().startswith(b"#"):
            break
        leading = previous
    return leading if source[line_start:start].strip() == b"" else start


class CMakeDocument(SyntaxDocument):
    """在通用不可变语法树之上提供 CMake 专用查询和编辑接口。
    CMake-specific query and edit facade over the same immutable syntax core used by C++.
    """

    __slots__ = ()

    language = "cmake"

    @classmethod
    def parse(
        cls,
        source: str | bytes,
        *,
        source_name: str | None = None,
        parser: CMakeParser | None = None,
    ) -> CMakeDocument:
        """解析文本或字节并创建文档快照。
        Parse text or bytes and create a document snapshot.

        parser 给出复用的解析器实例；省略时新建。
        parser reuses one parser instance; without it a new parser is created.
        """
        selected = parser or CMakeParser()
        return cls(selected.parse(source, source_name=source_name), selected)

    def comments(self) -> tuple[SyntaxElement, ...]:
        """按源码顺序返回全部 CMake 注释。
        Return CMake comments in source order.
        """
        return self.elements("comment")

    def command_views(self, name: str | None = None) -> tuple[CMakeCommandView, ...]:
        """返回类型化命令视图，并可按命令名过滤。
        Return typed command views, optionally filtered by command name.
        """
        normalized = name.casefold() if name is not None else None
        return tuple(
            CMakeCommandView(node)
            for node in self.root.descendants(include_self=True)
            if isinstance(node, SyntaxNode)
            and node.kind == "normal_command"
            and (normalized is None or CMakeCommandView(node).name.casefold() == normalized)
        )

    def top_level_statements(self) -> tuple[CMakeStatementView, ...]:
        """按源码顺序返回顶层语句：命令，以及各块命令到其结束命令的整块。
        The top-level statements in source order: commands, and whole blocks from a block command to
        its end command.

        块中的命令不单独列出。leading_span 记下语句紧上方没有空行隔开的注释行，迁移时随语句一起保留。
        Commands inside a block are not listed on their own. leading_span records the comment lines
        directly above a statement with no blank line between, which move along with the statement
        when it is kept.
        """
        source = self.render_bytes()
        views = []
        for child in self.root.syntax_children:
            if not isinstance(child, SyntaxNode):
                continue
            if child.kind != "normal_command" and child.kind not in _BLOCK_KINDS:
                continue
            start = child.span.start
            views.append(
                CMakeStatementView(
                    child,
                    CMakeCommandView(child).name,
                    CMakeCommandView(child).arguments,
                    child.span,
                    SourceSpan(_leading_offset(source, start), start),
                )
            )
        return tuple(views)

    def user_regions(self) -> tuple[SourceRegion, ...]:
        """识别并返回成对的 User Code Begin/End 区域，按源码顺序排列。
        Find paired User Code Begin/End comment regions, in source order.

        标记是 `# User Code Begin <name>` 与 `# User Code End <name>`，区分大小写；配对与校验语义
        与 C++ 侧完全相同（见 core.document.SyntaxDocument.paired_comment_regions）。
        The markers are `# User Code Begin <name>` and `# User Code End <name>`, case-sensitive; the
        pairing and validation semantics are exactly those of the C++ side (see
        core.document.SyntaxDocument.paired_comment_regions).
        """
        return self.paired_comment_regions(kind="user", begin=_USER_BEGIN, end=_USER_END)

    # -----------------------------------------------------------------------
    # 语句与参数的编辑。替换参数和语句用底层结构编辑，编辑后快照的诊断未经验证；按行插入和删除直接
    # 改源码再重新解析，诊断可信。
    # Statement and argument edits. Replacing an argument or a statement uses the low-level
    # structural edit, so the resulting snapshot's diagnostics are unverified; inserting and removing
    # lines edit the source and parse it again, so their diagnostics can be trusted.
    # -----------------------------------------------------------------------
    def replace_argument(self, argument: CMakeArgumentView, text: str) -> CMakeDocument:
        """把一条命令的一个参数换成 text，命令名、括号和其余空白原样保留。
        Replace one argument of a command with text, keeping the command name, the parentheses and
        every other byte as written.

        text 由解析器重新解析，因此引号与 bracket 写法都按 CMake 的规则处理。
        text is parsed again, so quoting and bracket spellings follow CMake's own rules.
        """
        fragment = self._argument_fragment(text)
        return self._with_tree(self.tree.replace(argument.node, fragment))

    def replace_statement(self, statement: CMakeStatementView, source: str) -> CMakeDocument:
        """把一条顶层语句换成 source（一条完整的 CMake 语句）。
        Replace one top-level statement with source, one complete CMake statement.

        语句前的注释行不属于语句本身，因此不在替换范围内。
        The comment lines above a statement are not part of it and stay where they are.

        Raises:
            ValueError: source 里没有顶层语句，或不止一条。
                source holds no top-level statement, or more than one.
        """
        parsed = CMakeDocument.parse(source, parser=self._parser_of())
        statements = parsed.top_level_statements()
        if len(statements) != 1:
            raise ValueError("replace_statement expects exactly one top-level CMake statement")
        return self._with_tree(
            self.tree.replace(
                statement.node,
                SyntaxFragment(
                    self.language, GreenToken("raw", statements[0].node.text, named=True)
                ),
            )
        )

    def insert_after(self, statement: CMakeStatementView, source: str) -> CMakeDocument:
        """在一条顶层语句所在的整行之后另起一行插入 source，一条完整的 CMake 语句，可带注释行。
        Insert source, one complete CMake statement together with the comment lines directly above
        it, on a line of its own after the whole line that holds a top-level statement.

        行尾注释属于原来那一行，因此留在原处，不跟着新语句走。
        A comment at the end of the line belongs to that line, so it stays there instead of moving
        with the new statement.

        插入的文本先被解析一次以确认它是且只是一条顶层语句，然后原样插入，因此注释与写法都不变。
        The text is parsed once to confirm it is exactly one top-level statement and is then inserted
        as written, so its comments and spelling stay.

        Raises:
            ValueError: source 里没有顶层语句，或不止一条。
                source holds no top-level statement, or more than one.
        """
        parsed = CMakeDocument.parse(source, parser=self._parser_of())
        statements = parsed.top_level_statements()
        if len(statements) != 1:
            raise ValueError("insert_after expects exactly one top-level CMake statement")
        kept = parsed.render_bytes()[statements[0].leading_span.start : statements[0].span.end]
        current = self.render_bytes()
        ending = self._line_ending().encode()
        newline, _ = _end_of_line(current, statement.node.span.end)
        if newline < 0:
            # 语句所在行没有行末换行（设置块由 split_blocks 去掉末尾换行得到）：先补一个换行。
            # The line of the statement has no line ending (split_blocks strips the trailing newline
            # of the settings block), so one is added first.
            return self._reparsed(current + ending + kept)
        # 插入点在这一行的换行之后：后面有几个空行、有没有行尾注释或行尾空格、是 LF 还是 CRLF 都一样。
        # The insertion point is right after the line ending: blank lines after it, a comment or
        # spaces at the end of the line, and LF or CRLF make no difference.
        boundary = newline + 1
        return self._reparsed(current[:boundary] + kept + ending + current[boundary:])

    def remove_command(self, view: CMakeCommandView) -> CMakeDocument:
        """删除一条命令，连同它所在的整行：行首缩进、行尾注释和行末换行。
        Remove one command together with the whole line it is on: the indentation, a comment at the
        end of the line and the line ending.

        命令后面跟着跨行的 bracket 注释时，注释属于这一行，一起删掉。
        A bracket comment that follows the command and spans lines belongs to that line and goes too.

        Raises:
            ValueError: 同一行上还有其他语句。CMake 不允许这样写，解析时已报诊断。
                Another statement shares the line; CMake does not allow that and parsing already
                reported it.
        """
        source = self.render_bytes()
        node = view.node
        line_start = source.rfind(b"\n", 0, node.span.start) + 1
        newline, only_comments = _end_of_line(source, node.span.end)
        line_end = len(source) if newline < 0 else newline + 1
        if source[line_start : node.span.start].strip(b" \t") or not only_comments:
            raise ValueError("remove_command expects a command that has its line to itself")
        return self._reparsed(source[:line_start] + source[line_end:])

    def _reparsed(self, source: bytes) -> CMakeDocument:
        """用同一解析器重新解析编辑后的源码，诊断因此可信。
        Parse the edited source again with the same parser, so its diagnostics can be trusted.
        """
        return CMakeDocument.parse(
            source, source_name=self.tree.source_name, parser=self._parser_of()
        )

    def _line_ending(self) -> str:
        """本文档使用的换行符：源码里出现过 CRLF 时用 CRLF，否则用 LF。
        The line ending this document uses: CRLF when the source holds one, LF otherwise.
        """
        return "\r\n" if b"\r\n" in self.render_bytes() else "\n"

    def _with_tree(self, tree: SyntaxTree) -> CMakeDocument:
        """用编辑后的语法树构造同一解析器的新文档快照。
        Build a new document snapshot of the same parser from an edited syntax tree.
        """
        return CMakeDocument(tree, self._parser_of())

    def _parser_of(self) -> CMakeParser:
        """当前文档使用的 CMake 解析器。
        The CMake parser this document was built with.
        """
        parser = self._parser
        assert isinstance(parser, CMakeParser)
        return parser

    def _argument_fragment(self, text: str) -> SyntaxFragment:
        """把 text 解析成一条命令的一个参数，返回可插入的片段。
        Parse text as one argument of a command and return an insertable fragment.

        Raises:
            ValueError: text 不能作为单个 CMake 参数解析。
                text does not parse as a single CMake argument.
        """
        parsed = CMakeDocument.parse(f"x({text})", parser=self._parser_of())
        for view in parsed.command_views():
            arguments = view.arguments
            if len(arguments) == 1:
                return SyntaxFragment(self.language, arguments[0].node.green)
        raise ValueError(f"{text!r} is not a single CMake argument")
