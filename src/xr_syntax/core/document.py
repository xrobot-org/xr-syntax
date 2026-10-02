"""定义语言无关的 SyntaxDocument：一个语法树快照及其查询。
The language-neutral SyntaxDocument: one syntax-tree snapshot and its queries.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from xr_syntax.core.diagnostic import Diagnostic
from xr_syntax.core.red import SyntaxElement, SyntaxNode
from xr_syntax.core.tree import SyntaxTree


class SyntaxParserProtocol(Protocol):
    """SyntaxDocument 需要的解析器接口。
    The parser interface SyntaxDocument needs.
    """

    def parse(
        self,
        source: str | bytes,
        *,
        source_name: str | None = None,
    ) -> SyntaxTree:
        """把源码文本或字节解析为一个不可变 SyntaxTree 快照。
        Parse text or bytes into one immutable syntax-tree snapshot.
        """
        ...


_DocumentT = TypeVar("_DocumentT", bound="SyntaxDocument")


class SyntaxDocument:
    """某一语言的不可变文档快照。
    An immutable document snapshot of one language.
    """

    __slots__ = ("tree", "_parser")

    language: str

    def __init__(
        self,
        tree: SyntaxTree,
        parser: SyntaxParserProtocol,
    ) -> None:
        """绑定语法树和解析器；解析器用于修改后重新解析。
        Bind a syntax tree and its parser; the parser reparses the source after a change.
        """
        if tree.language != self.language:
            raise ValueError(f"expected {self.language!r} syntax tree, got {tree.language!r}")
        self.tree = tree
        self._parser = parser

    @property
    def root(self) -> SyntaxNode:
        """当前文档快照的 red 根节点。
        The red root view of this document snapshot.
        """
        return self.tree.root

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        """解析时记录的诊断。
        The diagnostics recorded while parsing.
        """
        return self.tree.diagnostics

    def render(self) -> str:
        """按语法树中保存的源码内容原样渲染文本，不执行格式化。
        Render represented source text without applying formatting rules.
        """
        return self.tree.render()

    def render_bytes(self) -> bytes:
        """按原始编码规则渲染源码字节，并保留 surrogateescape 字节。
        Render represented source bytes while preserving surrogate-escaped input.
        """
        return self.tree.render_bytes()

    def elements(self, kind: str) -> tuple[SyntaxElement, ...]:
        """按源码顺序返回 kind 相同的全部节点和 token。
        All nodes and tokens of the given kind, in source order.
        """
        return tuple(self.root.descendants(kind, include_self=True))

    def nodes(self, kind: str) -> tuple[SyntaxNode, ...]:
        """按源码顺序返回 kind 相同的节点。
        The nodes of the given kind, in source order.
        """
        return tuple(element for element in self.elements(kind) if isinstance(element, SyntaxNode))

    def _reparse(self: _DocumentT, source: bytes) -> _DocumentT:
        """用同一个解析器重新解析修改后的源码，得到新的文档快照。
        Reparse changed source with the same parser into a new document snapshot.
        """
        tree = self._parser.parse(source, source_name=self.tree.source_name)
        return type(self)(tree, self._parser)
