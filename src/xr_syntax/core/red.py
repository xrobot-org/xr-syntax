"""定义绑定到某一语法快照的 red 视图，为 green 元素补充父节点、字段、索引和字节偏移。
Parent-aware, position-aware views over immutable green syntax elements.
"""

from __future__ import annotations

from collections.abc import Iterator
from collections.abc import Set as AbstractSet
from typing import TYPE_CHECKING

from xr_syntax.core.green import GreenChild, GreenElement, GreenNode, GreenToken, GreenTrivia
from xr_syntax.core.span import SourceSpan

if TYPE_CHECKING:
    from xr_syntax.core.tree import SyntaxTree


# ---------------------------------------------------------------------------
# 绑定到具体快照的 red 视图
# Snapshot-specific red views
# ---------------------------------------------------------------------------


class SyntaxElement:
    """把 green 元素绑定到一个 SyntaxTree 快照。
    Snapshot-specific view that adds parent, field, index and byte offset to a green element.
    """

    __slots__ = ("_tree", "_green", "_parent", "_index", "_offset", "_field")

    def __init__(
        self,
        tree: SyntaxTree,
        green: GreenElement,
        *,
        parent: SyntaxNode | None,
        index: int,
        offset: int,
        field: str | None,
    ) -> None:
        """把 green 元素绑定到所属 SyntaxTree，并记录父节点、索引、偏移和 field。
        Bind a green element to its SyntaxTree and record parent, index, offset, and field metadata.
        """
        self._tree = tree
        self._green = green
        self._parent = parent
        self._index = index
        self._offset = offset
        self._field = field

    @property
    def tree(self) -> SyntaxTree:
        """返回该 red 元素所属的 SyntaxTree 快照。
        Return the owning syntax-tree snapshot.
        """
        return self._tree

    @property
    def green(self) -> GreenElement:
        """返回该 red 视图包装的不可变 green 元素。
        Return the wrapped immutable green element.
        """
        return self._green

    @property
    def parent(self) -> SyntaxNode | None:
        """返回父 SyntaxNode；根节点返回 None。
        Return the parent syntax node, or None for the root.
        """
        return self._parent

    @property
    def index(self) -> int:
        """返回该元素在父节点 children 中的结构索引。
        Return this element's structural child index.
        """
        return self._index

    @property
    def field(self) -> str | None:
        """返回父节点 edge 上的 parser field 名称；没有则返回 None。
        Return the parser field label on the parent edge, when present.
        """
        return self._field

    @property
    def kind(self) -> str:
        """返回该元素的语法 kind 拼写。
        Return the parser syntax-kind spelling.
        """
        return self._green.kind

    @property
    def span(self) -> SourceSpan:
        """返回该元素在原始源码中的半开字节范围。
        Return this element's half-open source byte span.
        """
        return SourceSpan(self._offset, self._offset + self._green.byte_width)

    @property
    def text(self) -> str:
        """原样返回该语法元素代表的源码文本。
        Return the exact source text represented by this syntax element.
        """
        return self._green.render()

    @property
    def is_trivia(self) -> bool:
        """判断该元素是否包装保留的 GreenTrivia。
        Report whether this element wraps preserved trivia.
        """
        return isinstance(self._green, GreenTrivia)

    def __repr__(self) -> str:
        """返回包含 kind 和 span 的调试字符串。
        Return a debug representation containing the syntax kind and source span.
        """
        return f"{type(self).__name__}(kind={self.kind!r}, span={self.span!r})"


# Red node 的 parent/offset 都从所属 SyntaxTree 快照派生。
# Red nodes derive parent/offset information from one owning SyntaxTree.
class SyntaxNode(SyntaxElement):
    """GreenNode 的 red 视图，提供 children、field 和 descendants 等查询能力。
    Parent-aware view of a GreenNode with traversal and field-query helpers.
    """

    @property
    def green(self) -> GreenNode:
        """返回当前 red 节点包装的 GreenNode。
        Return the wrapped immutable green element.
        """
        return self._green  # type: ignore[return-value]

    @property
    def named(self) -> bool:
        """返回 parser 对该节点的 named/anonymous 分类。
        Return the parser's named-versus-anonymous classification.
        """
        return self.green.named

    @property
    def missing(self) -> bool:
        """判断该节点是否由 parser 错误恢复过程合成。
        Report whether parser recovery synthesized this element.
        """
        return self.green.missing

    @property
    def error(self) -> bool:
        """判断该节点是否被标记为 parser error recovery。
        Report whether this element is marked as parser error recovery.
        """
        return self.green.error

    @property
    def children(self) -> tuple[SyntaxElement, ...]:
        """物化所有 red child，并按 green child 宽度推导绝对字节偏移。
        Materialize red child views and derive their absolute byte offsets in source order.
        """
        result: list[SyntaxElement] = []
        # 绝对位置由前序 child 的字节宽度推导。
        # Absolute positions are derived from preceding child byte widths.
        offset = self._offset
        for index, child in enumerate(self.green.children):
            result.append(
                _wrap(
                    self._tree,
                    child,
                    parent=self,
                    index=index,
                    offset=offset,
                )
            )
            offset += child.element.byte_width
        return tuple(result)

    @property
    def syntax_children(self) -> tuple[SyntaxElement, ...]:
        """返回 parser 语法 children，并排除 xr-syntax 自己补的 trivia gap。
        Return parser syntax children while excluding xr-syntax trivia gap objects.
        """
        return tuple(child for child in self.children if not child.is_trivia)

    @property
    def named_syntax_children(self) -> tuple[SyntaxElement, ...]:
        """返回 named node/token，排除匿名标点和 trivia。
        Return named parser nodes/tokens, excluding anonymous punctuation and trivia.
        """
        return tuple(
            child
            for child in self.syntax_children
            if (isinstance(child, (SyntaxNode, SyntaxToken)) and child.named)
        )

    @property
    def named_children(self) -> tuple[SyntaxNode, ...]:
        """只返回 named 的 SyntaxNode 子节点。
        Return named child nodes only.
        """
        return tuple(child for child in self.named_syntax_children if isinstance(child, SyntaxNode))

    def child_by_field(self, field: str) -> SyntaxElement | None:
        """返回指定 field 上的第一个 child；不存在时返回 None。
        Return the first child carried by a parser field with this name.
        """
        return next((child for child in self.children if child.field == field), None)

    def descendants(
        self,
        kind: str | None = None,
        *,
        kinds: AbstractSet[str] | None = None,
        include_self: bool = False,
        include_trivia: bool = False,
    ) -> Iterator[SyntaxElement]:
        """按深度优先顺序遍历后代，并支持 kind（或一组 kinds）和 trivia 过滤。
        Depth-first traversal of descendants with optional kind (or a set of kinds) and
        trivia filtering.

        只返回少数几类节点时用 kinds 一次遍历，比不加过滤地遍历再筛选快：不需要的 token
        不会创建 red 视图。
        For a few node kinds, one traversal with kinds is faster than an unfiltered one
        filtered afterwards: unwanted tokens get no red view.
        """
        if kind is not None and kinds is not None:
            raise ValueError("pass kind or kinds, not both")
        wanted = kinds if kinds is not None else (None if kind is None else {kind})
        if include_self and (wanted is None or self.kind in wanted):
            yield self
        yield from self._descendants(wanted, include_trivia)

    def _descendants(
        self, wanted: AbstractSet[str] | None, include_trivia: bool
    ) -> Iterator[SyntaxElement]:
        """descendants 的遍历：在 green 树上前进，只为节点和要返回的元素创建 red 视图。
        The traversal behind descendants: it walks the green tree and creates red views only
        for nodes and for the elements it returns.

        用显式栈代替递归生成器：递归时每返回一个元素都要经过各层生成器，深的树代价随深度增长。
        An explicit stack replaces recursive generators, where every element passed through
        one generator per level, so deep trees cost more with every level.
        """
        tree = self._tree
        # 每一层：父节点、它的 green 子元素、下一个下标、该子元素的字节偏移。
        # Each level: the parent, its green children, the next index and that child's offset.
        stack: list[tuple[SyntaxNode, tuple[GreenChild, ...], int, int]] = []
        parent, children, index, offset = self, self.green.children, 0, self._offset
        while True:
            if index == len(children):
                if not stack:
                    return
                parent, children, index, offset = stack.pop()
                continue
            child = children[index]
            green = child.element
            if isinstance(green, GreenNode):
                node = SyntaxNode(
                    tree, green, parent=parent, index=index, offset=offset, field=child.field
                )
                if wanted is None or green.kind in wanted:
                    yield node
                stack.append((parent, children, index + 1, offset + green.byte_width))
                parent, children, index = node, green.children, 0
                continue
            if wanted is None or green.kind in wanted:
                if isinstance(green, GreenToken):
                    yield SyntaxToken(
                        tree, green, parent=parent, index=index, offset=offset, field=child.field
                    )
                elif include_trivia:
                    yield SyntaxTrivia(
                        tree, green, parent=parent, index=index, offset=offset, field=child.field
                    )
            offset += green.byte_width
            index += 1

    def first_descendant(self, kind: str) -> SyntaxElement | None:
        """返回深度优先遍历中第一个指定 kind 的后代。
        Return the first depth-first descendant of the requested kind.
        """
        return next(self.descendants(kind), None)


class SyntaxToken(SyntaxElement):
    """不可变 GreenToken 在指定语法快照中的 red 视图。
    Red view of an immutable syntax token.
    """

    @property
    def green(self) -> GreenToken:
        """返回当前 red token 包装的 GreenToken。
        Return the wrapped immutable green element.
        """
        return self._green  # type: ignore[return-value]

    @property
    def named(self) -> bool:
        """返回 parser 对该 token 的 named/anonymous 分类。
        Return the parser's named-versus-anonymous classification.
        """
        return self.green.named

    @property
    def missing(self) -> bool:
        """判断该 token 是否由 parser 错误恢复过程合成。
        Report whether parser recovery synthesized this element.
        """
        return self.green.missing

    @property
    def error(self) -> bool:
        """判断该 token 是否被标记为 parser error recovery。
        Report whether this element is marked as parser error recovery.
        """
        return self.green.error


class SyntaxTrivia(SyntaxElement):
    """保留源码 trivia 在指定语法快照中的 red 视图。
    Red view of preserved source trivia that the parser did not expose as syntax.
    """

    @property
    def green(self) -> GreenTrivia:
        """返回当前 red trivia 包装的 GreenTrivia。
        Return the wrapped immutable green element.
        """
        return self._green  # type: ignore[return-value]


# 统一的 green -> red 适配入口。集中构造可确保所有 red 视图遵守同一套
# parent/index/offset 计算规则。
# Central green -> red adapter. Keep construction here so all red views use the
# same parent/index/offset rules.
def _wrap(
    tree: SyntaxTree,
    child: GreenChild,
    *,
    parent: SyntaxNode | None,
    index: int,
    offset: int,
) -> SyntaxElement:
    """根据 GreenChild 的具体类型创建对应 red 视图，并统一传递父节点和偏移信息。
    Create the matching red view for a GreenChild while propagating parent and offset information.
    """
    green = child.element
    if isinstance(green, GreenNode):
        return SyntaxNode(
            tree,
            green,
            parent=parent,
            index=index,
            offset=offset,
            field=child.field,
        )
    if isinstance(green, GreenToken):
        return SyntaxToken(
            tree,
            green,
            parent=parent,
            index=index,
            offset=offset,
            field=child.field,
        )
    return SyntaxTrivia(
        tree,
        green,
        parent=parent,
        index=index,
        offset=offset,
        field=child.field,
    )
