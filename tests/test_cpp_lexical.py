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


@pytest.mark.parametrize(
    ("source", "tokens"),
    [
        pytest.param(
            "#define USE(x) x \\\n  hidden\n// ignored\nvisible + true",
            [("visible", "identifier"), ("+", "punct"), ("true", "identifier")],
            id="continued-directive",
        ),
        pytest.param(
            "int x;\n#define A 1\nint y;",
            [
                ("int", "identifier"),
                ("x", "identifier"),
                (";", "punct"),
                ("int", "identifier"),
                ("y", "identifier"),
                (";", "punct"),
            ],
            id="code-before-a-directive",
        ),
    ],
)
def test_code_tokens_ignore_comments_and_preprocessor_logical_lines(
    source: str, tokens: list[tuple[str, str]]
) -> None:
    assert [(item.text, item.kind) for item in code_tokens(source)] == tokens


def test_code_token_literal_and_number_categories() -> None:
    tokens = code_tokens('f("x", R"tag(a,b)tag", 1.0f, u8"y", L\'z\', .5)')
    assert [(item.text, item.kind) for item in tokens] == [
        ("f", "identifier"),
        ("(", "punct"),
        ('"x"', "literal"),
        (",", "punct"),
        ('R"tag(a,b)tag"', "literal"),
        (",", "punct"),
        ("1.0f", "number"),
        (",", "punct"),
        ('u8"y"', "literal"),
        (",", "punct"),
        ("L'z'", "literal"),
        (",", "punct"),
        (".5", "number"),
        (")", "punct"),
    ]


@pytest.mark.parametrize(
    ("source", "closing"),
    [
        pytest.param("std::vector<std::pair<int, float>> value", 11, id="shift-closes-two"),
        pytest.param("A<B<int>, C> x", 8, id="nested"),
        pytest.param("A<B<C<int>> > x", 8, id="shift-inside"),
        pytest.param("((a)) b", 4, id="nested-parentheses"),
        pytest.param("(a < b) c", 4, id="comparison-in-parentheses"),
    ],
)
def test_matching_delimiter_handles_nesting_and_the_shift_token(source: str, closing: int) -> None:
    tokens = code_tokens(source)
    opening = next(index for index, item in enumerate(tokens) if item.text in "(<")
    assert matching_delimiter(tokens, opening) == closing


def test_matching_delimiter_reports_invalid_or_unclosed_input() -> None:
    tokens = code_tokens("f(a")
    with pytest.raises(ValueError, match="^expected an opening delimiter$"):
        matching_delimiter(tokens, 0)
    with pytest.raises(ValueError, match="^unclosed delimiter at offset 1$"):
        matching_delimiter(tokens, 1)


def test_an_unclosed_quote_ends_with_its_line() -> None:
    # #error 和 #if 0 中的文字不是代码，撇号常常不成对。
    # The text of #error and #if 0 is not code, and its apostrophes are often unpaired.
    source = "#error Don't build this\n#if 0\nthis isn't compiled\n#endif\nint y;\n"
    assert [(item.text, item.kind) for item in code_tokens(source)] == [
        ("this", "identifier"),
        ("isn", "identifier"),
        ("'t compiled", "literal"),
        ("int", "identifier"),
        ("y", "identifier"),
        (";", "punct"),
    ]


@pytest.mark.parametrize(
    ("source", "texts"),
    [
        ("std::vector<::Foo> v;", ["std", "::", "vector", "<", "::", "Foo", ">", "v", ";"]),
        ("int a<:3:>;", ["int", "a", "<:", "3", ":>", ";"]),
        ("a<:::b", ["a", "<:", "::", "b"]),
        ("a<::>b", ["a", "<:", ":>", "b"]),
    ],
)
def test_the_digraph_rule_for_less_colon_colon(source: str, texts: list[str]) -> None:
    assert [item.text for item in code_tokens(source)] == texts


@pytest.mark.parametrize(
    ("source", "literals"),
    [
        pytest.param(
            'auto a = R"x(say "hi" // not a comment)x"; auto b = R"(/* " */)"; int c;',
            ['R"x(say "hi" // not a comment)x"', 'R"(/* " */)"'],
            id="quotes-and-comment-markers",
        ),
        pytest.param('auto e = R"()"; int c;', ['R"()"'], id="empty"),
        # 拆开 >> 之后，原始字符串的下标随之后移。
        # After a >> is split, the index of the raw string moves along.
        pytest.param(
            'template <typename T = A<int>> struct S {}; auto s = R"(x)"; int c;',
            ['R"(x)"'],
            id="after-a-split-closer",
        ),
    ],
)
def test_raw_strings_are_whole_literals(source: str, literals: list[str]) -> None:
    tokens = code_tokens(source)
    assert [item.text for item in tokens if item.kind == "literal"] == literals
    assert [item.text for item in tokens[-3:]] == ["int", "c", ";"]
