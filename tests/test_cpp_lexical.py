"""验证公共 C++ 词法 token 的位置、分类和 delimiter 配对。
Test public C++ lexical-token positions, categories, and delimiter matching.
"""

from __future__ import annotations

import pytest

from xr_syntax.cpp import code_tokens, matching_delimiter


def test_code_tokens_keep_character_and_byte_offsets_distinct() -> None:
    source = "/* 中文 */ value + 1"
    tokens = code_tokens(source)
    value = next(item for item in tokens if item.text == "value")
    assert source[value.start : value.end] == "value"
    assert source.encode("utf-8")[value.span.start : value.span.end] == b"value"
    assert value.start != value.span.start


def test_code_tokens_ignore_comments_and_preprocessor_logical_lines() -> None:
    source = "#define USE(x) x \\\n  hidden\n// ignored\nvisible + true"
    tokens = code_tokens(source)
    assert [item.text for item in tokens] == ["visible", "+", "true"]
    assert [item.kind for item in tokens] == ["identifier", "punct", "identifier"]


def test_code_token_literal_and_number_categories() -> None:
    tokens = code_tokens('f("x", R"tag(a,b)tag", 1.0f)')
    assert [(item.text, item.kind) for item in tokens] == [
        ("f", "identifier"),
        ("(", "punct"),
        ('"x"', "literal"),
        (",", "punct"),
        ('R"tag(a,b)tag"', "literal"),
        (",", "punct"),
        ("1.0f", "number"),
        (")", "punct"),
    ]


def test_matching_delimiter_handles_nested_templates_and_shift_token() -> None:
    tokens = code_tokens("std::vector<std::pair<int, float>> value")
    opening = next(index for index, item in enumerate(tokens) if item.text == "<")
    closing = matching_delimiter(tokens, opening)
    assert tokens[closing].text == ">>"
    assert tokens[closing + 1].text == "value"


def test_matching_delimiter_does_not_treat_comparison_as_nested_angle() -> None:
    tokens = code_tokens("(a < b)")
    assert matching_delimiter(tokens, 0) == len(tokens) - 1


def test_matching_delimiter_reports_invalid_or_unclosed_input() -> None:
    tokens = code_tokens("f(a")
    with pytest.raises(ValueError, match="^expected an opening delimiter$"):
        matching_delimiter(tokens, 0)
    with pytest.raises(ValueError, match="^unclosed delimiter at offset 1$"):
        matching_delimiter(tokens, 1)
