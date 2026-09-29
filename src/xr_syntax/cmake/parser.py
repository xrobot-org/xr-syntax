"""CMake 源码解析器。
CMake source parser.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from xr_syntax.core import (
    Diagnostic,
    GreenChild,
    GreenElement,
    GreenNode,
    GreenToken,
    GreenTrivia,
    ParserKindInfo,
    ParserSchema,
    SourcePoint,
    SourceSpan,
    SyntaxTree,
    decode_source,
    encode_source,
)

from .grammar import CMAKE_GRAMMAR

# ---------------------------------------------------------------------------
# 模块实现：CMake 源码解析器。
# ---------------------------------------------------------------------------

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BLOCKS = {
    "if": ("endif", "if_condition"),
    "foreach": ("endforeach", "foreach_loop"),
    "while": ("endwhile", "while_loop"),
    "function": ("endfunction", "function_def"),
    "macro": ("endmacro", "macro_def"),
}


# 对外入口只负责建立 schema、调用结构扫描器，并检查最终字节无损。
class CMakeParser:
    """无损 CMake parser；parse 调用之间不共享可变状态。
    Lossless CMake parser whose parse calls do not share mutable parsing state.
    """

    grammar = CMAKE_GRAMMAR

    def __init__(self) -> None:
        """建立稳定的 kind/field 表。
        Build the stable kind and field table.
        """
        refs = {(node.kind, node.named) for node in self.grammar.nodes}
        for node in self.grammar.nodes:
            refs.update((item.kind, item.named) for item in node.subtypes)
            if node.children is not None:
                refs.update((item.kind, item.named) for item in node.children.types)
            for _, slot in node.fields:
                refs.update((item.kind, item.named) for item in slot.types)
        refs.update(
            {
                ("identifier", True),
                ("argument", True),
                ("argument_list", True),
                ("quoted_argument", True),
                ("bracket_argument", True),
                ("unquoted_argument", True),
                ("comment", True),
                ("(", False),
                (")", False),
            }
        )
        ordered = sorted(refs, key=lambda item: (item[0], item[1]))
        fields = sorted(
            {field_name for node in self.grammar.nodes for field_name, _ in node.fields}
        )
        self._schema = ParserSchema(
            "cmake",
            tuple(
                ParserKindInfo(index, name, named)
                for index, (name, named) in enumerate(ordered)
            ),
            tuple(fields),
        )

    @property
    def schema(self) -> ParserSchema:
        """返回 parser 的 kind/field 表。
        Return the parser kind and field table.
        """
        return self._schema

    def parse(self, source: str | bytes, *, source_name: str | None = None) -> SyntaxTree:
        """解析 CMake 源码。
        Parse CMake source into an immutable syntax tree.
        """
        data = encode_source(source) if isinstance(source, str) else bytes(source)
        text = decode_source(data)
        parser = _CMakeStructuralParser(text)
        root = parser.parse()
        tree = SyntaxTree("cmake", root, tuple(parser.diagnostics), source_name)
        if tree.render_bytes() != data:
            raise AssertionError("CMake parser broke the lossless round-trip invariant")
        return tree


# 第一阶段把文件线性切成 command/comment/trivia；第二阶段再把
# if()/foreach()/function()/macro() 等成对命令递归组合成 block 节点。
class _CMakeStructuralParser:
    """识别 CMake 命令、参数、注释和块结构。
    Recognize CMake commands, arguments, comments, and block structure.
    """

    def __init__(self, text: str) -> None:
        """保存待解析的源码文本。
        Store the source text to parse.
        """
        self.text = text
        self.length = len(text)
        self.diagnostics: list[Diagnostic] = []

    def parse(self) -> GreenNode:
        """解析整个 CMake 文件。
        Parse the complete CMake file.
        """
        children: list[GreenChild] = []
        cursor = 0
        while cursor < self.length:
            command = self._command_at(cursor)
            if command is not None:
                node, end = command
                children.append(GreenChild(node))
                cursor = end
                continue

            comment_end = self._comment_end(cursor)
            if comment_end is not None:
                children.append(
                    GreenChild(GreenToken("comment", self.text[cursor:comment_end], named=True))
                )
                cursor = comment_end
                continue

            next_start = self._next_structure(cursor + 1)
            children.append(GreenChild(self._trivia(self.text[cursor:next_start])))
            cursor = next_start

        # command 的词法边界先全部确定，再做 block 配对，避免扫描参数时
        # 同时维护嵌套 block 状态，保持 parser 状态机简单且可恢复。
        grouped, _ = self._group_blocks(children, 0, None)
        return GreenNode("source_file", tuple(grouped), named=True)

    def _next_structure(self, start: int) -> int:
        """查找下一个命令或注释起点。
        Find the next command or comment start.
        """
        cursor = start
        while cursor < self.length:
            if self._comment_end(cursor) is not None or self._command_at(cursor) is not None:
                return cursor
            cursor += 1
        return self.length

    def _command_at(self, start: int) -> tuple[GreenNode, int] | None:
        """尝试从指定位置解析一个命令。
        Parse a command starting at the given offset when present.
        """
        match = _IDENTIFIER.match(self.text, start)
        if match is None:
            return None
        name_end = match.end()
        cursor = name_end
        while cursor < self.length and self.text[cursor] in " \t\r\n":
            cursor += 1
        if cursor >= self.length or self.text[cursor] != "(":
            return None

        close = self._matching_paren(cursor)
        if close is None:
            self._diagnose("unterminated CMake command", cursor, self.length)
            close = self.length - 1 if self.length else cursor
            end = self.length
            closed = False
        else:
            end = close + 1
            closed = True

        children: list[GreenChild] = [
            GreenChild(GreenToken("identifier", self.text[start:name_end], named=True), "name")
        ]
        if name_end < cursor:
            children.append(GreenChild(self._trivia(self.text[name_end:cursor])))
        children.append(GreenChild(GreenToken("(", "(", named=False)))
        arg_end = close if closed else self.length
        children.append(
            GreenChild(self._argument_list(cursor + 1, arg_end), "arguments")
        )
        if closed:
            children.append(GreenChild(GreenToken(")", ")", named=False)))
        return GreenNode("normal_command", tuple(children), named=True), end

    def _matching_paren(self, opening: int) -> int | None:
        """查找与命令左括号匹配的右括号。
        Find the closing parenthesis matching a command opener.
        """
        depth = 1
        cursor = opening + 1
        while cursor < self.length:
            char = self.text[cursor]
            # 引号、bracket argument 和注释内部的括号都不是 command 括号，
            # 必须整体跳过后再更新 depth。
            if char == '"':
                cursor = self._quoted_end(cursor)
                continue
            bracket_end = self._bracket_end(cursor)
            if bracket_end is not None:
                cursor = bracket_end
                continue
            if char == "#":
                comment_end = self._comment_end(cursor)
                if comment_end is not None:
                    cursor = comment_end
                    continue
            if char == "\\":
                cursor = min(cursor + 2, self.length)
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return cursor
            cursor += 1
        return None

    def _argument_list(self, start: int, end: int) -> GreenNode:
        """解析命令参数区域。
        Parse the argument region of a command.
        """
        children: list[GreenChild] = []
        cursor = start
        while cursor < end:
            if self.text[cursor].isspace():
                next_cursor = cursor + 1
                while next_cursor < end and self.text[next_cursor].isspace():
                    next_cursor += 1
                children.append(GreenChild(self._trivia(self.text[cursor:next_cursor])))
                cursor = next_cursor
                continue

            comment_end = self._comment_end(cursor, limit=end)
            if comment_end is not None:
                children.append(
                    GreenChild(GreenToken("comment", self.text[cursor:comment_end], named=True))
                )
                cursor = comment_end
                continue

            if self.text[cursor] == '"':
                next_cursor = min(self._quoted_end(cursor), end)
                kind = "quoted_argument"
            else:
                bracket_end = self._bracket_end(cursor, limit=end)
                if bracket_end is not None:
                    next_cursor = bracket_end
                    kind = "bracket_argument"
                else:
                    next_cursor = self._unquoted_end(cursor, end)
                    kind = "unquoted_argument"

            token = GreenToken(kind, self.text[cursor:next_cursor], named=True)
            argument = GreenNode("argument", (GreenChild(token),), named=True)
            children.append(GreenChild(argument))
            cursor = next_cursor
        return GreenNode("argument_list", tuple(children), named=True)

    def _quoted_end(self, start: int) -> int:
        """扫描双引号参数并返回结束位置。
        Scan a quoted argument and return its end offset.
        """
        cursor = start + 1
        while cursor < self.length:
            if self.text[cursor] == "\\":
                cursor = min(cursor + 2, self.length)
                continue
            if self.text[cursor] == '"':
                return cursor + 1
            cursor += 1
        self._diagnose("unterminated quoted argument", start, self.length)
        return self.length

    def _bracket_end(self, start: int, limit: int | None = None) -> int | None:
        """扫描 bracket argument 或 bracket comment 的括号区间。
        Scan a bracket argument or bracket comment range.
        """
        end = self.length if limit is None else limit
        if start >= end or self.text[start] != "[":
            return None
        cursor = start + 1
        while cursor < end and self.text[cursor] == "=":
            cursor += 1
        if cursor >= end or self.text[cursor] != "[":
            return None
        marks = cursor - start - 1
        closing = "]" + ("=" * marks) + "]"
        found = self.text.find(closing, cursor + 1, end)
        if found < 0:
            self._diagnose("unterminated bracket argument", start, end)
            return end
        return found + len(closing)

    def _comment_end(self, start: int, limit: int | None = None) -> int | None:
        """扫描行注释或 bracket comment。
        Scan a line comment or bracket comment.
        """
        end = self.length if limit is None else limit
        if start >= end or self.text[start] != "#":
            return None
        bracket_end = self._bracket_end(start + 1, limit=end)
        if bracket_end is not None:
            return bracket_end
        newline = self.text.find("\n", start, end)
        return end if newline < 0 else newline

    def _unquoted_end(self, start: int, end: int) -> int:
        """扫描普通未加引号参数。
        Scan an unquoted argument.
        """
        cursor = start
        paren_depth = 0
        while cursor < end:
            char = self.text[cursor]
            if char == "\\":
                cursor = min(cursor + 2, end)
                continue
            if char.isspace() and paren_depth == 0:
                break
            if char == "(" and paren_depth >= 0:
                paren_depth += 1
            elif char == ")" and paren_depth > 0:
                paren_depth -= 1
            cursor += 1
        return max(cursor, start + 1)

    def _group_blocks(
        self,
        children: Sequence[GreenChild],
        start: int,
        closing_name: str | None,
    ) -> tuple[list[GreenChild], int]:
        """把成对的块命令组合为结构节点。
        Group paired block commands into structural nodes.
        """
        output: list[GreenChild] = []
        cursor = start
        while cursor < len(children):
            child = children[cursor]
            name = self._command_name(child.element)
            if closing_name is not None and name == closing_name:
                return output, cursor
            block = _BLOCKS.get(name or "")
            if block is None:
                output.append(child)
                cursor += 1
                continue

            expected_close, kind = block
            # 递归只处理已经切好的 command 序列；找不到闭合命令时保留原节点，
            # 同时记录诊断而不是丢弃后续源码。
            inner, close_index = self._group_blocks(children, cursor + 1, expected_close)
            if close_index >= len(children):
                output.append(child)
                output.extend(inner)
                self._diagnose("unterminated CMake block", 0, 0)
                return output, close_index
            grouped = [child, *inner, children[close_index]]
            output.append(GreenChild(GreenNode(kind, tuple(grouped), named=True)))
            cursor = close_index + 1
        return output, cursor

    @staticmethod
    def _command_name(element: GreenElement) -> str | None:
        """读取 normal_command 的小写名称。
        Return the case-folded name of a normal command.
        """
        if not isinstance(element, GreenNode) or element.kind != "normal_command":
            return None
        for child in element.children:
            if isinstance(child.element, GreenToken) and child.element.kind == "identifier":
                return child.element.text.casefold()
        return None

    @staticmethod
    def _trivia(text: str) -> GreenTrivia:
        """把未分类源码保存为 trivia。
        Preserve unclassified source as trivia.
        """
        if text.isspace():
            kind = "newline" if "\n" in text or "\r" in text else "whitespace"
        else:
            kind = "raw"
        return GreenTrivia(kind, text)

    def _diagnose(self, message: str, start: int, end: int) -> None:
        """记录一个源码范围诊断。
        Record a diagnostic for a source range.
        """
        byte_start = len(encode_source(self.text[:start]))
        byte_end = len(encode_source(self.text[:end]))
        start_point = self._point(start)
        end_point = self._point(end)
        self.diagnostics.append(
            Diagnostic(
                message,
                SourceSpan(byte_start, byte_end),
                start_point,
                end_point,
            )
        )

    def _point(self, offset: int) -> SourcePoint:
        """把字符偏移转换为字节列坐标。
        Convert a character offset to a row and byte column.
        """
        prefix = self.text[:offset]
        row = prefix.count("\n")
        last_newline = prefix.rfind("\n")
        column_text = prefix if last_newline < 0 else prefix[last_newline + 1 :]
        return SourcePoint(row, len(encode_source(column_text)))
