"""值、声明、调用、宏、注释和 include 的排版（xr_syntax.format）。
Layout of values, declarations, calls, macros, comments and includes (xr_syntax.format).

期望的文本与固定版本的 clang-format 对 LibXR 风格的输出相同；两个生成器的 clang-format 测试对
真实生成结果逐一核对这一点。
The expected text is what the pinned clang-format gives in LibXR's style; the clang-format tests of
the two generators check that on real generated output.
"""

from __future__ import annotations

import pytest

from xr_syntax.format import (
    layout_call,
    layout_declaration,
    layout_macro,
    layout_value,
    sort_includes,
    wrap_comment,
)

# parse_node 与 flat 是值排版的内部结构，只由本测试直接检查，不出现在包的公开接口里。
# parse_node and flat are the internal structure of the value layout; only this test looks at them
# directly, and they are not part of the package's public surface.
from xr_syntax.format.layout import flat, parse_node

# 值排版测试里声明部分的固定前缀。
# The fixed declaration prefix of the value layout tests.
HEAD = "  static const T x = "


def lay(text: str) -> list[str]:
    """HEAD 之后的一个值的排版结果。
    The layout of a value after HEAD.
    """
    return layout_value(HEAD, text, ";", 2)


def test_brace_lists_calls_and_designated_entries_are_split() -> None:
    node = parse_node('{.a = 1, .b = {2, "x, y"}, .c = Foo<int, 2>(4, {5})}')
    assert node.kind == "brace"
    assert [(i.kind, i.text) for i in node.items] == [
        ("designated", "a"),
        ("designated", "b"),
        ("designated", "c"),
    ]
    assert node.items[1].items[0].kind == "brace"
    assert node.items[2].items[0].kind == "call"
    assert node.items[2].items[0].text == "Foo<int, 2>"
    assert flat(node) == '{.a = 1, .b = {2, "x, y"}, .c = Foo<int, 2>(4, {5})}'


def test_typed_braces_keep_their_type() -> None:
    node = parse_node("std::array<int, 2>{1,  2}")
    assert (node.kind, node.text) == ("brace", "std::array<int, 2>")
    assert flat(node) == "std::array<int, 2>{1, 2}"


@pytest.mark.parametrize(
    "text", ["a + f(x)", "cond ? {1} : {2}", "values[0]", "(a + b) * c", "-f(1)", "x"]
)
def test_anything_else_is_text_as_written(text: str) -> None:
    node = parse_node(text)
    assert (node.kind, node.text) == ("text", text)


def test_a_value_that_fits_stays_on_one_line() -> None:
    assert lay("{1, 2}") == ["  static const T x = {1, 2};"]
    assert lay("Param{1, 2}") == ["  static const T x = Param{1, 2};"]


def test_an_outermost_struct_has_one_field_per_line_even_when_it_fits() -> None:
    assert lay("{.a = 1, .b = {.c = 2}}") == [
        "  static const T x = {",
        "      .a = 1,",
        "      .b = {.c = 2},",
        "  };",
    ]
    assert lay("{}") == ["  static const T x = {};"]


def test_a_nested_struct_that_does_not_fit_breaks_after_its_field_name() -> None:
    text = (
        '{.name = "n", .inner = {.first_long_field = 1000000, '
        ".second_long_field = 2000000, .third_long_field = 3}}"
    )
    assert lay(text) == [
        "  static const T x = {",
        '      .name = "n",',
        "      .inner =",
        "          {",
        "              .first_long_field = 1000000,",
        "              .second_long_field = 2000000,",
        "              .third_long_field = 3,",
        "          },",
        "  };",
    ]


def test_a_list_of_five_or_more_fills_columns() -> None:
    text = "{" + ", ".join(f'"name_{i}"' for i in range(12)) + "}"
    assert lay(text) == [
        "  static const T x = {",
        '      "name_0", "name_1", "name_2", "name_3", "name_4",  "name_5",',
        '      "name_6", "name_7", "name_8", "name_9", "name_10", "name_11",',
        "  };",
    ]


def test_a_list_of_fewer_items_has_one_per_line() -> None:
    text = "{" + ", ".join(f"Some::Long::Qualified::Name{i}" for i in range(4)) + "}"
    lines = lay(text)
    assert len(lines) == 6
    assert lines[1] == "      Some::Long::Qualified::Name0,"


def test_a_call_fills_lines_aligned_after_its_parenthesis() -> None:
    text = "Type(" + ", ".join(f"argument_number_{i}" for i in range(8)) + ")"
    assert lay(text) == [
        "  static const T x = Type(argument_number_0, argument_number_1, argument_number_2,",
        "                          argument_number_3, argument_number_4, argument_number_5,",
        "                          argument_number_6, argument_number_7);",
    ]


def test_text_that_cannot_be_split_overflows_instead_of_breaking() -> None:
    long_text = "a_very_long_name_" * 8
    assert lay(long_text) == [f"{HEAD}{long_text};"]


def test_a_long_name_goes_to_the_next_line_after_the_type() -> None:
    assert layout_declaration(
        "static const std::initializer_list<SharedTopic::TopicConfig>",
        "xr_shared_topic_topic_configs",
        '{"a", "b"}',
        ";",
        2,
    ) == [
        "  static const std::initializer_list<SharedTopic::TopicConfig>",
        '      xr_shared_topic_topic_configs = {"a", "b"};',
    ]


def test_a_brace_that_does_not_fit_after_the_name_starts_its_own_line() -> None:
    items = ", ".join(f"Entry::kValue{i}" for i in range(7))
    assert layout_declaration(
        "static const std::initializer_list<EventBinder::ModuleInfo>",
        "xr_jftjjislhhdxmel_ltqslbq",
        "{" + items + "}",
        ";",
        2,
    ) == [
        "  static const std::initializer_list<EventBinder::ModuleInfo> "
        "xr_jftjjislhhdxmel_ltqslbq =",
        "      {",
        "          Entry::kValue0, Entry::kValue1, Entry::kValue2, Entry::kValue3,",
        "          Entry::kValue4, Entry::kValue5, Entry::kValue6,",
        "      };",
    ]


def test_call_arguments_that_fit_share_one_line() -> None:
    assert layout_call("static CMD cmd(", ['"a"', "b"], ");", 2) == ['  static CMD cmd("a", b);']


def test_a_call_aligns_after_the_parenthesis() -> None:
    args = [f"motor_{i}" for i in range(9)]
    assert layout_call("static Chassis<Mecanum> chassis(", args, ");", 2) == [
        "  static Chassis<Mecanum> chassis(motor_0, motor_1, motor_2, motor_3, motor_4, motor_5,",
        "                                  motor_6, motor_7, motor_8);",
    ]


def test_a_call_breaks_after_the_parenthesis_when_that_saves_a_line() -> None:
    args = [f"argument_{i:02d}" for i in range(14)]
    lines = layout_call("static Something_long_name instance_with_long_name(", args, ");", 2)
    assert lines[0] == "  static Something_long_name instance_with_long_name("
    assert lines[1][:10] == "      argu"
    assert all(len(line) <= 90 for line in lines)


def test_a_function_declaration_is_more_reluctant_to_break_after_the_parenthesis() -> None:
    params = [f"LibXR::GPIO& gpio_{i}" for i in range(6)]
    head = "[[noreturn]] static inline void XRobotMain("
    aligned = layout_call(head, params, ")", 0, hang_margin=3)
    assert len(aligned) == 3
    assert aligned[1].startswith(" " * 43 + "LibXR::GPIO& gpio_2")
    many = [f"LibXR::GPIO& gpio_{i}" for i in range(30)]
    hanging = layout_call(head, many, ")", 0, hang_margin=3)
    assert hanging[0] == head
    assert hanging[1].startswith("    LibXR::GPIO& gpio_0, ")


def test_a_short_macro_is_one_line_and_a_long_one_aligns_its_continuations() -> None:
    assert layout_macro("XROBOT_MAIN", "::XRobotMain", ["a", "b"]) == [
        "#define XROBOT_MAIN() ::XRobotMain(a, b)"
    ]
    lines = layout_macro("XROBOT_MAIN", "::XRobotMain", [f"gpio_{i}" for i in range(14)])
    assert lines == [
        "#define XROBOT_MAIN()" + " " * 66 + "\\",
        "  ::XRobotMain(gpio_0, gpio_1, gpio_2, gpio_3, gpio_4, gpio_5, gpio_6, gpio_7, gpio_8, \\",
        "               gpio_9, gpio_10, gpio_11, gpio_12, gpio_13)",
    ]


def test_a_long_comment_is_broken_at_spaces() -> None:
    text = (
        "Generated by `xrobot gen` from User/products/a_rather_long_product_name_xxxx.yaml; "
        "do not edit by hand."
    )
    assert wrap_comment(text) == [
        "// Generated by `xrobot gen` from User/products/a_rather_long_product_name_xxxx.yaml; do",
        "// not edit by hand.",
    ]
    assert wrap_comment("short", 2) == ["  // short"]


def test_includes_are_grouped_and_sorted_like_clang_format_regroups_them() -> None:
    assert sort_includes(
        ['"libxr.hpp"', "<vector>", '"Led.hpp"', "<stdint.h>", '"sub/Pins.h"', '"Led.hpp"']
        + ["<array>"]
    ) == [
        "#include <stdint.h>",
        "",
        "#include <array>",
        "#include <vector>",
        "",
        '#include "Led.hpp"',
        '#include "libxr.hpp"',
        '#include "sub/Pins.h"',
    ]
