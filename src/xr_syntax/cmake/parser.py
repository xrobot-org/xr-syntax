"""CMake 源码解析器。
CMake source parser.

两阶段解析：第一阶段把文件线性切成命令、注释和 trivia；第二阶段把成对的块命令
（if/foreach/while/function/macro/block）递归组合成结构节点。解析无损：结束时断言渲染出的字节与输入
相同。解析调用之间不共享可变状态，同一个解析器实例可以被多线程并发使用。
Two-stage parsing: the first stage cuts the file into commands, comments and trivia linearly; the
second groups paired block commands (if/foreach/while/function/macro/block) into structural
nodes. The
parse is lossless: it asserts at the end that the rendered bytes equal the input. Parse calls share
no mutable state, so one parser instance may be used from several threads.
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
    SourcePoint,
    SourceSpan,
    SyntaxTree,
    decode_source,
    encode_source,
)
from xr_syntax.i18n import tr

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# 开启一个块的命令、它的结束命令，以及组合出的节点 kind。
# The command that opens a block, the command that ends it, and the kind of the grouped node.
_BLOCKS = {
    "block": ("endblock", "block"),
    "foreach": ("endforeach", "foreach_loop"),
    "function": ("endfunction", "function_def"),
    "if": ("endif", "if_condition"),
    "macro": ("endmacro", "macro_def"),
    "while": ("endwhile", "while_loop"),
}


class CMakeParser:
    """无损 CMake 解析器；parse 调用之间不共享可变状态。
    Lossless CMake parser whose parse calls do not share mutable parsing state.
    """

    def parse(self, source: str | bytes, *, source_name: str | None = None) -> SyntaxTree:
        """解析 CMake 源码，返回不可变语法树。
        Parse CMake source into an immutable syntax tree.

        Raises:
            AssertionError: 解析结果渲染出的字节与输入不同（无损不变量被破坏）。
                The rendered bytes differ from the input, which breaks the lossless invariant.
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
# if()/foreach()/block() 等成对命令递归组合成 block 节点。
# The first stage cuts the file into command/comment/trivia linearly; the second groups paired
# commands such as if()/foreach()/block() into block nodes recursively.
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
        # 已经记过的诊断（消息与起点），用于去重。
        # The diagnostics already reported, by message and start, used to drop repeats.
        self._reported: set[tuple[str, int]] = set()

    def parse(self) -> GreenNode:
        """解析整个 CMake 文件。
        Parse the complete CMake file.
        """
        children: list[GreenChild] = []
        starts: list[int] = []
        cursor = 0
        while cursor < self.length:
            command = self._command_at(cursor)
            if command is not None:
                node, end = command
                children.append(GreenChild(node))
                starts.append(cursor)
                cursor = end
                continue

            comment_end = self._comment_end(cursor)
            if comment_end is not None:
                children.append(
                    GreenChild(GreenToken("comment", self.text[cursor:comment_end], named=True))
                )
                starts.append(cursor)
                cursor = comment_end
                continue

            next_start = self._next_structure(cursor + 1)
            children.append(GreenChild(self._trivia(self.text[cursor:next_start])))
            starts.append(cursor)
            cursor = next_start

        self._check_command_lines(children, starts)

        # command 的词法边界先全部确定，再做 block 配对，避免扫描参数时同时维护嵌套 block 状态，
        # 保持 parser 状态机简单且可恢复。
        # The lexical bounds of every command are settled before block pairing, so scanning arguments
        # never has to maintain nesting state at the same time and the parser stays simple and
        # recoverable.
        grouped, _ = self._group_blocks(children, 0, None)
        return GreenNode("source_file", tuple(grouped), named=True)

    def _check_command_lines(self, children: Sequence[GreenChild], starts: Sequence[int]) -> None:
        """检查每条命令都另起一行：同一行里命令前面只能有空白。
        Check that every command starts a line: only blanks may precede it on its line.

        这与 cmake 一致：命令前面有另一条命令、bracket 注释或其他文字时，cmake 报 "Expected a
        newline"。bracket 注释内部的换行不结束一行，所以 ``set(A 1) #[[ c\\n ]] set(B 2)`` 里的
        第二条命令仍在第一条所在的行上。
        This matches cmake, which reports "Expected a newline" when another command, a bracket
        comment or other text precedes a command on its line. A newline inside a bracket comment does
        not end the line, so the second command of ``set(A 1) #[[ c\\n ]] set(B 2)`` is still on
        the line of the first.
        """
        line_is_blank = True
        for index, child in enumerate(children):
            element = child.element
            if isinstance(element, GreenTrivia):
                # 只有 trivia 里的换行结束一行；行注释的换行也落在它后面的 trivia 里。
                # Only a newline in trivia ends a line; the newline of a line comment is in the
                # trivia after it as well.
                text = element.text
                if starts[index] == 0:
                    # 文件开头的 UTF-8 BOM 不算文字，cmake 同样接受。
                    # A UTF-8 BOM at the start of the file is not text; cmake accepts it as well.
                    text = text.removeprefix("﻿")
                rest = text.rsplit("\n", 1)
                if len(rest) == 2:
                    line_is_blank = rest[1].strip(" \t") == ""
                else:
                    line_is_blank = line_is_blank and rest[0].strip(" \t") == ""
                continue
            if self._command_name(element) is not None and not line_is_blank:
                # children 依次铺满整份源码：命令的末尾就是下一个元素的起点。
                # The children tile the whole source: a command ends where the next element starts.
                end = starts[index + 1] if index + 1 < len(children) else self.length
                self._diagnose(
                    tr(
                        "expected a newline before this CMake command",
                        "CMake 命令必须另起一行",
                    ),
                    starts[index],
                    end,
                )
            line_is_blank = False

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
            self._diagnose(
                tr("unterminated CMake command", "CMake 命令没有结束"), cursor, self.length
            )
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
        children.append(GreenChild(self._argument_list(cursor + 1, arg_end), "arguments"))
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
            # 引号、bracket argument 和注释内部的括号都不是 command 括号，必须整体跳过后再更新
            # depth。
            # A parenthesis inside a quoted argument, a bracket argument or a comment is not a
            # command parenthesis, so the whole of it is skipped before depth changes.
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
        self._diagnose(tr("unterminated quoted argument", "引号参数没有结束"), start, self.length)
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
            self._diagnose(tr("unterminated bracket argument", "括号参数没有结束"), start, end)
            return end
        return found + len(closing)

    def _comment_end(self, start: int, limit: int | None = None) -> int | None:
        """扫描行注释或 bracket comment。
        Scan a line comment or bracket comment.

        行注释在行末换行之前结束；CRLF 的 \\r 属于换行而不是注释，因此不计入注释文本，区域的
        body span 才落在整行之后而不是行末 \\r 与 \\n 之间。
        A line comment ends before the line ending; the \\r of a CRLF belongs to the line ending and
        not to the comment, so a region's body span starts after the whole line instead of between
        its \\r and \\n.
        """
        end = self.length if limit is None else limit
        if start >= end or self.text[start] != "#":
            return None
        bracket_end = self._bracket_end(start + 1, limit=end)
        if bracket_end is not None:
            return bracket_end
        newline = self.text.find("\n", start, end)
        if newline < 0:
            return end
        if newline > start and self.text[newline - 1] == "\r":
            return newline - 1
        return newline

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
            # 递归只处理已经切好的 command 序列；找不到闭合命令时保留原节点，同时记录诊断而不是
            # 丢弃后续源码。诊断只记最外面那一层：内层递归的 close_index 同样是 len(children)，
            # 但它们不急着报告，而是回到这里由唯一持有 opener 的这一层报一次，位置是开块的命令。
            # The recursion only walks the already-cut command sequence; a missing closing command
            # keeps the original node and records a diagnostic instead of dropping the source after
            # it. Only the outermost level reports: an inner recursion sees the same
            # close_index == len(children) and waits, so the one level that holds the opener reports
            # once, at the command that opens the block.
            inner, close_index = self._group_blocks(children, cursor + 1, expected_close)
            if close_index >= len(children):
                output.append(child)
                output.extend(inner)
                if closing_name is None:
                    start = sum(item.element.byte_width for item in children[:cursor])
                    self._diagnose(
                        tr(
                            "unterminated CMake block: {expected} is missing",
                            "CMake 块没有结束：缺少 {expected}",
                        ).format(expected=expected_close),
                        start,
                        start + child.element.byte_width,
                    )
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
        self._append(Diagnostic(message, SourceSpan(byte_start, byte_end), start_point, end_point))

    def _append(self, diagnostic: Diagnostic) -> None:
        """追加一条诊断；同一起点同一条消息的诊断只记一次。
        Append one diagnostic; a diagnostic of the same message at the same start is kept once.

        同一个问题可能被多个路径扫到：未闭合的引号让整个命令扫描失败、又让命令本身没有结束。只记
        最里面那一次，否则用户会看到同一个问题被报告两三遍。
        One problem can be found by several paths: an unterminated quote makes the command scan fail
        and also leaves the command itself unterminated. Only the innermost finding is kept, or the
        user sees the same problem reported two or three times.
        """
        key = (diagnostic.message, diagnostic.span.start)
        if key not in self._reported:
            self._reported.add(key)
            self.diagnostics.append(diagnostic)

    def _point(self, offset: int) -> SourcePoint:
        """把字符偏移转换为字节列坐标。
        Convert a character offset to a row and byte column.
        """
        prefix = self.text[:offset]
        row = prefix.count("\n")
        last_newline = prefix.rfind("\n")
        column_text = prefix if last_newline < 0 else prefix[last_newline + 1 :]
        return SourcePoint(row, len(encode_source(column_text)))
