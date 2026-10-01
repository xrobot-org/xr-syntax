"""验证深层嵌套和长运算符链：解析不会因递归过深而失败，嵌套上限之内完整结构化。
Test deep nesting and long operator chains: parsing never fails on recursion depth, and source
within the nesting limit is fully structured.
"""

import sys

from xr_syntax.core.red import SyntaxNode
from xr_syntax.cpp import CppDocument


def _count(document: CppDocument, kind: str) -> int:
    """文档中指定 kind 的节点个数。
    The number of nodes of one kind in a document.
    """
    return sum(1 for _ in document.root.descendants(kind))


def _too_deep(document: CppDocument) -> bool:
    """是否给出了“嵌套过深”诊断。
    Whether the "nesting too deep" diagnostic was given.
    """
    return any("nesting too deep" in item.message for item in document.tree.diagnostics)


def test_a_long_operator_chain_is_left_associative_and_needs_no_recursion() -> None:
    """3000 项的加法链解析成左结合的二元表达式（每一项一层），源码原样还原。
    A 3000-term sum parses into left-associative binary expressions (one level per term) and
    renders unchanged.
    """
    source = "int x = " + " + ".join(f"a{i}" for i in range(3000)) + ";\n"
    document = CppDocument.parse(source)
    assert document.tree.render() == source
    assert not document.tree.diagnostics
    assert _count(document, "binary_expression") == 2999
    outer = next(document.root.descendants("binary_expression"))
    assert isinstance(outer, SyntaxNode)
    left, right = outer.child_by_field("left"), outer.child_by_field("right")
    assert left is not None and left.kind == "binary_expression"
    assert right is not None and right.text == "a2999"


def test_nesting_as_deep_as_real_code_is_fully_structured() -> None:
    """50 层嵌套调用（实际源码最深约 22 层）全部结构化，没有诊断。
    Calls nested 50 deep (real source nests about 22 levels at most) are all structured, without
    a diagnostic.
    """
    source = "int x = " + "f(" * 50 + "0" + ")" * 50 + ";\n"
    document = CppDocument.parse(source)
    assert _count(document, "call_expression") == 50
    assert not document.tree.diagnostics


def test_nesting_past_the_limit_stays_source_with_a_diagnostic() -> None:
    """3000 层嵌套的调用、代码块、括号和 lambda 都能解析：上限以内结构化，更深处保留为源码并给出诊断。
    Calls, blocks, parentheses and lambdas nested 3000 deep all parse: structured up to the limit,
    kept as source deeper down, with a diagnostic.
    """
    depth = 3000
    sources = {
        "call_expression": "int x = " + "f(" * depth + "0" + ")" * depth + ";\n",
        "if_statement": "void f() " + "{ if (a) " * depth + "x = 1;" + " }" * depth + "\n",
        "parenthesized_expression": "int x = " + "(" * depth + "1" + ")" * depth + ";\n",
        "lambda_expression": "auto x = " + "[]{ return " * depth + "1" + "; }()" * depth + ";\n",
    }
    for kind, source in sources.items():
        document = CppDocument.parse(source)
        assert document.tree.render() == source
        assert 0 < _count(document, kind) < depth, kind
        assert _too_deep(document), kind


def test_parsing_from_a_deep_call_stack_stays_within_the_recursion_limit() -> None:
    """调用方已经用掉一半递归深度时，嵌套上限随之降低，解析仍然成功。
    When the caller has already used half of the recursion depth, the nesting limit drops
    accordingly and parsing still succeeds.
    """
    source = "void f() " + "{ if (a) " * 200 + "x = 1;" + " }" * 200 + "\n"

    def nested(levels: int) -> CppDocument:
        """在 levels 层递归之后解析。
        Parse after levels of recursion.
        """
        return nested(levels - 1) if levels else CppDocument.parse(source)

    document = nested(sys.getrecursionlimit() // 2)
    assert document.tree.render() == source
    assert _too_deep(document)
