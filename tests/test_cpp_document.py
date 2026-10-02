"""测试 C++ 文档：复用解析时的词法结果、User Code 区域及其替换。
Tests of the C++ document: reuse of the lexing of the parse, and User Code regions and their
replacement.
"""

from __future__ import annotations

import pytest

from xr_syntax.core import SourceSpan
from xr_syntax.cpp import CppDocument, CppRegion, code_tokens, identifier_occurrences


def _region_source(newline: str = "\n") -> str:
    """一段带命名 User Code 区域的源码。
    Source with one named User Code region.
    """
    return newline.join(
        (
            "void f() {",
            "  /* User Code Begin body */",
            "  keep_me();",
            "  /* User Code End body */",
            "}",
            "",
        )
    )


@pytest.mark.parametrize("edited", [False, True], ids=["parsed", "edited"])
def test_tokens_and_identifiers_equal_those_of_lexing_the_source_again(edited: bool) -> None:
    source = (
        '#define A 1\nint /* é */ value = f("x");\n/* User Code Begin a */\n/* User Code End a */\n'
    )
    document = CppDocument.parse(source)
    if edited:
        document = document.replace_region_body(document.user_regions()[0], "\nint b;\n")
    assert document.code_tokens() == code_tokens(document.render())
    assert document.identifier_occurrences() == identifier_occurrences(document.render())


@pytest.mark.parametrize("comment", ["/* open", "/*/"])
def test_tokens_of_a_source_with_a_lexical_error_are_refused(comment: str) -> None:
    with pytest.raises(ValueError, match="^unclosed block comment$"):
        CppDocument.parse(f"int x; {comment}").code_tokens()


def test_a_user_region_gives_its_name_and_body() -> None:
    region = CppDocument.parse(_region_source()).user_regions()[0]
    assert (region.kind, region.name, region.body_text) == (
        "user",
        "body",
        "\n  keep_me();\n  ",
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_replacing_a_region_body_keeps_the_markers_and_the_rest(newline: str) -> None:
    source = _region_source(newline)
    document = CppDocument.parse(source)
    body = f"{newline}  generated();{newline}  "
    changed = document.replace_region_body(document.user_regions()[0], body)
    assert changed.render_bytes() == source.replace("keep_me", "generated").encode()
    assert [region.body_text for region in changed.user_regions()] == [body]


def test_writing_back_a_body_keeps_non_utf8_bytes() -> None:
    source = b"/* User Code Begin raw */\n\xff\xfe\n/* User Code End raw */\n"
    document = CppDocument.parse(source)
    region = document.user_regions()[0]
    assert document.replace_region_body(region, region.body_text).render_bytes() == source


@pytest.mark.parametrize("edited", [False, True], ids=["another-parse", "after-an-edit"])
def test_a_region_of_another_snapshot_is_refused(edited: bool) -> None:
    first = CppDocument.parse(_region_source())
    region = first.user_regions()[0]
    second = (
        first.replace_region_body(region, "\n  first();\n  ")
        if edited
        else CppDocument.parse(_region_source())
    )
    with pytest.raises(
        ValueError, match="^region belongs to a different immutable syntax snapshot$"
    ):
        second.replace_region_body(region, "\n  second();\n  ")


def test_a_forged_body_span_is_refused() -> None:
    document = CppDocument.parse(_region_source())
    region = document.user_regions()[0]
    forged = CppRegion(
        region.kind,
        region.name,
        region.begin,
        region.end,
        SourceSpan(region.body_span.start, region.body_span.start),
        "",
    )
    with pytest.raises(ValueError, match="^region body span does not match its begin/end markers$"):
        document.replace_region_body(forged, "replacement")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "/* User Code Begin A */\nfirst();\n/* User Code End B */\n"
            "second();\n/* User Code End A */\n",
            [("A", "\nfirst();\n/* User Code End B */\nsecond();\n")],
            id="mismatched-end-is-text",
        ),
        pytest.param(
            "/* User Code Begin A */\n/* User Code Begin B */\ninner();\n"
            "/* User Code End B */\nouter();\n/* User Code End A */\n",
            [
                ("A", "\n/* User Code Begin B */\ninner();\n/* User Code End B */\nouter();\n"),
                ("B", "\ninner();\n"),
            ],
            id="nested",
        ),
        pytest.param(
            "/* User Code Begin A */\n/* User Code Begin A */\ninner();\n"
            "/* User Code End A */\nouter();\n/* User Code End A */\n",
            [
                ("A", "\n/* User Code Begin A */\ninner();\n/* User Code End A */\nouter();\n"),
                ("A", "\ninner();\n"),
            ],
            id="nested-same-name",
        ),
        pytest.param(
            "/* User Code End orphan */\n/* User Code Begin open */\nwork();\n",
            [],
            id="unmatched",
        ),
    ],
)
def test_region_markers_pair_like_brackets(source: str, expected: list[tuple[str, str]]) -> None:
    regions = CppDocument.parse(source).user_regions()
    assert [(region.name, region.body_text) for region in regions] == expected
