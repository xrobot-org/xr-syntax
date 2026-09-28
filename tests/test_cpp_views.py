"""验证 C++ 类型化视图对类、函数、参数、调用和变量的源码级解释。
Test source-level C++ typed views for classes, functions, parameters, calls, includes, and variables.
"""
from xr_syntax.cpp import CppDocument

SOURCE = """class Example {
 public:
  Example(Device& device, int period = 20) : device_(&device) {}
  void Run(int value) { Use(value); }

 private:
  Device* device_;
};
"""


def test_class_and_function_views() -> None:
    """验证类和函数视图能正确提取名称、参数、访问级别和函数体。
    Verify that class and function views extract names, parameters, access levels, and function bodies correctly.
    """
    document = CppDocument.parse(SOURCE)
    view = document.class_views("Example")[0]
    constructors = view.constructors(public_only=True)
    assert len(constructors) == 1
    assert constructors[0].name == "Example"
    assert [parameter.name for parameter in constructors[0].parameters] == [
        "device",
        "period",
    ]
    assert [parameter.type for parameter in constructors[0].parameters] == [
        "Device&",
        "int",
    ]
    assert constructors[0].parameters[1].default == "20"

    functions = {function.name: function for function in view.functions()}
    assert "Run" in functions
    assert functions["Run"].access == "public"


def test_complex_declarator_type_spelling() -> None:
    """验证复杂 declarator 的源码级类型拼写能够完整重建。
    Verify that source-level type spelling for complex declarators can be reconstructed completely.
    """
    document = CppDocument.parse(
        "void f(int (*cb)(double), int (&arr)[3], const X* p = nullptr) {}"
    )
    parameters = document.function_views("f")[0].parameters
    assert [parameter.name for parameter in parameters] == ["cb", "arr", "p"]
    assert [parameter.type for parameter in parameters] == [
        "int (*)(double)",
        "int (&)[3]",
        "const X*",
    ]
    assert parameters[2].default == "nullptr"


def test_template_parameter_views() -> None:
    """验证模板参数视图的名称、类型和默认值提取。
    Verify extraction of template-parameter names, types, and default values.
    """
    document = CppDocument.parse(
        "template <typename T, int N = 3, Foo V> class C {};"
    )
    parameters = document.class_views("C")[0].template_parameters
    assert [parameter.name for parameter in parameters] == ["T", "N", "V"]
    assert [parameter.type for parameter in parameters] == ["typename", "int", "Foo"]
    assert [parameter.default for parameter in parameters] == [None, "3", None]


def test_deleted_special_members_are_structured_but_not_callable() -> None:
    """验证 = delete 特殊成员仍被结构化，但不会被视为可调用构造函数。
    Verify that = delete special members remain structured but are not treated as callable constructors.
    """
    document = CppDocument.parse(
        "class C { public: C(int); C(const C&) = delete; "
        "C& operator=(const C&) = delete; ~C() = default; };"
    )
    view = document.class_views("C")[0]
    functions = {function.name: function for function in view.functions()}
    assert "operator=" in functions
    assert "~C" in functions
    assert functions["operator="].deleted
    assert functions["~C"].defaulted
    assert len(view.constructors(public_only=True)) == 2
    assert len(view.constructors(public_only=True, callable_only=True)) == 1


def test_call_view_arguments() -> None:
    """验证调用视图按源码顺序返回完整实参。
    Verify that call views return complete arguments in source order.
    """
    document = CppDocument.parse("void f() { target(a, b + c); }")
    call = document.call_views("target")[0]
    assert call.callee == "target"
    assert [argument.text for argument in call.arguments] == ["a", "b + c"]


def test_include_and_variable_views_cover_file_and_function_scope() -> None:
    """验证 include 与变量视图同时覆盖文件作用域和函数作用域。
    Verify that include and variable views cover both file and function scope.
    """
    document = CppDocument.parse(
        '#include "local.hpp"\n'
        '#include <vector>\n'
        'static int global_value = 3;\n'
        'void f() {\n'
        '  static Foo local = Foo(arg);\n'
        '  auto& ref = global_value;\n'
        '}\n'
    )

    includes = document.include_views()
    assert [(item.header, item.system) for item in includes] == [
        ("local.hpp", False),
        ("vector", True),
    ]

    variables = {item.name: item for item in document.variable_views()}
    assert variables["global_value"].base_type == "int"
    assert variables["global_value"].storage == ("static",)
    assert variables["global_value"].initializer == "3"
    assert variables["global_value"].global_scope

    assert variables["local"].base_type == "Foo"
    assert variables["local"].initializer == "Foo(arg)"
    assert not variables["local"].global_scope
    assert variables["ref"].base_type == "auto"
    assert variables["ref"].initializer == "global_value"
    assert not variables["ref"].global_scope


def test_constructor_declarations_with_defaults_remain_functions() -> None:
    """验证只有声明的构造函数即使带默认值也不会被误判为调用表达式。
    Verify that constructor prototypes with default arguments remain function declarations.
    """
    document = CppDocument.parse(
        "class Foo { public: Foo(int count = 10); Foo(float gain = 1.0f); };"
    )
    constructors = document.class_views("Foo")[0].constructors(public_only=True)
    assert [item.name for item in constructors] == ["Foo", "Foo"]
    assert [[parameter.name for parameter in item.parameters] for item in constructors] == [
        ["count"],
        ["gain"],
    ]
    assert [item.parameters[0].default for item in constructors] == ["10", "1.0f"]
    assert not document.call_views("Foo")


def test_template_parameter_defaults_keep_nested_template_commas() -> None:
    """验证模板默认类型中的嵌套逗号不会切开外层模板参数。
    Verify that commas in nested template defaults do not split outer template parameters.
    """
    document = CppDocument.parse(
        "template <typename T = std::array<int, 2>, int N = 4> class Foo {};"
    )
    parameters = document.class_views("Foo")[0].template_parameters
    assert [item.name for item in parameters] == ["T", "N"]
    assert [item.default for item in parameters] == ["std::array<int, 2>", "4"]


def test_class_name_after_attributes() -> None:
    """验证 class-head 中的属性说明不会被当成类名。
    Verify that attribute specifiers in a class head are not taken as the class name.
    """
    source = (
        "struct [[gnu::packed]] Packed { int a; };\n"
        "struct alignas(alignof(double)) Aligned { int a; };\n"
        "struct __attribute__((packed)) GnuPacked { int a; };\n"
        "class [[nodiscard]] Final final : public Base {};\n"
        "struct { int a; } anonymous;\n"
    )
    names = {view.name for view in CppDocument.parse(source).class_views()}
    assert names == {"Packed", "Aligned", "GnuPacked", "Final", None}
