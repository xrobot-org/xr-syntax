"""验证 C++ 文件、函数和代码块构建器覆盖常用生成场景。
Test common C++ file, function, and block generation workflows.
"""

from xr_syntax.cpp import CppFileBuilder


def test_source_builder_covers_common_generator_operations() -> None:
    """验证 C++ builder 覆盖常用代码生成操作。
    Verify that the C++ builder covers common source-generation operations.
    """
    source = CppFileBuilder()
    source.include("app_main.h")
    source.include("cstdint", system=True)
    source.variable("int", "global_counter", initializer="0", storage=["static"])

    app = source.function("void", "app_main", prefix=['extern "C"'])
    app.body.variable(
        "STM32GPIO",
        "LED_B",
        initializer="GPIOB",
        storage=["static"],
    )
    app.body.call("XR_REGISTER", ["LED_B", "LibXR::GPIO"])
    app.body.user_region(
        "3",
        [source.factory.call_statement("XROBOT_MAIN", [])],
    )

    document = source.build()
    text = document.render()
    assert '#include "app_main.h"' in text
    assert "#include <cstdint>" in text
    assert "static int global_counter = 0;" in text
    assert "static STM32GPIO LED_B = GPIOB;" in text
    assert "XR_REGISTER(LED_B, LibXR::GPIO);" in text
    assert "/* User Code Begin 3 */" in text
    assert len(document.functions("app_main")) == 1
    assert len(document.calls("XR_REGISTER")) == 1
    assert len(document.user_regions()) == 1


def test_header_builder_adds_pragma_once() -> None:
    """验证头文件 builder 会按约定加入 pragma once。
    Verify that the header builder emits pragma once as required.
    """
    header = CppFileBuilder(header=True)
    header.include("thread.hpp")
    document = header.build()
    assert document.render().startswith('#pragma once\n#include "thread.hpp"\n')


def test_file_builder_structures_format_and_lint_regions() -> None:
    """验证文件 builder 能生成结构化 format 与 lint 保护区域。
    Verify that the file builder creates structured format and lint protection regions.
    """
    source = CppFileBuilder()
    declaration = source.factory.declaration("static int generated = 0")
    source.format_disabled([declaration])
    source.lint_disabled([source.factory.call_statement("generated_call", [])])

    document = source.build()
    assert len(document.format_regions()) == 1
    assert len(document.lint_regions()) == 1
    assert "static int generated = 0;" in document.format_regions()[0].body_text
    assert "generated_call();" in document.lint_regions()[0].body_text


def test_cpp_builder_parses_only_once_at_build_boundary() -> None:
    """验证 builder-only 路径不会逐片段 parse，最终 build 只 parse 一次。
    Verify that the builder-only path parses once at the final build boundary.
    """
    from xr_syntax.cpp import CppFactory, CppParser

    class CountingParser(CppParser):
        """记录 parse 调用次数的测试 parser。
        Test parser that counts parse calls.
        """

        def __init__(self) -> None:
            """初始化 parser 和计数器。
            Initialize the parser and parse-call counter.
            """
            super().__init__()
            self.calls = 0

        def parse(self, source, *, source_name=None):  # type: ignore[no-untyped-def,override]
            """记录调用后执行正常解析。
            Count the call and delegate to the normal parser.
            """
            self.calls += 1
            return super().parse(source, source_name=source_name)

    parser = CountingParser()
    builder = CppFileBuilder(factory=CppFactory(parser=parser))
    builder.include("app.hpp")
    builder.comment("generated")
    builder.variable("int", "value", initializer="1", storage=["static"])
    function = builder.function("void", "run")
    function.body.call("target", ["value"])
    function.body.user_region("body", [function.body.raw("keep();")])

    assert parser.calls == 0
    document = builder.build(require_clean=True)
    assert parser.calls == 1
    assert len(document.functions("run")) == 1
    assert len(document.user_regions()) == 1


def test_cpp_builder_require_clean_controls_generation_diagnostics() -> None:
    """验证 builder 默认保留 diagnostics，strict 模式会拒绝有诊断的生成结果。
    Verify that builders expose diagnostics by default and can reject them explicitly.
    """
    import pytest

    builder = CppFileBuilder()
    builder.raw("void broken() {")
    document = builder.build()
    assert document.diagnostics

    strict = CppFileBuilder()
    strict.raw("void broken() {")
    with pytest.raises(ValueError, match="generated C\\+\\+ source"):
        strict.build(require_clean=True)
