"""定义不可变、无绝对位置的 green 语法元素，用于持久化语法树和结构共享。
Immutable position-independent syntax storage used as the persistent tree representation.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Union

from xr_syntax.core.text import encode_source

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

    @cached_property
    def byte_width(self) -> int:
        """返回该 trivia 按源码编码后的字节宽度。
        Return the encoded source width in bytes.
        """
        text = self.text
        return len(text) if text.isascii() else len(encode_source(text))


@dataclass(frozen=True)
class GreenToken(_GreenMixin):
    """表示不可变的叶子 token，并保存它实际代表的源码文本。
    Immutable leaf syntax element containing exactly the represented source text.
    """

    kind: str
    text: str
    named: bool = False

    def render(self) -> str:
        """原样返回该 token 所保存的源码文本。
        Render this represented source without normalization.
        """
        return self.text

    @cached_property
    def byte_width(self) -> int:
        """返回该 token 按源码编码后的字节宽度。
        Return the encoded source width in bytes.
        """
        text = self.text
        return len(text) if text.isascii() else len(encode_source(text))


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

    def render(self) -> str:
        """按 children 顺序拼接并渲染当前节点代表的完整源码。
        Render this represented source without normalization.

        用显式栈遍历，树再深也不会递归。
        Walks with an explicit stack, so no tree is too deep for it.
        """
        parts: list[str] = []
        stack: list[GreenElement] = [self]
        while stack:
            element = stack.pop()
            if isinstance(element, GreenNode):
                stack += [child.element for child in reversed(element.children)]
            else:
                parts.append(element.text)
        return "".join(parts)

    @cached_property
    def byte_width(self) -> int:
        """返回全部 children 字节宽度之和。
        Return the encoded source width in bytes.
        """
        return sum(child.element.byte_width for child in self.children)


# ---------------------------------------------------------------------------
# parser 的快速构造
# Fast construction for the parser
# ---------------------------------------------------------------------------

# frozen dataclass 的 __init__ 对每个字段调用一次 object.__setattr__。parser 为每个 lexeme 创建一个
# token 和一条边，这里直接写实例字典；得到的对象与正常构造的对象相等，哈希也相同。
# A frozen dataclass __init__ calls object.__setattr__ once per field. The parser creates one
# token and one edge per lexeme, so these write the instance dictionary directly; the objects
# are equal to, and hash like, the normally constructed ones.
_new = object.__new__


def green_token(kind: str, text: str, named: bool) -> GreenToken:
    """与 GreenToken(kind, text, named=named) 相等的 token。
    A token equal to GreenToken(kind, text, named=named).
    """
    element = _new(GreenToken)
    fields = element.__dict__
    fields["kind"] = kind
    fields["text"] = text
    fields["named"] = named
    return element


def green_trivia(kind: str, text: str) -> GreenTrivia:
    """与 GreenTrivia(kind, text) 相等的 trivia。
    A trivia equal to GreenTrivia(kind, text).
    """
    element = _new(GreenTrivia)
    fields = element.__dict__
    fields["kind"] = kind
    fields["text"] = text
    return element


def green_child(element: GreenElement, field: str | None = None) -> GreenChild:
    """与 GreenChild(element, field) 相等的边。
    An edge equal to GreenChild(element, field).
    """
    child = _new(GreenChild)
    fields = child.__dict__
    fields["element"] = element
    fields["field"] = field
    return child


def green_node(
    kind: str, children: tuple[GreenChild, ...], byte_width: int | None = None
) -> GreenNode:
    """与 GreenNode(kind, children, named=True) 相等的节点；给出 byte_width 时不再从 children 求和。
    A node equal to GreenNode(kind, children, named=True); with byte_width given it is not summed
    from the children.
    """
    node = _new(GreenNode)
    fields = node.__dict__
    fields["kind"] = kind
    fields["children"] = children
    fields["named"] = True
    if byte_width is not None:
        # 写进 cached_property 的缓存位置。
        # Stored where the cached_property keeps its value.
        fields["byte_width"] = byte_width
    return node
