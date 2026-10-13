"""验证 C++ 文件构建器：区域标记、逐字保留的区域体、只解析一次和整文件校验。
Test the C++ file builder: region markers, verbatim region bodies, one parse, and the whole-file
check.
"""

from __future__ import annotations

import pytest

from xr_syntax.core import SourceDraft
from xr_syntax.cpp import CppDocument, CppFileBuilder, CppParser


def test_the_builder_covers_the_operations_the_generators_need() -> None:
    builder = CppFileBuilder(header=True)
    builder.raw("")
    builder.include("libxr.hpp")
    builder.include("vector", system=True)
    builder.raw("")
    builder.raw("// an instance")
    builder.raw("static T x(1);")
    builder.format_region('\nMANIFEST = {"a": 1}\n')

    document = builder.build()
    assert document.render() == (
        "#pragma once\n"
        "\n"
        '#include "libxr.hpp"\n'
        "#include <vector>\n"
        "\n"
        "// an instance\n"
        "static T x(1);\n"
        "// clang-format off\n"
        'MANIFEST = {"a": 1}\n'
        "// clang-format on\n"
    )


def test_a_region_body_is_kept_verbatim() -> None:
    body = '\nMANIFEST = {\n  "a": 1,\n}\n'
    builder = CppFileBuilder()
    builder.raw("void f();")
    builder.format_region(body)
    document = builder.build()
    assert document.render() == ("void f();\n// clang-format off" + body + "// clang-format on\n")


def test_an_empty_region_is_two_adjacent_marker_lines() -> None:
    builder = CppFileBuilder()
    builder.format_region()
    assert builder.build().render() == "// clang-format off\n// clang-format on\n"


def test_the_builder_parses_only_once_at_the_build_boundary() -> None:
    class CountingParser(CppParser):
        """记录 parse 调用次数的测试 C++ parser。
        Test C++ parser that counts parse calls.
        """

        def __init__(self) -> None:
            """初始化解析器和调用计数。
            Initialize the parser and the call counter.
            """
            super().__init__()
            self.calls = 0

        def parse(self, source, *, source_name=None):  # type: ignore[no-untyped-def,override]
            """记一次调用后交给正常解析。
            Count the call and delegate to the normal parser.
            """
            self.calls += 1
            return super().parse(source, source_name=source_name)

    parser = CountingParser()
    builder = CppFileBuilder(parser=parser)
    builder.include("libxr.hpp")
    builder.raw("static T x(1);")
    builder.format_region("\nMANIFEST = 1\n")

    assert parser.calls == 0
    document = builder.build(require_clean=True)
    assert parser.calls == 1
    assert len(document.include_views()) == 1
    assert "MANIFEST = 1" in document.render()


def test_require_clean_rejects_generated_source_with_diagnostics() -> None:
    builder = CppFileBuilder()
    builder.raw("void f( {")
    assert builder.build().diagnostics

    strict = CppFileBuilder()
    strict.raw("void f( {")
    with pytest.raises(ValueError, match="generated C\\+\\+ source"):
        strict.build(require_clean=True)


def test_an_item_of_another_language_is_refused() -> None:
    builder = CppFileBuilder()
    with pytest.raises(ValueError, match="draft language"):
        builder._add(SourceDraft("cmake", "project(Demo)\n"))


def test_an_empty_builder_gives_an_empty_document() -> None:
    document = CppFileBuilder().build()
    assert document.render() == ""
    assert not document.diagnostics


def test_a_header_of_a_generated_file_is_self_contained() -> None:
    builder = CppFileBuilder()
    builder.include("libxr.hpp")
    builder.raw("static LibXR::UART uart(1);")
    document = builder.build(require_clean=True)
    assert CppDocument.parse(document.render()).render() == document.render()


def test_a_trailing_empty_chunk_stays_a_blank_line() -> None:
    # 末尾的空 raw 是一个空行：build() 原样拼接每个片段，不做任何增删。
    # A trailing empty chunk is one blank line: build() joins every chunk as written and adds or
    # drops nothing.
    builder = CppFileBuilder()
    builder.raw("int x;")
    builder.raw("")
    assert builder.build().render() == "int x;\n\n"


def test_a_chunk_that_already_ends_with_a_newline_gains_none() -> None:
    builder = CppFileBuilder()
    builder.raw("int x;\n")
    builder.raw("int y;")
    assert builder.build().render() == "int x;\nint y;\n"
