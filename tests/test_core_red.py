"""测试 red 语法树：深度优先遍历、按 kind 过滤、字节范围、trivia 和具名子元素。
Tests of the red syntax tree: depth-first walks, filtering by kind, byte spans, trivia and named
children.
"""

from __future__ import annotations

import pytest

from xr_syntax.core import SyntaxElement, SyntaxNode, SyntaxToken
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


def test_spans_count_the_bytes_of_wide_text() -> None:
    root = CppDocument.parse("int é = 1;").root
    tokens = [element for element in root.descendants() if isinstance(element, SyntaxToken)]
    assert [(token.text, token.span.start, token.span.end) for token in tokens] == [
        ("int", 0, 3),
        ("é", 4, 6),
        ("=", 7, 8),
        ("1", 9, 10),
        (";", 10, 11),
    ]


def test_trivia_is_walked_only_on_request() -> None:
    source = "int x = 1; // one\n"
    root = CppDocument.parse(source).root
    assert not any(element.is_trivia for element in root.descendants())
    leaves = [
        element
        for element in root.descendants(include_trivia=True)
        if not isinstance(element, SyntaxNode)
    ]
    assert [element.kind for element in leaves if element.is_trivia] == [
        "whitespace",
        "whitespace",
        "whitespace",
        "whitespace",
        "newline",
    ]
    assert "".join(element.text for element in leaves) == source


def test_named_children_leave_out_punctuation() -> None:
    document = CppDocument.parse("void f(int a, int b);\nint x = y;\n")
    parameters = document.nodes("parameter_list")[0]
    assert [child.kind for child in parameters.syntax_children] == [
        "(",
        "parameter_declaration",
        ",",
        "parameter_declaration",
        ")",
    ]
    assert [child.kind for child in parameters.named_children] == [
        "parameter_declaration",
        "parameter_declaration",
    ]
    declarator = document.nodes("init_declarator")[0]
    assert [child.text for child in declarator.named_syntax_children] == ["x", "y"]
