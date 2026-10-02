"""验证原生 C++ parser 的 runtime schema 和现代 C++ 结构分类。
Test the native C++ parser runtime schema and modern C++ syntax classification.
"""

from xr_syntax.cpp import CppDocument


def test_complex_cpp_syntax_remains_structured_and_lossless() -> None:
    """模板、concept、requires、lambda 和 fold expression 必须保持结构化且无损。
    Verify that templates, concepts, requires expressions, lambdas, and fold expressions remain structured and lossless.
    """
    source = b"""template <typename T>
concept Addable = requires(T t) { t + t; };

template <Addable T>
auto fold(T... xs) {
  auto lambda = []<typename U>(U value) requires Addable<U> { return value; };
  return (lambda(xs) + ...);
}
"""
    document = CppDocument.parse(source)
    assert document.render_bytes() == source
    assert document.nodes("requires_expression")
    assert document.nodes("lambda_expression")
    assert document.nodes("fold_expression")


def test_utf8_bom_is_source_trivia_not_lost() -> None:
    """BOM 是源码字节的一部分，不能在 parser 层消失。
    Verify that a UTF-8 BOM remains part of the source and is not lost by the parser.
    """
    source = b"\xef\xbb\xbf#pragma once\r\n"
    document = CppDocument.parse(source)
    assert document.render_bytes() == source
