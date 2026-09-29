"""验证公共 C++ 词法 token 的位置、分类和 delimiter 配对。
Test public C++ lexical-token positions, categories, and delimiter matching.
"""

from __future__ import annotations

import pytest

from xr_syntax.cpp import code_tokens, matching_delimiter


def test_code_tokens_keep_character_and_byte_offsets_distinct() -> None:
    """验证 Unicode 前缀后的字符位置和字节位置都准确。
    Verify character and byte offsets after a Unicode prefix.
    """
    source = "/* 中文 */ value + 1"
    tokens = code_tokens(source)
    value = next(item for item in tokens if item.text == "value")
    assert source[value.start : value.end] == "value"
    assert source.encode("utf-8")[value.span.start : value.span.end] == b"value"
    assert value.start != value.span.start


def test_code_tokens_ignore_comments_and_preprocessor_logical_lines() -> None:
    """验证注释和带续行的预处理指令不会进入 code token。
    Verify comments and continued preprocessor directives do not enter code tokens.
    """
    source = "#define USE(x) x \\\n  hidden\n// ignored\nvisible + true"
    tokens = code_tokens(source)
    assert [item.text for item in tokens] == ["visible", "+", "true"]
    assert [item.kind for item in tokens] == ["identifier", "punct", "identifier"]


def test_code_token_literal_and_number_categories() -> None:
    """验证 literal/number 分类保持稳定。
    Verify stable literal and number categories.
    """
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
    """验证嵌套模板的 >> token 能同时关闭两层角括号。
    Verify that a >> token can close two nested template-angle levels.
    """
    tokens = code_tokens("std::vector<std::pair<int, float>> value")
    opening = next(index for index, item in enumerate(tokens) if item.text == "<")
    closing = matching_delimiter(tokens, opening)
    assert tokens[closing].text == ">>"
    assert tokens[closing + 1].text == "value"


def test_matching_delimiter_does_not_treat_comparison_as_nested_angle() -> None:
    """验证圆括号内的小于比较不会被当成模板角括号。
    Verify that a less-than comparison inside parentheses is not treated as template nesting.
    """
    tokens = code_tokens("(a < b)")
    assert matching_delimiter(tokens, 0) == len(tokens) - 1


def test_matching_delimiter_reports_invalid_or_unclosed_input() -> None:
    """验证无效 opening 和未闭合 delimiter 会报错。
    Verify errors for invalid openings and unclosed delimiters.
    """
    tokens = code_tokens("f(a")
    with pytest.raises(ValueError, match="Expected opening"):
        matching_delimiter(tokens, 0)
    with pytest.raises(ValueError, match="Unclosed delimiter"):
        matching_delimiter(tokens, 1)
