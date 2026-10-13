"""提供 CMake 命令与参数的轻量只读视图，保留原始源码文本和语法节点。
Convenience views for CMake commands and arguments.

视图只做记号层面的结构识别，不做变量展开、不做名字查找，也不判断命令是否合法；需要这些语义时由
调用方自己处理。
The views recognize structure at the token level only: no variable expansion, no name lookup and no
judgement about whether a command is valid. A caller that needs those semantics handles them itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from xr_syntax.core import SyntaxElement, SyntaxNode


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

        块节点（if_condition 等）取开启它的那条命令的名字，因此 if(...) 的块名是 if。大小写保持源码
        写法；比较时由调用方 casefold。
        A block node (if_condition and the like) takes the name of the command that opens it, so an
        if(...) block is named if. The case is kept as written; a caller that compares names
        casefolds them.
        """
        if self.node.kind == "normal_command":
            for child in self.node.named_syntax_children:
                if child.kind == "identifier":
                    return child.text
            return ""
        opening = next(
            (
                child
                for child in self.node.syntax_children
                if isinstance(child, SyntaxNode) and child.kind == "normal_command"
            ),
            None,
        )
        if opening is not None:
            return CMakeCommandView(opening).name
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
