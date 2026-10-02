"""测试 C++ 视图：类名、构造函数及其参数、模板参数和 include。
Tests of the C++ views: class names, constructors and their parameters, template parameters
and includes.
"""

from __future__ import annotations

from xr_syntax.cpp import CppDocument


def _constructors(source: str, name: str, **options: bool) -> list[list[str]]:
    """类 name 的构造函数，每个构造函数给出各参数的源码文字。
    The constructors of class name, each as the source text of its parameters.
    """
    view = CppDocument.parse(source).class_views(name)[0]
    return [
        [parameter.text.strip() for parameter in constructor.parameters]
        for constructor in view.constructors(**options)
    ]


def test_a_constructor_gives_parameter_names_types_and_defaults() -> None:
    source = (
        "class Example {\n"
        " public:\n"
        "  Example(Device& device, int period = 20) : device_(&device) {}\n"
        "  void Run(int value) { Use(value); }\n"
        "\n"
        " private:\n"
        "  Device* device_;\n"
        "};\n"
    )
    constructors = CppDocument.parse(source).class_views("Example")[0].constructors()
    assert [constructor.name for constructor in constructors] == ["Example"]
    assert [
        (parameter.name, parameter.type, parameter.default)
        for parameter in constructors[0].parameters
    ] == [("device", "Device&", None), ("period", "int", "20")]


def test_declarator_types_are_spelled_without_the_name() -> None:
    source = "class F { public: F(int (*cb)(double), int (&arr)[3], const X* p = nullptr) {} };"
    parameters = CppDocument.parse(source).class_views("F")[0].constructors()[0].parameters
    assert [(parameter.name, parameter.type) for parameter in parameters] == [
        ("cb", "int (*)(double)"),
        ("arr", "int (&)[3]"),
        ("p", "const X*"),
    ]


def test_template_parameters_give_names_types_and_defaults() -> None:
    source = "template <typename T, typename U = std::array<int, 2>, int N = 3, Foo V> class C {};"
    parameters = CppDocument.parse(source).class_views("C")[0].template_parameters
    assert [(item.name, item.type, item.default) for item in parameters] == [
        ("T", "typename", None),
        ("U", "typename", "std::array<int, 2>"),
        ("N", "int", "3"),
        ("V", "Foo", None),
    ]


def test_deleted_constructors_are_not_callable() -> None:
    source = (
        "class C { public: C(int); C(const C&) = delete; "
        "C& operator=(const C&) = delete; ~C() = default; };"
    )
    assert _constructors(source, "C", public_only=True) == [["int"], ["const C&"]]
    assert _constructors(source, "C", public_only=True, callable_only=True) == [["int"]]


def test_member_functions_give_access_and_deleted_or_defaulted() -> None:
    source = (
        "class C { public: C(int); C& operator=(const C&) = delete; ~C() = default;\n"
        " private: void Run(); };"
    )
    functions = CppDocument.parse(source).class_views("C")[0].functions()
    assert [(item.name, item.access, item.deleted, item.defaulted) for item in functions] == [
        ("C", "public", False, False),
        ("operator=", "public", True, False),
        ("~C", "public", False, True),
        ("Run", "private", False, False),
    ]


def test_constructor_declarations_with_defaults_are_not_calls() -> None:
    source = "class Foo { public: Foo(int count = 10); Foo(float gain = 1.0f); };"
    assert _constructors(source, "Foo", public_only=True) == [
        ["int count = 10"],
        ["float gain = 1.0f"],
    ]
    assert CppDocument.parse(source).nodes("call_expression") == ()


def test_parameter_types_keep_template_argument_commas() -> None:
    source = (
        "class Led { public: Led(std::pair<int, float> p, A<B<int, int>, C> x, "
        "int y = f(1, 2)) {} };"
    )
    assert _constructors(source, "Led") == [
        ["std::pair<int, float> p", "A<B<int, int>, C> x", "int y = f(1, 2)"]
    ]


def test_attributes_before_the_class_name_are_not_the_name() -> None:
    source = (
        "struct [[gnu::packed]] Packed { int a; };\n"
        "struct alignas(alignof(double)) Aligned { int a; };\n"
        "struct __attribute__((packed)) GnuPacked { int a; };\n"
        "class [[nodiscard]] Final final : public Base {};\n"
        "struct { int a; } anonymous;\n"
    )
    names = [view.name for view in CppDocument.parse(source).class_views()]
    assert names == ["Packed", "Aligned", "GnuPacked", "Final", None]


def test_a_class_keyword_that_starts_no_definition_is_no_class() -> None:
    source = (
        "class Forward;\n"
        "class Forward* pointer = nullptr;\n"
        "struct stat info;\n"
        "struct Result make() { return {}; }\n"
        "class EXPORT_API Led final : public Base<(1)> { public: Led(int a) {} };\n"
    )
    views = CppDocument.parse(source).class_views()
    assert [(view.node.kind, view.name) for view in views] == [("class_specifier", "Led")]
    assert _constructors(source, "Led") == [["int a"]]


def test_an_out_of_line_nested_class_keeps_its_qualified_name() -> None:
    document = CppDocument.parse("class Outer { class Inner; };\nclass Outer::Inner { int a; };\n")
    assert [view.name for view in document.class_views()] == ["Outer", "Outer::Inner"]
    assert [view.name for view in document.class_views("Outer")] == ["Outer"]


def test_include_views_give_the_header_and_its_form() -> None:
    includes = CppDocument.parse('#include "local.hpp"\n#include <vector>\n').include_views()
    assert [(item.header, item.system) for item in includes] == [
        ("local.hpp", False),
        ("vector", True),
    ]
