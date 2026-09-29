"""定义不可变、无绝对位置的 green 语法元素，用于持久化语法树和结构共享。
Immutable position-independent syntax storage used as the persistent tree representation.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Union

from .text import encode_source

# ---------------------------------------------------------------------------
# 不可变 green 存储层
# Immutable green storage
# ---------------------------------------------------------------------------


class _GreenMixin:
    """定义所有 green 元素共同需要提供的渲染和字节宽度接口。
    Define the rendering and byte-width interface shared by all green elements.
    """

    def render(self) -> str:
        """渲染当前 green 元素所代表的源码文本。
        Render the source text represented by this green element.
        """
        raise NotImplementedError

    @property
    def byte_width(self) -> int:
        """返回当前 green 元素按源码编码后的字节宽度。
        Return the encoded byte width of this green element.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class GreenTrivia(_GreenMixin):
    """表示 parser 未作为语法 child 暴露、但为逐字节 round-trip 必须原样保存的空白或源码间隙。
    Immutable source text that is not represented as a parser syntax child.
    """

    kind: str
    text: str

    def render(self) -> str:
        """原样返回该 trivia 所保存的源码文本。
        Render this represented source without normalization.
        """
        return self.text

    @property
    def byte_width(self) -> int:
        """返回该 trivia 按源码编码后的字节宽度。
        Return the encoded source width in bytes.
        """
        return len(encode_source(self.text))


@dataclass(frozen=True)
class GreenToken(_GreenMixin):
    """表示不可变的叶子 token，并保存它实际代表的源码文本。
    Immutable leaf syntax element containing exactly the represented source text.
    """

    kind: str
    text: str
    named: bool = False
    missing: bool = False
    error: bool = False

    def render(self) -> str:
        """原样返回该 token 所保存的源码文本。
        Render this represented source without normalization.
        """
        return self.text

    @property
    def byte_width(self) -> int:
        """返回该 token 按源码编码后的字节宽度。
        Return the encoded source width in bytes.
        """
        return len(encode_source(self.text))


# 每个 green child 要么是语法 node/token，要么是必须保留的源码 trivia。
# Every green child is either syntax (node/token) or preserved source trivia.
GreenElement = Union["GreenNode", "GreenToken", "GreenTrivia"]


@dataclass(frozen=True)
class GreenChild:
    """表示 GreenNode 到子元素的一条边，并携带可选 field 标签。
    One child edge in a green node, including the parser field name when available.
    """

    element: GreenElement
    field: str | None = None


# GreenNode 不保存 parent 指针和绝对位置；这些信息属于 red 视图层。
# 因而未变化的 green 子树可以安全地在多个不可变快照之间复用。
# Green nodes never carry parent pointers or absolute positions. Those belong to
# the red view layer, which keeps green subtrees reusable across snapshots.
@dataclass(frozen=True)
class GreenNode(_GreenMixin):
    """表示不可变且与绝对位置无关的语法节点。
    Immutable, position-independent syntax node.
    """

    kind: str
    children: tuple[GreenChild, ...]
    named: bool = True
    missing: bool = False
    error: bool = False

    def render(self) -> str:
        """按 children 顺序拼接并渲染当前节点代表的完整源码。
        Render this represented source without normalization.
        """
        return "".join(child.element.render() for child in self.children)

    @cached_property
    def byte_width(self) -> int:
        """返回全部 children 字节宽度之和。
        Return the encoded source width in bytes.
        """
        return sum(child.element.byte_width for child in self.children)

    def replacing_child(self, index: int, element: GreenElement) -> GreenNode:
        """返回替换指定 child 后的新 GreenNode，并保留原 edge 的 field 标签。
        Return a copy with one child replaced while preserving that edge's field label.
        """
        if index < 0 or index >= len(self.children):
            raise IndexError(index)
        children = list(self.children)
        original = children[index]
        children[index] = GreenChild(element=element, field=original.field)
        return GreenNode(
            kind=self.kind,
            children=tuple(children),
            named=self.named,
            missing=self.missing,
            error=self.error,
        )

    def inserting_child(
        self,
        index: int,
        element: GreenElement,
        *,
        field: str | None = None,
    ) -> GreenNode:
        """返回在指定结构索引插入 child 后的新 GreenNode。
        Return a copy with a new child inserted at the requested structural index.
        """
        if index < 0 or index > len(self.children):
            raise IndexError(index)
        children = list(self.children)
        children.insert(index, GreenChild(element=element, field=field))
        return GreenNode(
            kind=self.kind,
            children=tuple(children),
            named=self.named,
            missing=self.missing,
            error=self.error,
        )

    def removing_child(self, index: int) -> GreenNode:
        """返回移除指定 child 后的新 GreenNode。
        Return a copy without the selected child.
        """
        if index < 0 or index >= len(self.children):
            raise IndexError(index)
        children = list(self.children)
        del children[index]
        return GreenNode(
            kind=self.kind,
            children=tuple(children),
            named=self.named,
            missing=self.missing,
            error=self.error,
        )
