"""验证语法树遍历：深度优先顺序、kind 和 kinds 过滤以及渲染结果。
Test syntax-tree traversal: depth-first order, kind and kinds filtering, and rendering.
"""

import pytest

from xr_syntax.core.red import SyntaxNode
from xr_syntax.cpp import CppDocument

SOURCE = """#if defined(USE_A)
class A { public: A(int x) {} };
#endif
namespace n { struct B { int y = 1; }; }
"""


def test_kinds_returns_the_same_elements_as_filtering_the_whole_walk() -> None:
    """验证 kinds 过滤与完整遍历后筛选得到同样的元素、同样的顺序。
    Verify that kinds gives the same elements in the same order as filtering the whole walk.
    """
    root = CppDocument.parse(SOURCE).root
    wanted = {"class_specifier", "struct_specifier", "preproc_ifdef", "preproc_if"}

    def key(element: object) -> tuple:
        """用于比较的节点特征：kind、span 和父节点的 span。
        What identifies a node for the comparison: kind, span and the parent's span.
        """
        assert isinstance(element, SyntaxNode)
        parent = element.parent
        return (element.kind, element.span, None if parent is None else parent.span)

    everything = [key(e) for e in root.descendants() if e.kind in wanted]
    assert [key(e) for e in root.descendants(kinds=wanted)] == everything
    assert [e.kind for e in root.descendants(kinds=wanted)] == [
        "preproc_if",
        "class_specifier",
        "struct_specifier",
    ]
    assert [key(e) for e in root.descendants("class_specifier")] == [everything[1]]
    with pytest.raises(ValueError, match="pass kind or kinds, not both"):
        list(root.descendants("class_specifier", kinds=wanted))


def test_rendering_returns_the_source_every_time() -> None:
    """验证多次渲染都返回原样源码（渲染结果在快照中只计算一次）。
    Verify that rendering returns the exact source every time (the snapshot renders once).
    """
    tree = CppDocument.parse(SOURCE).tree
    assert tree.render() == SOURCE
    assert tree.render() is tree.render()
    assert tree.render_bytes() == SOURCE.encode("utf-8")
