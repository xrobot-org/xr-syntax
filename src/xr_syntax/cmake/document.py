"""提供面向 CMake 的高层文档查询接口，底层仍使用语言无关的不可变语法模型。
High-level CMake document queries over the generic syntax model.
"""

from __future__ import annotations

from xr_syntax.core import SyntaxDocument, SyntaxElement, SyntaxNode

from .grammar import CMAKE_GRAMMAR
from .parser import CMakeParser
from .view import CMakeCommandView

# ---------------------------------------------------------------------------
# 基于共享语法核心实现的 CMake 文档查询
# CMake document queries using the shared syntax core
# ---------------------------------------------------------------------------


class CMakeDocument(SyntaxDocument):
    """在通用不可变语法树之上提供 CMake 专用查询和编辑接口。
    CMake-specific query facade over the same immutable syntax core used by C++.
    """

    __slots__ = ()

    language = "cmake"
    grammar = CMAKE_GRAMMAR

    @classmethod
    def parse(
        cls,
        source: str | bytes,
        *,
        source_name: str | None = None,
        parser: CMakeParser | None = None,
    ) -> CMakeDocument:
        """使用可选的固定版本 CMake grammar 解析文本或字节并创建文档快照。
        Parse CMake source using the optional pinned language-pack grammar.
        """
        selected = parser or CMakeParser()
        return cls(
            selected.parse(source, source_name=source_name),
            selected,
        )

    def comments(self) -> tuple[SyntaxElement, ...]:
        """按源码顺序返回全部 CMake 注释节点。
        Return CMake comments in source order.
        """
        return self.elements("comment")

    def commands(self, name: str | None = None) -> tuple[SyntaxNode, ...]:
        """返回 CMake 命令节点，并可按命令名进行大小写不敏感过滤。
        Return command nodes, optionally filtered case-insensitively by command name.
        """
        nodes = tuple(
            node
            for node in self.root.descendants(include_self=True)
            if isinstance(node, SyntaxNode)
            and (node.kind == "normal_command" or node.kind.endswith("_command"))
        )
        if name is None:
            return nodes
        normalized = name.casefold()
        return tuple(node for node in nodes if CMakeCommandView(node).name.casefold() == normalized)

    def command_views(self, name: str | None = None) -> tuple[CMakeCommandView, ...]:
        """返回类型化命令视图，并可按命令名过滤。
        Return typed command views, optionally filtered by command name.
        """
        return tuple(CMakeCommandView(node) for node in self.commands(name))

    def blocks(self) -> tuple[SyntaxNode, ...]:
        """返回 if、foreach、while、function、macro 等结构化块节点。
        Return structured block nodes such as if/foreach/while/function/macro constructs.
        """
        kinds = {
            "if_condition",
            "foreach_loop",
            "while_loop",
            "function_def",
            "macro_def",
        }
        return tuple(
            node
            for node in self.root.descendants(include_self=True)
            if isinstance(node, SyntaxNode) and node.kind in kinds
        )
