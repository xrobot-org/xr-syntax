"""测试 C++ 解析器：逐字节还原源码、结构识别、深层嵌套和并发解析。
Tests of the C++ parser: byte-for-byte reproduction, structure, deep nesting and concurrency.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from xr_syntax.core import SourcePoint, SourceSpan, SyntaxNode
from xr_syntax.cpp import CppDocument, CppParser


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            b'#include "foo.hpp"\r\n'
            b"\r\n"
            b"// comment\r\n"
            b"#define FOO(x) ((x) + 1)\r\n"
            b"template <typename T>\r\n"
            b"T f(T value) {\r\n"
            b'  auto s = R"tag(a // b)tag";\r\n'
            b"  return FOO(value);\r\n"
            b"}\r\n",
            id="crlf-and-raw-string",
        ),
        pytest.param(b"", id="empty"),
        pytest.param(b"void f() {\n  foo(\n", id="incomplete"),
        pytest.param(b"\xef\xbb\xbf#pragma once\r\n", id="bom"),
        pytest.param(b"int value; // byte: \xff\n", id="non-utf8"),
        # 预处理行夹在表达式中间时，表达式的边界不能吞掉两侧的空白和换行。
        # With a preprocessor line inside an expression, the expression bounds must not take in
        # the whitespace and newlines around it.
        pytest.param(
            b"bool f(bool ready) {\n"
            b"  return ready\n"
            b"#if defined(EXTRA)\n"
            b"         && extra\n"
            b"#endif\n"
            b"      ;\n"
            b"}\n"
            b"void g() { int value = 1 ; target((value   )); }\n",
            id="preprocessor-inside-expression",
        ),
    ],
)
def test_parsing_reproduces_the_source_bytes(source: bytes) -> None:
    assert CppDocument.parse(source).render_bytes() == source


def test_surrogateescaped_text_gives_back_the_original_bytes() -> None:
    source = b"int value; // byte: \xff\n"
    text = source.decode("utf-8", errors="surrogateescape")
    assert CppDocument.parse(text).render_bytes() == source


def test_a_complete_source_has_no_diagnostics() -> None:
    document = CppDocument.parse(b"int f(int a) { return a + 1; }\n")
    assert document.diagnostics == ()
    assert document.root.kind == "translation_unit"


def test_modern_syntax_is_structured() -> None:
    source = (
        "template <typename T>\n"
        "concept Addable = requires(T t) { t + t; };\n"
        "\n"
        "template <Addable T>\n"
        "auto fold(T... xs) {\n"
        "  auto lambda = []<typename U>(U value) requires Addable<U> { return value; };\n"
        "  return (lambda(xs) + ...);\n"
        "}\n"
    )
    document = CppDocument.parse(source)
    assert [len(document.nodes(kind)) for kind in ("requires_expression", "lambda_expression")] == [
        1,
        1,
    ]
    assert len(document.nodes("fold_expression")) == 1


def test_a_continued_define_does_not_swallow_the_next_class() -> None:
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
    assert document.diagnostics == ()
    assert [view.name for view in document.class_views()] == ["Sensor"]


def test_a_long_operator_chain_is_left_associative() -> None:
    source = "int x = " + " + ".join(f"a{i}" for i in range(3000)) + ";\n"
    document = CppDocument.parse(source)
    assert document.render() == source
    assert document.diagnostics == ()
    assert len(document.nodes("binary_expression")) == 2999
    outer = document.nodes("binary_expression")[0]
    left, right = outer.child_by_field("left"), outer.child_by_field("right")
    assert left is not None and left.kind == "binary_expression"
    assert right is not None and right.text == "a2999"


def test_assignment_is_right_associative() -> None:
    outer = CppDocument.parse("void f() { a = b = c; }\n").nodes("assignment_expression")[0]
    left, right = outer.child_by_field("left"), outer.child_by_field("right")
    assert left is not None and left.text == "a"
    assert right is not None and right.kind == "assignment_expression"
    assert right.text == "b = c"


def test_nesting_as_deep_as_real_code_is_fully_structured() -> None:
    # 实际源码最深约 22 层。
    # Real source nests about 22 levels at most.
    source = "int x = " + "f(" * 50 + "0" + ")" * 50 + ";\n"
    document = CppDocument.parse(source)
    assert len(document.nodes("call_expression")) == 50
    assert document.diagnostics == ()


@pytest.mark.parametrize(
    ("kind", "source"),
    [
        ("call_expression", "int x = " + "f(" * 3000 + "0" + ")" * 3000 + ";\n"),
        ("if_statement", "void f() " + "{ if (a) " * 3000 + "x = 1;" + " }" * 3000 + "\n"),
        ("parenthesized_expression", "int x = " + "(" * 3000 + "1" + ")" * 3000 + ";\n"),
        ("lambda_expression", "auto x = " + "[]{ return " * 3000 + "1" + "; }()" * 3000 + ";\n"),
    ],
)
def test_nesting_past_the_limit_stays_source_with_a_diagnostic(kind: str, source: str) -> None:
    document = CppDocument.parse(source)
    assert document.render() == source
    assert 0 < len(document.nodes(kind)) < 3000
    assert {item.message for item in document.diagnostics} == {
        "nesting too deep; the inner source is kept unstructured"
    }


def test_the_nesting_limit_follows_the_recursion_depth_left() -> None:
    source = "void f() " + "{ if (a) " * 200 + "x = 1;" + " }" * 200 + "\n"

    def nested(levels: int) -> CppDocument:
        """在 levels 层递归之后解析。
        Parse after levels of recursion.
        """
        return nested(levels - 1) if levels else CppDocument.parse(source)

    document = nested(sys.getrecursionlimit() // 2)
    assert document.render() == source
    assert {item.message for item in document.diagnostics} == {
        "nesting too deep; the inner source is kept unstructured"
    }


def test_one_parser_can_be_shared_by_threads() -> None:
    parser = CppParser()
    sources = [f"void f{i}() {{ target({i}); }}\n".encode() for i in range(64)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        rendered = list(executor.map(lambda source: parser.parse(source).render_bytes(), sources))
    assert rendered == sources


def test_the_root_is_a_node_without_parent() -> None:
    root = CppDocument.parse("int x;\n").root
    assert isinstance(root, SyntaxNode)
    assert root.parent is None


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("if (a) x = 0;" + " else if (a) x = 1;" * 2000, id="else-if"),
        pytest.param("if (a) " * 2000 + "x = 1;", id="unbraced-if"),
    ],
)
def test_long_control_chains_parse(body: str) -> None:
    source = "void f() { " + body + " }\n"
    assert CppDocument.parse(source).render() == source


def test_an_extern_c_block_is_a_scope() -> None:
    source = 'extern "C" {\n#include "a.h"\nclass X { public: X(int); };\n}\n'
    document = CppDocument.parse(source)
    assert [view.header for view in document.include_views()] == ["a.h"]
    assert [view.name for view in document.class_views()] == ["X"]


def test_an_inline_namespace_is_a_namespace() -> None:
    document = CppDocument.parse("inline namespace v1 { class Y {}; }\n")
    namespaces = document.nodes("namespace_definition")
    assert [node.child_by_field("name").text for node in namespaces] == ["v1"]
    assert [view.name for view in document.class_views()] == ["Y"]


def test_a_namespace_alias_is_no_namespace() -> None:
    document = CppDocument.parse("namespace fs = std::filesystem;\nclass Z {};\n")
    assert document.nodes("namespace_definition") == ()
    assert [view.name for view in document.class_views()] == ["Z"]


def test_a_nested_namespace_definition_keeps_its_whole_name() -> None:
    document = CppDocument.parse("namespace a::b { class W {}; }\n")
    namespaces = document.nodes("namespace_definition")
    assert [node.child_by_field("name").text for node in namespaces] == ["a::b"]


def test_a_comment_before_a_directive_keeps_the_directive() -> None:
    document = CppDocument.parse('/* c */ #include "a.h"\n#include "b.h"\nint x;\n')
    assert [view.header for view in document.include_views()] == ["a.h", "b.h"]


@pytest.mark.parametrize(
    "initializers",
    [
        pytest.param("x_(1), y_{2}", id="brace-initializer"),
        pytest.param("base_(f(), {1, 2})", id="brace-in-arguments"),
        pytest.param("Base<int>{1}", id="template-base"),
    ],
)
def test_a_constructor_body_follows_its_initializers(initializers: str) -> None:
    document = CppDocument.parse(f"A::A() : {initializers} {{ body(); }}\n")
    functions = document.nodes("function_definition")
    assert [node.child_by_field("body").text for node in functions] == ["{ body(); }"]


@pytest.mark.parametrize(
    ("source", "name"),
    [
        pytest.param("std::string s;", "s", id="qualified-type"),
        pytest.param("std::vector<std::vector<int>> v;", "v", id="closing-shift"),
        pytest.param('std::string Foo::name_ = "x";', "Foo::name_", id="qualified-name"),
        pytest.param("Foo* Foo::map_[4] = {nullptr};", "Foo::map_", id="qualified-array"),
        pytest.param("typedef void (*Callback)(void*);", "Callback", id="function-pointer-type"),
        pytest.param("void (*handler)(int) = nullptr;", "handler", id="function-pointer"),
        pytest.param("typedef struct { int a; } Point;", "Point", id="typedef-struct"),
        pytest.param(
            "typedef struct __attribute__((packed)) { int a; } Packed;",
            "Packed",
            id="typedef-packed-struct",
        ),
        pytest.param(
            "typedef enum {\n#if defined(A)\n  X,\n#endif\n} Kind;", "Kind", id="typedef-enum"
        ),
    ],
)
def test_a_declaration_gives_its_declarator_name(source: str, name: str) -> None:
    declaration = CppDocument.parse(source).nodes("declaration")[0]
    declarator = declaration.child_by_field("declarator")
    assert isinstance(declarator, SyntaxNode)
    assert declarator.child_by_field("declarator").text == name


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("typedef void (*Callback)(void*);", id="function-pointer-type"),
        pytest.param("std::function<void()> callback;", id="function-in-template-argument"),
        pytest.param("alignas(4) static uint8_t buf[4] = {1, 2, 3, 4};", id="alignas"),
        pytest.param(
            "static const int table[] = {\n#if defined(A)\n  1,\n#endif\n};", id="directive"
        ),
        pytest.param("static_assert(std::is_same_v<A, B>);", id="static-assert"),
    ],
)
def test_parentheses_in_a_declaration_declare_no_function(source: str) -> None:
    assert CppDocument.parse(source).nodes("function_declarator") == ()


def test_statements_in_a_function_body_are_told_apart() -> None:
    source = (
        "void f() {\n"
        "  Config.mode = 1;\n"
        "  Port->level = 2;\n"
        "  std::cout << a << b;\n"
        "  std::string s;\n"
        "  { int y = 1; }\n"
        "}\n"
    )
    body = CppDocument.parse(source).nodes("function_definition")[0].child_by_field("body")
    assert isinstance(body, SyntaxNode)
    assert [node.kind for node in body.named_children] == [
        "expression_statement",
        "expression_statement",
        "expression_statement",
        "declaration_statement",
        "compound_statement",
    ]


def test_case_labels_are_units_of_their_own() -> None:
    source = "void f(int x) { switch (x) { case 1: g(); break; default: return Code::ERR; } }\n"
    switch = CppDocument.parse(source).nodes("switch_statement")[0]
    body = switch.child_by_field("consequence")
    assert isinstance(body, SyntaxNode)
    assert [(node.kind, node.text) for node in body.named_children] == [
        ("case_label", "case 1:"),
        ("expression_statement", "g();"),
        ("break_statement", "break;"),
        ("case_label", "default:"),
        ("return_statement", "return Code::ERR;"),
    ]


def test_an_anonymous_enum_is_a_declaration() -> None:
    document = CppDocument.parse("class M { enum { Size = (A & B) == B ? 1 : 2 }; };\n")
    declarations = document.nodes("declaration")
    assert [node.child_by_field("type").text for node in declarations] == [
        "enum { Size = (A & B) == B ? 1 : 2 }"
    ]


def test_diagnostics_give_the_row_and_byte_column() -> None:
    source = "void f() {\r\n  é(1, \r\n}\r\n"
    diagnostics = CppDocument.parse(source).diagnostics
    assert [
        (item.message, item.span, item.start_point, item.end_point) for item in diagnostics
    ] == [
        (
            "unmatched closing delimiter",
            SourceSpan(22, 23),
            SourcePoint(2, 0),
            SourcePoint(2, 1),
        ),
        ("unclosed delimiter", SourceSpan(9, 10), SourcePoint(0, 9), SourcePoint(0, 10)),
        ("unclosed delimiter", SourceSpan(16, 17), SourcePoint(1, 4), SourcePoint(1, 5)),
    ]


def test_diagnostic_rows_count_the_lines_inside_comments() -> None:
    diagnostics = CppDocument.parse("/* a\nb */\nvoid f() {\n").diagnostics
    assert [(item.message, item.start_point) for item in diagnostics] == [
        ("unclosed delimiter", SourcePoint(2, 9))
    ]
