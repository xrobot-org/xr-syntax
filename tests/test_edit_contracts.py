"""验证底层编辑与片段契约：语言归属、跨快照拼接、诊断可信度和区域归属。
Test the low-level edit and fragment contracts: language provenance, cross-snapshot splicing,
diagnostic trust and region ownership.
"""

from __future__ import annotations

import pytest

from xr_syntax.core import GreenToken, SyntaxFragment
from xr_syntax.cpp import CppDocument


def test_a_same_language_fragment_can_replace_an_element() -> None:
    document = CppDocument.parse("int a;\n")
    fragment = SyntaxFragment("cpp", GreenToken("raw", "int b;", named=True))
    changed = document.tree.replace(document.root.children[0], fragment)
    assert changed.render() == "int b;\n"


def test_a_bare_green_element_is_refused() -> None:
    document = CppDocument.parse("int a;\n")
    with pytest.raises(TypeError, match="SyntaxFragment"):
        document.tree.replace(document.root.children[0], GreenToken("raw", "x", named=True))  # type: ignore[arg-type]


def test_a_fragment_of_another_language_is_refused() -> None:
    document = CppDocument.parse("int a;\n")
    fragment = SyntaxFragment("cmake", GreenToken("raw", "set(X 1)", named=True))
    with pytest.raises(ValueError, match="fragment language"):
        document.tree.replace(document.root.children[0], fragment)


def test_a_same_language_element_of_another_snapshot_is_allowed() -> None:
    # green 元素不带位置，跨快照拼接是安全的；只有跨语言才拒绝。
    # Green elements carry no position, so splicing them across snapshots is safe; only a different
    # language is refused.
    first = CppDocument.parse("int a;\n")
    second = CppDocument.parse("int c;\n")
    changed = first.tree.replace(first.root.children[0], second.root.children[0])
    assert changed.render() == "int c;\n"


def test_an_element_of_another_snapshot_cannot_be_edited_directly() -> None:
    first = CppDocument.parse("int a;\n")
    second = CppDocument.parse("int a;\n")
    fragment = SyntaxFragment("cpp", GreenToken("raw", "int b;", named=True))
    with pytest.raises(ValueError, match="different immutable syntax snapshot"):
        first.tree.replace(second.root.children[0], fragment)


def test_a_low_level_edit_marks_the_diagnostics_unknown() -> None:
    document = CppDocument.parse("int a;\n")
    assert document.tree.diagnostic_state == "clean"
    fragment = SyntaxFragment("cpp", GreenToken("raw", "int b;", named=True))
    changed = document.tree.replace(document.root.children[0], fragment)
    assert changed.diagnostic_state == "unknown"
    assert changed.diagnostics is None
    # 文档层把"未验证"显示为空元组，同时用诊断状态保留这个区别。
    # The document layer shows "unverified" as an empty tuple and keeps the difference in the
    # diagnostic state of the tree.
    rebuilt = CppDocument(changed, document._parser)  # noqa: SLF001
    assert rebuilt.diagnostics == ()
    assert rebuilt.tree.diagnostic_state == "unknown"


def test_a_diagnosed_snapshot_reports_diagnosed() -> None:
    document = CppDocument.parse("void f( {\n")
    assert document.tree.diagnostic_state == "diagnosed"
    assert document.diagnostics


def test_the_root_can_only_be_replaced_by_a_node() -> None:
    document = CppDocument.parse("int a;\n")
    with pytest.raises(TypeError, match="root"):
        document.tree.replace(document.root, SyntaxFragment("cpp", GreenToken("raw", "", True)))
