"""测试 C++ 视图：类名、构造函数及其参数、模板参数和 include。
Tests of the C++ views: class names, constructors and their parameters, template parameters
and includes.
"""

from __future__ import annotations

import pytest

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


def test_member_functions_give_their_access_and_whether_deleted() -> None:
    source = (
        "class C { public: C(int); C& operator=(const C&) = delete; ~C() = default;\n"
        " private: void Run(); };"
    )
    functions = CppDocument.parse(source).class_views("C")[0].functions()
    assert [(item.name, item.access, item.deleted) for item in functions] == [
        ("C", "public", False),
        ("operator=", "public", True),
        ("~C", "public", False),
        ("Run", "private", False),
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


@pytest.mark.parametrize("label", ["public :", "public /* api */:", "public\n  :"])
def test_an_access_label_may_hold_spaces_and_comments(label: str) -> None:
    source = f"class A {{ {label} A(int x); }};"
    assert _constructors(source, "A", public_only=True) == [["int x"]]


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        pytest.param(
            "int a = (1 < 2), int d = 3", ["int a = (1 < 2)", "int d = 3"], id="less-in-parens"
        ),
        pytest.param(
            "A<(1 > 2), int> a, int b", ["A<(1 > 2), int> a", "int b"], id="greater-in-parens"
        ),
        pytest.param("void", [], id="void"),
        pytest.param("int (&arr)[3]", ["int (&arr)[3]"], id="array-reference"),
    ],
)
def test_constructor_parameters_are_split_at_top_level_commas(
    parameters: str, expected: list[str]
) -> None:
    source = f"class B {{ public: B({parameters}); }};"
    assert _constructors(source, "B") == [expected]


def test_parameter_text_has_no_surrounding_whitespace() -> None:
    source = "class C { public: C( int a,  char* b ) {} };"
    constructor = CppDocument.parse(source).class_views("C")[0].constructors()[0]
    assert [parameter.text for parameter in constructor.parameters] == ["int a", "char* b"]


def test_unnamed_parameters_have_no_name_and_the_whole_type() -> None:
    source = "class C { public: C(int, const uint8_t*, unsigned long, Foo&); };"
    constructor = CppDocument.parse(source).class_views("C")[0].constructors()[0]
    assert [(parameter.name, parameter.type) for parameter in constructor.parameters] == [
        (None, "int"),
        (None, "const uint8_t*"),
        (None, "unsigned long"),
        (None, "Foo&"),
    ]


@pytest.mark.parametrize(
    ("source", "defaults"),
    [
        pytest.param(
            "template <typename T = std::array<int, 2>> class X {};",
            ["std::array<int, 2>"],
            id="closing-shift",
        ),
        pytest.param(
            "template <bool B = (1 > 2), typename T = int> class X {};",
            ["(1 > 2)", "int"],
            id="greater-in-parens",
        ),
    ],
)
def test_template_parameter_defaults_end_at_the_list_end(source: str, defaults: list[str]) -> None:
    parameters = CppDocument.parse(source).class_views("X")[0].template_parameters
    assert [item.default for item in parameters] == defaults


@pytest.mark.parametrize(
    "member",
    [
        pytest.param("int x_ = compute(y);", id="initialized-by-call"),
        pytest.param("Foo bar_{make(z)};", id="brace-initialized-by-call"),
        pytest.param("Callback (*callback_)(void*);", id="function-pointer"),
        pytest.param("std::function<void()> handler_;", id="function-in-template-argument"),
    ],
)
def test_data_members_are_not_functions(member: str) -> None:
    source = f"class Cfg {{ public: Cfg(); {member} }};"
    functions = CppDocument.parse(source).class_views("Cfg")[0].functions()
    assert [function.name for function in functions] == ["Cfg"]


def test_operator_and_parenthesized_names_are_function_names() -> None:
    source = (
        "class C { public: bool operator()(int) const; operator const char*() const;\n"
        "  int& operator[](size_t i); bool operator<(const C&) const;\n"
        "  static bool (isinf)(float x) { return false; } };"
    )
    functions = CppDocument.parse(source).class_views("C")[0].functions()
    assert [function.name for function in functions] == [
        "operator()",
        "operator const char*",
        "operator[]",
        "operator<",
        "isinf",
    ]


def test_brace_initializers_do_not_end_an_inline_constructor() -> None:
    source = "class Led { public: Led(Gpio& g) : g_{g}, n_(1) { Run(); } void Run(); Gpio& g_; };"
    functions = CppDocument.parse(source).class_views("Led")[0].functions()
    assert [function.name for function in functions] == ["Led", "Run"]
