"""验证布局 IR 在可平铺和必须换行两种宽度条件下的行为。
Test layout-IR behavior when groups fit on one line and when they must break.
"""

from xr_syntax.format import Group, Indent, concat, join, line, render, softline


def call_doc(arguments):
    """构造用于布局测试的示例调用文档。
    Build the sample call document used by layout tests.
    """
    return Group(
        concat(
            "foo(",
            Indent(concat(softline, join(concat(",", line), arguments))),
            softline,
            ")",
        )
    )


def test_group_stays_flat_when_it_fits() -> None:
    """验证 group 在剩余行宽足够时保持单行平铺。
    Verify that a group remains flat on one line when the remaining width is sufficient.
    """
    assert render(call_doc(["a", "b"]), width=80) == "foo(a, b)"


def test_group_breaks_when_needed() -> None:
    """验证 group 在行宽不足时按布局规则换行。
    Verify that a group breaks according to layout rules when the line is too narrow.
    """
    assert render(
        call_doc(["long_argument_a", "long_argument_b"]),
        width=20,
    ) == ("foo(\n  long_argument_a,\n  long_argument_b\n)")
