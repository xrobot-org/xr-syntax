"""测试宏式调用查询、源码列表切分和标识符出现位置。
Tests of macro-style invocation queries, source-list splitting and identifier occurrences.
"""

from __future__ import annotations

import pytest

from xr_syntax.cpp import CppDocument, identifier_occurrences, split_source_list


def test_invocations_keep_template_commas_and_skip_comments_and_directives() -> None:
    source = (
        "#define XR_REGISTER(name, ...) something(name, __VA_ARGS__)\n"
        "// XR_REGISTER(fake, Wrong)\n"
        "XR_REGISTER(array, std::array<int, 2>);\n"
        "XR_REGISTER(ref, Type&);\n"
    )
    invocations = CppDocument.parse(source).invocation_views("XR_REGISTER", template_angles=True)
    assert [(item.arguments, item.line, item.text) for item in invocations] == [
        (("array", "std::array<int, 2>"), 3, "XR_REGISTER(array, std::array<int, 2>)"),
        (("ref", "Type&"), 4, "XR_REGISTER(ref, Type&)"),
    ]


def test_angles_inside_parentheses_do_not_nest_a_source_list() -> None:
    assert split_source_list("A<(1 > 2), int>, x", template_angles=True) == (
        "A<(1 > 2), int>",
        "x",
    )


def test_a_source_list_with_an_unclosed_template_is_refused() -> None:
    with pytest.raises(ValueError, match="^unbalanced C\\+\\+ source list$"):
        split_source_list("a, std::array<int, 2", template_angles=True)


def test_identifier_occurrences_skip_literals_comments_and_directives() -> None:
    source = (
        "#define USE(x) x \\\n  dev\n"
        'f(dev, obj.dev, ptr->dev, ns::dev, dev::constant, "dev"); // dev\n'
    )
    items = [item for item in identifier_occurrences(source) if item.text == "dev"]
    assert [(item.previous, item.following) for item in items] == [
        ("(", ","),
        (".", ","),
        ("->", ","),
        ("::", ","),
        (",", "::"),
    ]
