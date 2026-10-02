"""测试 red 语法树的遍历：深度优先顺序以及按 kind 过滤。
Tests of walking the red syntax tree: depth-first order and filtering by kind.
"""

from __future__ import annotations

import pytest

from xr_syntax.core import SyntaxElement
from xr_syntax.cpp import CppDocument

SOURCE = """#if defined(USE_A)
class A { public: A(int x) {} };
#endif
namespace n { struct B { int y = 1; }; }
"""
WANTED = frozenset({"class_specifier", "struct_specifier", "preproc_if"})


def _key(element: SyntaxElement) -> tuple[str, int, int]:
    """比较元素用的 kind 和位置。
    The kind and position an element is compared by.
    """
    return (element.kind, element.span.start, element.span.end)


def test_filtering_by_kinds_equals_filtering_the_whole_walk() -> None:
    root = CppDocument.parse(SOURCE).root
    everything = [_key(e) for e in root.descendants() if e.kind in WANTED]
    assert [_key(e) for e in root.descendants(kinds=WANTED)] == everything
    assert [e.kind for e in root.descendants(kinds=WANTED)] == [
        "preproc_if",
        "class_specifier",
        "struct_specifier",
    ]
    assert [_key(e) for e in root.descendants("class_specifier")] == [everything[1]]


def test_kind_and_kinds_together_are_refused() -> None:
    root = CppDocument.parse(SOURCE).root
    with pytest.raises(ValueError, match="^pass kind or kinds, not both$"):
        list(root.descendants("class_specifier", kinds=WANTED))
