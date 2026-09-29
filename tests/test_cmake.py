"""验证 CMake grammar、无损解析、查询、构建和编辑行为。
Test CMake grammar metadata, lossless parsing, queries, builders, and structured edits.
"""

from __future__ import annotations

from xr_syntax.cmake import (
    CMAKE_GRAMMAR,
    CMakeDocument,
    CMakeFactory,
    CMakeFileBuilder,
    CMakeParser,
)


def test_cmake_grammar_schema_matches_native_runtime() -> None:
    """验证打包的 CMake grammar schema 与实际运行时 parser 保持一致。
    Verify that packaged CMake grammar metadata matches the native parser.
    """
    assert CMAKE_GRAMMAR.version == "0.7.4"
    assert CMAKE_GRAMMAR.source_revision == ("ca627bb5828616b6246aafdc3c3222789e728e37")
    assert len(CMAKE_GRAMMAR.nodes) == 71
    assert [(node.kind, node.named) for node in CMAKE_GRAMMAR.roots] == [("source_file", True)]

    runtime_kinds = CMakeParser().schema.kind_names
    missing: set[tuple[str, bool]] = set()
    for node in CMAKE_GRAMMAR.nodes:
        refs = list(node.subtypes)
        if node.children is not None:
            refs.extend(node.children.types)
        for _, field in node.fields:
            refs.extend(field.types)
        for ref in refs:
            if ref.kind not in runtime_kinds:
                missing.add((ref.kind, ref.named))
    assert not missing

    source = CMakeDocument.parse("project(Demo)\n")
    spec = source.grammar_spec(source.commands("project")[0])
    assert spec is not None
    assert spec.kind == "normal_command"


def test_empty_cmake_file_is_a_lossless_node() -> None:
    """验证空 CMake 文件仍表示为可无损渲染的根节点。
    Verify that an empty CMake file is still represented by a losslessly renderable root node.
    """
    document = CMakeDocument.parse(b"")
    assert document.render_bytes() == b""
    assert document.root.kind == "source_file"
    assert not document.diagnostics


def test_cmake_roundtrip_and_queries() -> None:
    """验证 CMake 源码逐字节 round-trip 以及常用查询结果。
    Verify byte-for-byte CMake round-trip behavior and common query results.
    """
    source = (
        b"cmake_minimum_required(VERSION 3.20)\r\n"
        b"project(Demo LANGUAGES C CXX)\r\n"
        b"# keep this comment\r\n"
        b"add_library(foo STATIC a.cpp b.cpp)\r\n"
        b"if(FOO)\r\n"
        b'  message(STATUS "enabled")\r\n'
        b"endif()\r\n"
    )
    document = CMakeDocument.parse(source)
    assert document.render_bytes() == source
    assert not document.diagnostics
    assert len(document.command_views("project")) == 1

    library = document.command_views("add_library")[0]
    assert library.name == "add_library"
    assert [argument.text for argument in library.arguments] == [
        "foo",
        "STATIC",
        "a.cpp",
        "b.cpp",
    ]
    assert {command.name for command in document.command_views()} >= {
        "project",
        "add_library",
        "if",
        "message",
        "endif",
    }


def test_cmake_builder_uses_same_syntax_model() -> None:
    """验证 CMake builder 生成结果与 parser 使用同一语法模型。
    Verify that CMake builder output uses the same syntax model as parsed source.
    """
    builder = CMakeFileBuilder()
    builder.command("cmake_minimum_required", ["VERSION", "3.20"])
    builder.command("project", ["Demo", "LANGUAGES", "CXX"])
    builder.command("add_library", ["foo", "STATIC", "foo.cpp"])

    document = builder.build()
    assert not document.diagnostics
    assert len(document.command_views("add_library")) == 1
    assert document.render().endswith("add_library(foo STATIC foo.cpp)\n")


def test_cmake_structured_edit_reparses() -> None:
    """验证 CMake 结构化编辑后会重新解析并刷新语法结构。
    Verify that structured CMake edits reparse and refresh syntax structure.
    """
    document = CMakeDocument.parse("project(Old)\n")
    command = document.commands("project")[0]
    replacement = CMakeFactory().command("project", ["New"])
    changed = document.replace(command, replacement)

    assert document.render() == "project(Old)\n"
    assert changed.render() == "project(New)\n"
    assert changed.command_views("project")[0].arguments[0].text == "New"


def test_cmake_builder_parses_only_once_at_build_boundary() -> None:
    """验证 CMake builder-only 路径最终只 parse 一次。
    Verify that the CMake builder-only path parses once at the final build boundary.
    """

    class CountingParser(CMakeParser):
        """记录 parse 调用次数的测试 CMake parser。
        Test CMake parser that counts parse calls.
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
    builder = CMakeFileBuilder(factory=CMakeFactory(parser=parser))
    builder.comment("generated")
    builder.command("project", ["Demo"])
    body = [builder.factory._command_draft("message", ["STATUS", '"ok"'])]
    builder.if_block(["ENABLED"], body)

    assert parser.calls == 0
    document = builder.build(require_clean=True)
    assert parser.calls == 1
    assert len(document.command_views("project")) == 1
    assert len(document.command_views("message")) == 1


def test_cmake_factory_comment_handles_named_comment_tokens() -> None:
    """验证 CMake comment factory 可以包装 named token。
    Verify that the CMake comment factory handles named comment tokens.
    """
    assert CMakeFactory().comment("generated").render() == "# generated"


def test_cmake_builder_require_clean_controls_generation_diagnostics() -> None:
    """验证 CMake builder strict 模式会拒绝有 parser diagnostics 的生成结果。
    Verify that strict CMake builds reject generated source with parser diagnostics.
    """
    import pytest

    builder = CMakeFileBuilder()
    builder.raw("if(FOO)\n")
    assert builder.build().diagnostics

    strict = CMakeFileBuilder()
    strict.raw("if(FOO)\n")
    with pytest.raises(ValueError, match="generated CMake source"):
        strict.build(require_clean=True)


def test_cmake_surrogateescaped_text_input_roundtrips_losslessly() -> None:
    """验证 CMake 对 surrogateescape str 输入也保持原始字节。
    Verify lossless CMake round-trip for surrogateescaped str input.
    """
    source = b"# byte: \xff\nproject(Demo)\n"
    text = source.decode("utf-8", errors="surrogateescape")
    document = CMakeDocument.parse(text)
    assert document.render_bytes() == source
