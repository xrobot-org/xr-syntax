"""定义语言无关的 SyntaxDocument 外观，统一查询、不可变编辑和编辑后的重新解析。
Language-neutral document facade for querying and safely editing syntax trees.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, TypeVar

from .diagnostic import Diagnostic
from .fragment import SyntaxFragment
from .grammar import GrammarNodeSpec, LanguageGrammar
from .red import SyntaxElement, SyntaxNode, SyntaxToken
from .tree import SyntaxTree

# ---------------------------------------------------------------------------
# 语言无关的文档外观
# Language-neutral document facade
# ---------------------------------------------------------------------------


class SyntaxParserProtocol(Protocol):
    """规定 SyntaxDocument 所需的最小解析器接口。
    Minimal parser contract required by SyntaxDocument.
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


DocumentT = TypeVar("DocumentT", bound="SyntaxDocument")


class SyntaxDocument:
    """表示某一语言的不可变文档快照。
    Language-neutral immutable document facade over one SyntaxTree snapshot.
    """

    __slots__ = ("tree", "_parser")

    language: str
    grammar: ClassVar[LanguageGrammar | None] = None

    def __init__(
        self,
        tree: SyntaxTree,
        parser: SyntaxParserProtocol,
    ) -> None:
        """绑定语法树、解析器和可选 grammar，形成一个不可变文档快照。
        Bind a syntax tree, parser, and optional grammar into one immutable document snapshot.
        """
        if tree.language != self.language:
            raise ValueError(f"expected {self.language!r} syntax tree, got {tree.language!r}")
        self.tree = tree
        self._parser = parser

    @property
    def root(self) -> SyntaxNode:
        """返回当前文档快照的 red 根节点。
        Return the red root view for this document snapshot.
        """
        return self.tree.root

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        """返回当前已解析文档的诊断。
        Return diagnostics for this parsed document snapshot.
        """
        diagnostics = self.tree.diagnostics
        if diagnostics is None:
            raise RuntimeError("document diagnostics are unknown; reparse the syntax tree first")
        return diagnostics

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

    def grammar_spec(self, element: SyntaxElement) -> GrammarNodeSpec | None:
        """把解析得到的元素映射回对应的版本化 grammar 结构合同。
        Map a parsed node/token back to its versioned grammar contract when available.
        """
        grammar = self.grammar
        if grammar is None or not isinstance(element, (SyntaxNode, SyntaxToken)):
            return None
        return grammar.node(element.kind, named=element.named)

    # 高层编辑后重新解析，刷新 field 和 diagnostics；底层 tree 仍可复用 green 子树。
    # High-level edits reparse to refresh fields and diagnostics; low-level edits still reuse green subtrees.
    def replace(
        self: DocumentT,
        target: SyntaxElement,
        replacement: SyntaxElement | SyntaxFragment,
    ) -> DocumentT:
        """替换一个语法元素，重新解析结果并返回新的文档快照。
        Replace one element and return a new reparsed document snapshot.
        """
        return self._reparse(self.tree.replace(target, replacement).render_bytes())

    def remove(self: DocumentT, target: SyntaxElement) -> DocumentT:
        """删除一个语法元素，重新解析结果并返回新的文档快照。
        Remove one element and return a new reparsed document snapshot.
        """
        return self._reparse(self.tree.remove(target).render_bytes())

    def insert_before(
        self: DocumentT,
        target: SyntaxElement,
        element: SyntaxElement | SyntaxFragment,
        *,
        separator: str = "",
    ) -> DocumentT:
        """在目标元素前插入新元素，重新解析并返回新的文档快照。
        Insert an element before a target and return a new reparsed document snapshot.
        """
        changed = self.tree.insert_before(target, element, separator=separator)
        return self._reparse(changed.render_bytes())

    def insert_after(
        self: DocumentT,
        target: SyntaxElement,
        element: SyntaxElement | SyntaxFragment,
        *,
        separator: str = "",
    ) -> DocumentT:
        """在目标元素后插入新元素，重新解析并返回新的文档快照。
        Insert an element after a target and return a new reparsed document snapshot.
        """
        changed = self.tree.insert_after(target, element, separator=separator)
        return self._reparse(changed.render_bytes())

    def elements(self, kind: str) -> tuple[SyntaxElement, ...]:
        """返回匹配 kind 的全部语法元素，包括 named token 与 node。
        Return all matching syntax elements, including named tokens as well as nodes.
        """
        return tuple(self.root.descendants(kind, include_self=True))

    def nodes(self, kind: str) -> tuple[SyntaxNode, ...]:
        """只返回匹配 kind 的 SyntaxNode 节点。
        Return only matching SyntaxNode objects.
        """
        return tuple(element for element in self.elements(kind) if isinstance(element, SyntaxNode))

    def _reparse(self: DocumentT, source: bytes) -> DocumentT:
        # 在语言文档边界统一重新解析，确保 field、诊断和错误恢复结构始终
        # 来源于真正拥有它们的 parser。以后可在不改变 API 的前提下做增量优化。
        # Reparse at the language-document boundary so fields, diagnostics, and recovery
        # structure always come from the parser that owns them. Incremental reparsing can
        # be added later without changing the public API.
        """把底层编辑结果渲染为字节并重新解析，以刷新 field 和诊断。
        Render the edited bytes and reparse them to refresh fields and diagnostics.
        """
        tree = self._parser.parse(source, source_name=self.tree.source_name)
        return type(self)(tree, self._parser)
