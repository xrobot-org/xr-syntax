"""验证 C++ 常用结构查询和 User Code 区域识别。
Test common C++ structure queries and User Code region detection.
"""

import pytest

from xr_syntax.cpp import CppDocument

SOURCE = """
#include "foo.hpp"

class Device {
 public:
  Device(int value);
};

extern "C" void app_main(void) {
  static Device device(1);
  XR_REGISTER(device, Base);
  /* User Code Begin 3 */
  XROBOT_MAIN();
  /* User Code End 3 */
}
""".lstrip()


def test_common_queries() -> None:
    """验证 CppDocument 的常用函数、调用和声明查询。
    Verify the common CppDocument queries for functions, calls, and declarations.
    """
    document = CppDocument.parse(SOURCE)
    assert len(document.include_views()) == 1
    assert len(document.class_views("Device")) == 1


def test_user_region() -> None:
    """验证 User Code 区域的名称、body 和边界识别。
    Verify User Code region names, bodies, and boundary detection.
    """
    document = CppDocument.parse(SOURCE)
    regions = document.user_regions()
    assert len(regions) == 1
    assert regions[0].name == "3"
    assert "XROBOT_MAIN();" in regions[0].body_text


def test_lexical_invocation_views_support_macro_type_lists() -> None:
    """验证宏式 invocation 能保留模板类型中的逗号并忽略注释/预处理定义。
    Verify lexical invocation queries preserve template commas and ignore comments/directives.
    """
    source = (
        "#define XR_REGISTER(name, ...) something(name, __VA_ARGS__)\n"
        "// XR_REGISTER(fake, Wrong)\n"
        "XR_REGISTER(array, std::array<int, 2>);\n"
        "XR_REGISTER(ref, Type&);\n"
    )
    document = CppDocument.parse(source)
    invocations = document.invocation_views("XR_REGISTER", template_angles=True)
    assert [(item.arguments, item.line) for item in invocations] == [
        (("array", "std::array<int, 2>"), 3),
        (("ref", "Type&"), 4),
    ]


def test_source_list_reports_unbalanced_nesting() -> None:
    """验证公开源码列表切分会拒绝未闭合的嵌套结构。
    Verify that public source-list splitting rejects unclosed nesting.
    """
    from xr_syntax.cpp import split_source_list

    with pytest.raises(ValueError, match="unbalanced"):
        split_source_list("a, std::array<int, 2", template_angles=True)


def test_identifier_occurrences_ignore_literals_comments_and_directives() -> None:
    """验证 identifier occurrence 只返回实际代码中的标识符。
    Verify that identifier occurrences ignore literals, comments, and directives.
    """
    from xr_syntax.cpp import identifier_occurrences

    source = (
        "#define USE(x) x \\\n  dev\n"
        'f(dev, obj.dev, ptr->dev, ns::dev, dev::constant, "dev"); // dev\n'
    )
    items = [item for item in identifier_occurrences(source) if item.text == "dev"]
    assert len(items) == 5
    assert [(item.qualified_left, item.scope_root) for item in items] == [
        (False, False),
        (True, False),
        (True, False),
        (True, False),
        (False, True),
    ]


def test_multiline_preprocessor_define_does_not_swallow_following_class() -> None:
    """验证反斜杠续行的宏定义不会吞掉后续 class。
    Verify that continued macro definitions do not consume a following class declaration.
    """
    source = (
        "#define VALUE \\\n"
        "  0x1D // continued macro body\n"
        "#define OTHER \\\n"
        "  0x40\n"
        "class Sensor {\n"
        " public:\n"
        "  Sensor(int value) {}\n"
        "};\n"
    )
    document = CppDocument.parse(source)

    assert document.render() == source
    assert not document.diagnostics
    assert len(document.class_views("Sensor")) == 1
    assert len(document.class_views("Sensor")[0].constructors(public_only=True)) == 1
