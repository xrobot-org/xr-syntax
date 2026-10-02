"""提供 C++ declarator、声明名称和类型文本提取等语法辅助函数。
Internal C++ declarator/name helpers shared by typed convenience views.
"""

from __future__ import annotations

from xr_syntax.core import SyntaxElement, SyntaxNode, decode_source


def field_text(node: SyntaxNode, field: str) -> str | None:
    """返回节点指定 field 的精确源码文本；field 不存在时返回 None。
    Return raw source text for one parser field, or None when absent.
    """
    child = node.child_by_field(field)
    return None if child is None else child.text


def declaration_name_element(node: SyntaxNode) -> SyntaxElement | None:
    """函数或参数名称的语法元素；带括号的名字 (isinf) 取括号里的名字。
    The syntax element of a function or parameter name; for a parenthesized name (isinf), the
    name inside the parentheses.

    名字是函数声明子的 declarator 字段，没有函数声明子时是节点自己的 declarator 字段。
    The name is the declarator field of the function declarator, or of the node itself without
    one.
    """
    function = find_function_declarator(node)
    name = (function if function is not None else node).child_by_field("declarator")
    if isinstance(name, SyntaxNode) and name.kind == "parenthesized_declarator":
        return name.child_by_field("declarator")
    return name


def declaration_name(node: SyntaxNode) -> str | None:
    """返回声明的源码级名称文本；无法定位时返回 None。
    Return the source spelling of a declaration name when identifiable.
    """
    element = declaration_name_element(node)
    return None if element is None else element.text


def declaration_type_text(node: SyntaxNode) -> str | None:
    """重建声明的源码级类型文本，同时排除名称和初始化器；没有名称时是 = 之前的全部文本。
    Reconstruct source-level type text without the name and the initializer; without a name it
    is all the text before the =.
    """
    end = node.span.end
    equal = next(
        (child for child in node.syntax_children if child.kind == "="),
        None,
    )
    if equal is not None:
        end = equal.span.start

    source = node.tree.render_bytes()
    name = declaration_name_element(node)
    if name is None:
        raw = source[node.span.start : end]
    else:
        raw = source[node.span.start : name.span.start] + source[name.span.end : end]
    return decode_source(raw).strip()


def find_function_declarator(node: SyntaxNode) -> SyntaxNode | None:
    """在函数或声明结构中定位 function_declarator 节点。
    Return the first function_declarator at or below a syntax node.
    """
    if node.kind == "function_declarator":
        return node
    found = node.first_descendant("function_declarator")
    return found if isinstance(found, SyntaxNode) else None
