"""验证 CppFactory 生成的片段使用同一 parser-backed 语法模型。
Test that CppFactory fragments use the same parser-backed syntax model.
"""

from xr_syntax.cpp import CppFactory


def test_factory_builds_parser_backed_syntax() -> None:
    """验证 CppFactory 创建的片段都会重新进入 parser-backed 语法模型。
    Verify that fragments created by CppFactory re-enter the parser-backed syntax model.
    """
    factory = CppFactory(width=40)
    include = factory.include("libxr.hpp")
    call = factory.call_statement("XR_REGISTER", ["led", "LibXR::GPIO"])
    variable = factory.variable(
        "STM32GPIO",
        "led",
        storage=["static"],
        initializer="GPIOB",
    )

    assert include.render() == '#include "libxr.hpp"\n'
    assert "XR_REGISTER" in call.render()
    assert variable.render() == "static STM32GPIO led = GPIOB;"


def test_expression_is_structured() -> None:
    """验证工厂创建的表达式具有可查询的结构节点。
    Verify that expressions created by the factory expose queryable structural nodes.
    """
    expression = CppFactory().expression("a + b * c")
    assert expression.render() == "a + b * c"


def test_cpp_factory_comment_handles_named_comment_tokens() -> None:
    """验证 comment factory 可以包装 parser 暴露的 named token。
    Verify that comment factories handle comments exposed as named tokens.
    """
    factory = CppFactory()
    assert factory.comment("line").render() == "// line"
    assert factory.comment("block", block=True).render() == "/* block */"
