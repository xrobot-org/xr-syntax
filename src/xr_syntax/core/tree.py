"""定义不可变 SyntaxTree 快照以及底层 replace/remove/insert 结构编辑操作。
Immutable syntax-tree snapshot and low-level structural edit operations.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from dataclasses import dataclass

from .diagnostic import Diagnostic
from .fragment import SyntaxFragment
from .green import GreenChild, GreenElement, GreenNode, GreenTrivia
from .red import SyntaxElement, SyntaxNode
from .text import encode_source

# ---------------------------------------------------------------------------
# SyntaxTree 快照与 persistent green-tree 编辑
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SyntaxTree:
    """保存某一语言不可变语法快照的核心状态。
    Immutable language syntax snapshot backed by a green root.
    """

    language: str
    green_root: GreenNode
    diagnostics: tuple[Diagnostic, ...] | None = ()
    source_name: str | None = None

    @property
    def root(self) -> SyntaxNode:
        """创建并返回当前不可变语法快照的 red 根节点。
        Create the red root view for this immutable snapshot.
        """
        return SyntaxNode(
            self,
            self.green_root,
            parent=None,
            index=0,
            offset=0,
            field=None,
        )

    @property
    def diagnostic_state(self) -> str:
        """返回 clean、diagnosed 或 unknown 三种诊断状态。
        Return the diagnostic state: clean, diagnosed, or unknown.
        """
        if self.diagnostics is None:
            return "unknown"
        return "diagnosed" if self.diagnostics else "clean"

    def render(self) -> str:
        """按 green root 原样渲染完整源码文本。
        Render the complete represented source without normalization.
        """
        return self._source_text

    def render_bytes(self) -> bytes:
        """按源码编码原样渲染完整源码字节。
        Render the complete represented source as bytes.
        """
        return self._source_bytes

    # 快照不可变，渲染结果只计算一次；行号、invocation 文本和解析后的无损检查都会用到它。
    # The snapshot is immutable, so it is rendered once; line numbers, invocation texts and
    # the lossless check after parsing all use the result.
    @functools.cached_property
    def _source_text(self) -> str:
        """渲染一次的源码文本。
        The source text, rendered once.
        """
        return self.green_root.render()

    @functools.cached_property
    def _source_bytes(self) -> bytes:
        """编码一次的源码字节。
        The source bytes, encoded once.
        """
        return encode_source(self._source_text)

    # 这里的低层编辑只沿 target.path 重建祖先链；路径之外的 green subtree
    # 继续复用原对象。高层 Document 在需要恢复 parser field/diagnostic 时再 reparse。
    def replace(
        self,
        target: SyntaxElement,
        replacement: SyntaxElement | SyntaxFragment,
    ) -> SyntaxTree:
        """持久化替换一个元素，仅重建目标到根路径上的节点。
        Persistently replace one element, reusing unaffected green subtrees.
        """
        self._check_target(target)
        green = self._coerce_insertable(replacement)
        if not target.path:
            if not isinstance(green, GreenNode):
                raise TypeError("syntax tree root must remain a GreenNode")
            return self._with_root(green)
        return self._with_root(_replace_at(self.green_root, target.path, green))

    def remove(self, target: SyntaxElement) -> SyntaxTree:
        """持久化删除一个非根元素。
        Persistently remove one non-root element.
        """
        self._check_target(target)
        if not target.path:
            raise ValueError("cannot remove the syntax tree root")
        return self._with_root(_remove_at(self.green_root, target.path))

    def insert_before(
        self,
        target: SyntaxElement,
        element: SyntaxElement | SyntaxFragment,
        *,
        separator: str = "",
    ) -> SyntaxTree:
        """在非根目标元素前持久化插入一个元素。
        Persistently insert one element before a non-root target.
        """
        self._check_target(target)
        if not target.path:
            raise ValueError("cannot insert beside the syntax tree root")
        green = self._coerce_insertable(element)
        additions: list[GreenElement] = [green]
        if separator:
            additions.append(GreenTrivia("raw", separator))
        return self._with_root(_insert_at(self.green_root, target.path, additions, before=True))

    def insert_after(
        self,
        target: SyntaxElement,
        element: SyntaxElement | SyntaxFragment,
        *,
        separator: str = "",
    ) -> SyntaxTree:
        """在非根目标元素后持久化插入一个元素。
        Persistently insert one element after a non-root target.
        """
        self._check_target(target)
        if not target.path:
            raise ValueError("cannot insert beside the syntax tree root")
        green = self._coerce_insertable(element)
        additions: list[GreenElement] = []
        if separator:
            additions.append(GreenTrivia("raw", separator))
        additions.append(green)
        return self._with_root(_insert_at(self.green_root, target.path, additions, before=False))

    def _check_target(self, target: SyntaxElement) -> None:
        """确认待编辑 red 元素属于当前 SyntaxTree 快照。
        Verify that the edited red element belongs to this SyntaxTree snapshot.
        """
        if target.tree is not self:
            raise ValueError("target belongs to a different immutable syntax snapshot")

    def _coerce_insertable(
        self,
        value: SyntaxElement | SyntaxFragment,
    ) -> GreenElement:
        """取得可插入 green 元素并校验语言归属。
        Resolve an insertable green element and validate its language provenance.
        """
        if isinstance(value, SyntaxElement):
            if value.tree.language != self.language:
                raise ValueError(
                    f"element language {value.tree.language!r} does not match tree language "
                    f"{self.language!r}"
                )
            return value.green
        if isinstance(value, SyntaxFragment):
            return value.green_for(self.language)
        raise TypeError(
            "low-level edits accept SyntaxElement or SyntaxFragment; "
            "wrap generated/raw green data in SyntaxFragment with an explicit language"
        )

    def _with_root(self, root: GreenNode) -> SyntaxTree:
        """用新 green root 构造诊断状态未知的新 SyntaxTree。
        Create a new SyntaxTree whose diagnostics are unknown until reparsed.
        """
        return SyntaxTree(
            language=self.language,
            green_root=root,
            diagnostics=None,
            source_name=self.source_name,
        )


# ---------------------------------------------------------------------------
# 结构路径递归操作：只处理 green tree，不触碰 parser/diagnostic
# ---------------------------------------------------------------------------


def _replace_at(
    root: GreenNode,
    path: tuple[int, ...],
    element: GreenElement,
) -> GreenNode:
    """按结构路径递归替换 green 元素，并复用路径外的子树。
    Recursively replace a green element by structural path while reusing subtrees outside the path.
    """
    index = path[0]
    if len(path) == 1:
        return root.replacing_child(index, element)
    child = root.children[index].element
    if not isinstance(child, GreenNode):
        raise ValueError("rewrite path crosses a non-node")
    return root.replacing_child(index, _replace_at(child, path[1:], element))


def _remove_at(root: GreenNode, path: tuple[int, ...]) -> GreenNode:
    """按结构路径递归删除 green 元素，并复用路径外的子树。
    Recursively remove a green element by structural path while reusing subtrees outside the path.
    """
    index = path[0]
    if len(path) == 1:
        return root.removing_child(index)
    child = root.children[index].element
    if not isinstance(child, GreenNode):
        raise ValueError("rewrite path crosses a non-node")
    return root.replacing_child(index, _remove_at(child, path[1:]))


def _insert_at(
    root: GreenNode,
    path: tuple[int, ...],
    additions: Iterable[GreenElement],
    *,
    before: bool,
) -> GreenNode:
    """按结构路径递归插入 green 元素，并复用路径外的子树。
    Recursively insert green elements by structural path while reusing subtrees outside the path.
    """
    index = path[0]
    if len(path) == 1:
        children = list(root.children)
        insert_index = index if before else index + 1
        for element in reversed(list(additions)):
            children.insert(insert_index, GreenChild(element))
        return GreenNode(
            root.kind,
            tuple(children),
            root.named,
            root.missing,
            root.error,
        )
    child = root.children[index].element
    if not isinstance(child, GreenNode):
        raise ValueError("rewrite path crosses a non-node")
    return root.replacing_child(
        index,
        _insert_at(child, path[1:], additions, before=before),
    )
