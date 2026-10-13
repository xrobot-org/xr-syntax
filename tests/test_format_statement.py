"""语句排版（xr_syntax.format.layout_statement）：与 clang-format 在 LibXR 的风格下断行相同。
Statement layout (xr_syntax.format.layout_statement): the same line breaks as clang-format makes in
the LibXR style.
"""

from __future__ import annotations

import random

import pytest
from format_fixtures import clang_format, requires_clang_format

from xr_syntax.format import Braces, layout_statement


def format_lines(statements: list[str]) -> list[list[str]]:
    """clang-format 对每条语句的排版：各行，缩进 2 列。
    The layout clang-format gives each statement: its lines, indented by 2 columns.

    每条语句放进自己的函数，两侧各有一条语句，使函数体不会被合并成一行。
    Each statement goes into a function of its own with a statement on either side, so that the body
    is not merged into one line.
    """
    source = "".join(
        f"void f{number}()\n{{\n  int before = 0;\n  {statement}\n  int after = 0;\n}}\n"
        for number, statement in enumerate(statements)
    )
    formatted = clang_format(source, "layout.cpp")
    results = []
    for chunk in formatted.split("void f")[1:]:
        results.append(chunk.rstrip("\n").split("\n")[3:-2])
    return results


def statement(head: str, args: list) -> str:
    """语句 ``head(args);`` 写在一行里的文本。
    The text of the statement ``head(args);`` written on one line.
    """
    text = ", ".join(arg if isinstance(arg, str) else arg.text() for arg in args)
    return f"{head}({text});"


def test_a_statement_that_fits_stays_on_one_line() -> None:
    assert layout_statement(
        "static STM32SPI spi1", ["&hspi1", "spi1_rx_buf", "spi1_tx_buf", "3"]
    ) == ["  static STM32SPI spi1(&hspi1, spi1_rx_buf, spi1_tx_buf, 3);"]
    assert layout_statement("PlatformInit", []) == ["  PlatformInit();"]


def test_arguments_are_packed_and_aligned_after_the_parenthesis() -> None:
    endpoint = "USB::Endpoint::EPNumber::EP"
    assert layout_statement(
        "static USB::CDCUart usb_otg_fs_cdc",
        [endpoint + "1", endpoint + "1", endpoint + "2", "128", "128", "3"],
    ) == [
        "  static USB::CDCUart usb_otg_fs_cdc(USB::Endpoint::EPNumber::EP1,",
        "                                     USB::Endpoint::EPNumber::EP1,",
        "                                     USB::Endpoint::EPNumber::EP2, 128, 128, 3);",
    ]


def test_a_long_name_breaks_after_the_parenthesis() -> None:
    assert layout_statement(
        "static STM32UART usart_very_long_name_number_one",
        [
            "&huart1",
            "usart_very_long_name_number_one_rx_buf",
            "usart_very_long_name_number_one_tx_buf",
            "5",
        ],
    ) == [
        "  static STM32UART usart_very_long_name_number_one(",
        "      &huart1, usart_very_long_name_number_one_rx_buf,",
        "      usart_very_long_name_number_one_tx_buf, 5);",
    ]


def test_an_assignment_breaks_after_the_parenthesis_or_the_equals_sign() -> None:
    assert layout_statement(
        "static constexpr auto usb_otg_fs_strings = USB::DescriptorStrings::MakeLanguagePack",
        [
            "USB::DescriptorStrings::Language::EN_US",
            '"QDU-Future"',
            '"MainCtrl"',
            '"QDU-Future-MainCtrl-89ABCDEF0123456701234567"',
        ],
    ) == [
        "  static constexpr auto usb_otg_fs_strings = USB::DescriptorStrings::MakeLanguagePack(",
        '      USB::DescriptorStrings::Language::EN_US, "QDU-Future", "MainCtrl",',
        '      "QDU-Future-MainCtrl-89ABCDEF0123456701234567");',
    ]


def test_a_list_of_braced_lists_breaks_at_every_item() -> None:
    entries = [Braces(f"usb_otg_hs_ep{n}_in_buf", "128") for n in range(4)]
    assert layout_statement("x.Create", ["a", Braces(*entries)]) == [
        "  x.Create(a, {{usb_otg_hs_ep0_in_buf, 128},",
        "               {usb_otg_hs_ep1_in_buf, 128},",
        "               {usb_otg_hs_ep2_in_buf, 128},",
        "               {usb_otg_hs_ep3_in_buf, 128}});",
    ]


def test_a_list_with_a_braced_list_among_its_items_breaks_at_every_item() -> None:
    buffers = [f"usb_otg_hs_ep{n}_out_buf" for n in range(4)]
    assert layout_statement(
        "static T x", ["&hpcd", "256", Braces(Braces(buffers[0], "8"), *buffers[1:])]
    ) == [
        "  static T x(&hpcd, 256,",
        "             {{usb_otg_hs_ep0_out_buf, 8},",
        "              usb_otg_hs_ep1_out_buf,",
        "              usb_otg_hs_ep2_out_buf,",
        "              usb_otg_hs_ep3_out_buf});",
    ]


def test_a_list_that_spans_lines_starts_a_line_after_two_arguments() -> None:
    entries = [Braces(f"usb_otg_hs_ep{n}_in_buf", "128") for n in range(4)]
    assert layout_statement("x.Create", ["a", "b", Braces(*entries)]) == [
        "  x.Create(a, b,",
        "           {{usb_otg_hs_ep0_in_buf, 128},",
        "            {usb_otg_hs_ep1_in_buf, 128},",
        "            {usb_otg_hs_ep2_in_buf, 128},",
        "            {usb_otg_hs_ep3_in_buf, 128}});",
    ]


def test_the_argument_after_a_list_that_spans_lines_starts_a_line() -> None:
    channels = Braces(*[f"ADC_CHANNEL_{n}" for n in range(6)])
    assert layout_statement("static STM32ADC adc3", ["&hadc3", "adc3_buf", channels, "3.3"]) == [
        "  static STM32ADC adc3(&hadc3, adc3_buf,",
        "                       {ADC_CHANNEL_0, ADC_CHANNEL_1, ADC_CHANNEL_2, ADC_CHANNEL_3,",
        "                        ADC_CHANNEL_4, ADC_CHANNEL_5},",
        "                       3.3);",
    ]


def atom(rng: random.Random, length: int | None = None) -> str:
    """随机的不可拆分参数：标识符、数字、字符串或带 & 的句柄；length 给出时按这个长度。
    A random unbreakable argument: an identifier, a number, a string or a handle with &; of the
    given length when length is set.
    """
    length = length or rng.choice([1, 2, 3, 5, 8, 12, 16, 20, 25, 30, 38, 45])
    kind = rng.random()
    if kind < 0.5:
        prefix = rng.choice(["usart", "buf", "spi", "usb_otg_hs_ep", "ADC_CHANNEL_"])
        return prefix + "x" * length if rng.random() < 0.5 else prefix + str(rng.randint(0, 99))
    if kind < 0.7:
        return str(rng.randint(0, 10 ** rng.randint(1, 6)))
    if kind < 0.8:
        return "&h" + "a" * length
    if kind < 0.9:
        return '"' + "s" * length + '"'
    return "a" * length


def items(rng: random.Random) -> list[str]:
    """花括号列表的随机元素：同一个前缀加序号，如通道列表和缓冲区列表。
    Random items of a braced list: one prefix and a running number, like a list of channels or of
    buffers.
    """
    prefix = rng.choice(["ADC_CHANNEL_", "usb_otg_hs_ep", "buf", "spi_" + "x" * 12])
    return [prefix + str(number) for number in range(rng.randint(1, 8))]


def argument(rng: random.Random) -> str | Braces:
    """随机的参数：不可拆分的文本，或元素为文本、文本列表的花括号列表。
    A random argument: unbreakable text, or a braced list of text or lists of text.
    """
    if rng.random() < 0.35:
        if rng.random() < 0.2:
            return Braces(Braces(atom(rng), str(rng.randint(8, 256))), *items(rng))
        if rng.random() < 0.4:
            return Braces(
                *[Braces(atom(rng), str(rng.randint(8, 256))) for _ in range(rng.randint(1, 6))]
            )
        return Braces(*items(rng))
    return atom(rng)


@requires_clang_format
def test_random_statements_break_where_clang_format_breaks() -> None:
    rng = random.Random(20261003)
    cases = []
    for _ in range(400):
        name = "n" * rng.randint(2, 30)
        head = rng.choice(
            [
                f"static STM32T {name}",
                f"{name}.Create",
                f"static constexpr auto {name} = A::B::Make",
            ]
        )
        # 赋值只用于带文本参数的 MakeLanguagePack，不带列表。
        # An assignment is written only for MakeLanguagePack, whose arguments are text and no
        # lists.
        arguments = [argument(rng) for _ in range(rng.randint(2, 9))]
        if "=" in head:
            arguments = [atom(rng) for _ in arguments]
        cases.append((head, arguments))
    expected = format_lines([statement(head, args) for head, args in cases])
    mismatches = [
        statement(head, args)
        for (head, args), lines in zip(cases, expected, strict=True)
        if layout_statement(head, args) != lines
    ]
    assert mismatches == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
