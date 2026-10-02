"""测试语法树快照的渲染。
Tests of rendering a syntax-tree snapshot.
"""

from __future__ import annotations

from xr_syntax.cpp import CppDocument


def test_rendering_gives_the_source_text_and_bytes() -> None:
    source = "int é = 1; // é\n"
    tree = CppDocument.parse(source).tree
    assert tree.render() == source
    assert tree.render_bytes() == source.encode("utf-8")
