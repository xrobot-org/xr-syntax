"""提供 CMake 命令与参数的轻量只读视图，保留原始源码文本和语法节点。
Convenience views for CMake commands and arguments.
"""

from __future__ import annotations

from dataclasses import dataclass

from xr_syntax.core import SyntaxElement, SyntaxNode

# ---------------------------------------------------------------------------
# 模块实现：提供 CMake 命令与参数的轻量只读视图，保留原始源码文本和语法节点。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CMakeArgumentView:
    """表示一个 CMake 参数的便捷视图，同时保留其原始语法文本。
    Convenience view of one CMake argument while retaining its original syntax text.
    """

    node: SyntaxElement

    @property
    def text(self) -> str:
        """返回该参数在源码中的精确文本。
        Return the exact source text of this CMake argument.
        """
        return self.node.text

    @property
    def syntax_kind(self) -> str:
        """返回该参数视图所代表的最具体 named syntax kind。
        Return the most specific named syntax kind represented by this view.
        """
        if isinstance(self.node, SyntaxNode):
            child = next(iter(self.node.named_syntax_children), None)
            if child is not None:
                return child.kind
        return self.node.kind


@dataclass(frozen=True)
class CMakeCommandView:
    """统一普通命令和块命令的名称与参数访问方式。
    Convenience view that normalizes the name/arguments of normal and block commands.
    """

    node: SyntaxNode

    @property
    def name(self) -> str:
        """返回普通命令或块命令统一后的命令名。
        Return normalized command spelling for normal or block command nodes.
        """
        if self.node.kind == "normal_command":
            for child in self.node.named_syntax_children:
                if child.kind == "identifier":
                    return child.text
        for child in self.node.syntax_children:
            if child.kind not in {"argument_list", "(", ")"}:
                return child.text
        return self.node.kind[:-8] if self.node.kind.endswith("_command") else self.node.kind

    @property
    def arguments(self) -> tuple[CMakeArgumentView, ...]:
        """按源码顺序返回该命令的参数视图。
        Return typed argument views in source order.
        """
        argument_list = self.node.first_descendant("argument_list")
        if not isinstance(argument_list, SyntaxNode):
            return ()
        return tuple(
            CMakeArgumentView(child)
            for child in argument_list.named_syntax_children
            if child.kind == "argument"
        )
