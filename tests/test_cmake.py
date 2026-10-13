"""验证 CMake 的无损解析、查询、构建、语句编辑和 User Code 区域。
Test CMake lossless parsing, queries, builders, statement edits and User Code regions.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from xr_syntax.cmake import CMakeDocument, CMakeFileBuilder, CMakeParser
from xr_syntax.core import SourceRegion, SourceSpan

# 一份包含块、注释、引号参数、括号参数和 User Code 区域的 CMake 片段。
# A CMake excerpt with blocks, comments, quoted and bracket arguments, and a User Code region.
SAMPLE = (
    "# ---- Project settings ----\n"
    "set(LIBXR_SYSTEM None)\n"
    "set(LIBXR_DRIVER st)\n"
    "\n"
    "# ---- Compile options ----\n"
    "# User Code Begin CompileOptions\n"
    "add_compile_options(-Wall)\n"
    "# User Code End CompileOptions\n"
    "\n"
    "if(FOO)\n"
    '  message(STATUS "a (b")\n'
    "  foreach(i IN LISTS L)\n"
    "    set(X [=[ ) ]=])\n"
    "  endforeach()\n"
    "endif()\n"
)


def test_empty_cmake_file_is_a_lossless_node() -> None:
    document = CMakeDocument.parse(b"")
    assert document.render_bytes() == b""
    assert document.root.kind == "source_file"
    assert not document.diagnostics


def test_cmake_roundtrip_and_queries() -> None:
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


def test_quoted_bracket_and_line_comments_are_distinguished() -> None:
    document = CMakeDocument.parse(SAMPLE)
    assert not document.diagnostics
    assert document.render() == SAMPLE
    bracket = document.command_views("set")[2].arguments[1]
    assert bracket.node.kind == "argument"
    assert bracket.text == "[=[ ) ]=]"
    assert [comment.text for comment in document.comments()] == [
        "# ---- Project settings ----",
        "# ---- Compile options ----",
        "# User Code Begin CompileOptions",
        "# User Code End CompileOptions",
    ]


def test_blocks_group_the_paired_commands() -> None:
    document = CMakeDocument.parse(SAMPLE)
    assert [
        node.kind
        for node in document.root.descendants(
            kinds={"if_condition", "foreach_loop", "while_loop", "function_def", "macro_def"}
        )
    ] == ["if_condition", "foreach_loop"]
    # 块内的命令照样能查到，且按源码顺序排列。
    # Commands inside a block are found as well, in source order.
    assert [view.name for view in document.command_views()] == [
        "set",
        "set",
        "add_compile_options",
        "if",
        "message",
        "foreach",
        "set",
        "endforeach",
        "endif",
    ]


def test_top_level_statements_carry_their_leading_comments() -> None:
    document = CMakeDocument.parse(SAMPLE)
    statements = document.top_level_statements()
    assert [statement.name for statement in statements] == [
        "set",
        "set",
        "add_compile_options",
        "if",
    ]
    source = document.render_bytes()
    assert source[statements[0].leading_span.start : statements[0].span.end] == (
        b"# ---- Project settings ----\nset(LIBXR_SYSTEM None)"
    )
    # 上面是空行时不含注释；块语句整块返回。
    # A blank line above leaves no leading comment; a block statement is returned as a whole.
    assert statements[1].leading_span.start == statements[1].span.start
    assert source[statements[3].leading_span.start : statements[3].span.end].startswith(b"if(FOO)")
    assert statements[3].span.end - statements[3].span.start == len(
        'if(FOO)\n  message(STATUS "a (b")\n  foreach(i IN LISTS L)\n    set(X [=[ ) ]=])\n  endforeach()\nendif()'
    )


def test_unterminated_constructs_are_diagnosed_and_still_round_trip() -> None:
    for source in (b"if(FOO)\n", b'set(X "abc\n', b"set(X [=[abc\n", b"message(abc\n"):
        document = CMakeDocument.parse(source)
        assert document.render_bytes() == source
        assert document.diagnostics


def test_cmake_builder_uses_same_syntax_model() -> None:
    builder = CMakeFileBuilder()
    builder.comment("generated")
    builder.command("cmake_minimum_required", ["VERSION", "3.20"])
    builder.command("project", ["Demo", "LANGUAGES", "CXX"])
    builder.command("add_library", ["foo", "STATIC", "foo.cpp"])

    document = builder.build()
    assert not document.diagnostics
    assert document.render() == (
        "# generated\n"
        "cmake_minimum_required(VERSION 3.20)\n"
        "project(Demo LANGUAGES CXX)\n"
        "add_library(foo STATIC foo.cpp)\n"
    )
    assert len(document.command_views("add_library")) == 1


def test_a_generated_command_stays_on_one_line_whatever_its_length() -> None:
    # 生成的 CMake 没有排版工具，折行只会让输出随名字长度变化。
    # Generated CMake has no formatter, so breaking a line would only make the output depend on how
    # long a name happens to be.
    builder = CMakeFileBuilder()
    builder.command("set", ["LONG_NAME", '"' + "x" * 100 + '"'])
    assert builder.build().render() == 'set(LONG_NAME "' + "x" * 100 + '")\n'

    builder = CMakeFileBuilder()
    builder.command(
        "target_include_directories",
        ["xr", "PUBLIC", '"${CMAKE_CURRENT_LIST_DIR}/' + "a" * 60 + '"'],
    )
    assert builder.build().render() == (
        'target_include_directories(xr PUBLIC "${CMAKE_CURRENT_LIST_DIR}/' + "a" * 60 + '")\n'
    )


def test_cmake_builder_parses_only_once_at_build_boundary() -> None:
    class CountingParser(CMakeParser):
        """记录 parse 调用次数的测试 CMake parser。
        Test CMake parser that counts parse calls.
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
    builder = CMakeFileBuilder(parser=parser)
    builder.comment("generated")
    builder.command("project", ["Demo"])
    builder.raw('if(ENABLED)\n  message(STATUS "ok")\nendif()')

    assert parser.calls == 0
    document = builder.build(require_clean=True)
    assert parser.calls == 1
    assert len(document.command_views("project")) == 1
    assert len(document.command_views("message")) == 1


def test_cmake_builder_require_clean_controls_generation_diagnostics() -> None:
    builder = CMakeFileBuilder()
    builder.raw("if(FOO)\n")
    assert builder.build().diagnostics

    strict = CMakeFileBuilder()
    strict.raw("if(FOO)\n")
    with pytest.raises(ValueError, match="generated CMake source"):
        strict.build(require_clean=True)


def test_cmake_surrogateescaped_text_input_roundtrips_losslessly() -> None:
    source = b"# byte: \xff\nproject(Demo)\n"
    text = source.decode("utf-8", errors="surrogateescape")
    document = CMakeDocument.parse(text)
    assert document.render_bytes() == source


def test_a_builder_item_of_another_language_is_refused() -> None:
    from xr_syntax.core import SourceDraft

    builder = CMakeFileBuilder()
    with pytest.raises(ValueError, match="draft language"):
        builder._add(SourceDraft("cpp", "int x;\n"))


# ---------------------------------------------------------------------------
# User Code 区域
# User Code regions
# ---------------------------------------------------------------------------


def test_a_user_region_gives_its_name_and_body() -> None:
    document = CMakeDocument.parse(SAMPLE)
    regions = document.user_regions()
    assert [(region.kind, region.name) for region in regions] == [("user", "CompileOptions")]
    assert regions[0].body_text == "\nadd_compile_options(-Wall)\n"
    assert document.render_bytes()[regions[0].body_span.start : regions[0].body_span.end] == (
        b"\nadd_compile_options(-Wall)\n"
    )


def test_replacing_a_region_body_keeps_the_markers_and_the_rest() -> None:
    document = CMakeDocument.parse(SAMPLE)
    region = document.user_regions()[0]
    changed = document.replace_region_body(region, "\nadd_compile_options(-Wextra)\n")
    assert changed.render() == SAMPLE.replace("-Wall", "-Wextra")
    # 原快照不变，且新快照的诊断仍然可信。
    # The original snapshot is unchanged and the new snapshot's diagnostics stay trustworthy.
    assert document.render() == SAMPLE
    assert changed.tree.diagnostic_state == "clean"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_writing_back_a_body_keeps_the_line_endings_of_the_file(newline: str) -> None:
    source = SAMPLE.replace("\n", newline)
    document = CMakeDocument.parse(source)
    region = document.user_regions()[0]
    changed = document.replace_region_body(region, f"{newline}# nothing{newline}")
    assert changed.render() == source.replace(
        f"{newline}add_compile_options(-Wall){newline}", f"{newline}# nothing{newline}"
    )


def test_a_region_of_another_snapshot_is_refused() -> None:
    first = CMakeDocument.parse(SAMPLE)
    second = CMakeDocument.parse(SAMPLE)
    with pytest.raises(ValueError, match="different immutable syntax snapshot"):
        first.replace_region_body(second.user_regions()[0], "\n")


def test_a_forged_body_span_is_refused() -> None:
    document = CMakeDocument.parse(SAMPLE)
    region = document.user_regions()[0]
    forged = SourceRegion(
        region.kind,
        region.name,
        region.begin,
        region.end,
        SourceSpan(region.body_span.start, region.body_span.start),
        "",
    )
    with pytest.raises(ValueError, match="body span does not match"):
        document.replace_region_body(forged, "\n")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # 名字不匹配的 End 不弹栈，因此 Begin A / End B / End A 仍得到区域 A。
        # An End with another name does not pop, so Begin A / End B / End A still yields region A.
        (
            "# User Code Begin A\nx\n# User Code End B\n# User Code End A\n",
            [("A", "\nx\n# User Code End B\n")],
        ),
        # 嵌套按源码顺序配对；区域按 begin 的位置排序，因此外层在前。
        # Nesting pairs in source order; regions sort by the position of their begin, so the outer
        # one comes first.
        (
            "# User Code Begin A\n# User Code Begin B\ny\n# User Code End B\nz\n# User Code End A\n",
            [("A", "\n# User Code Begin B\ny\n# User Code End B\nz\n"), ("B", "\ny\n")],
        ),
        # 同名嵌套按栈配对。
        # A nested duplicate name pairs through the stack.
        (
            "# User Code Begin A\n# User Code Begin A\nx\n# User Code End A\n# User Code End A\n",
            [("A", "\n# User Code Begin A\nx\n# User Code End A\n"), ("A", "\nx\n")],
        ),
        # 未配对的 Begin 与孤立的 End 不产生区域。
        # An unpaired Begin and a lone End produce no region.
        ("# User Code Begin A\nx\n", []),
        ("# User Code End A\n", []),
        ("x\n# User Code End A\n", []),
        # 标记区分大小写。
        # The markers are case-sensitive.
        ("# USER CODE BEGIN A\nx\n# USER CODE END A\n", []),
    ],
)
def test_region_markers_pair_like_brackets(source: str, expected: list[tuple[str, str]]) -> None:
    document = CMakeDocument.parse(source)
    assert [(region.name, region.body_text) for region in document.user_regions()] == expected


def test_a_non_utf8_body_is_kept_byte_for_byte() -> None:
    source = b"# User Code Begin A\n\xff\xfe\n# User Code End A\n"
    document = CMakeDocument.parse(source)
    region = document.user_regions()[0]
    assert region.body_text == "\n\udcff\udcfe\n"
    changed = document.replace_region_body(region, region.body_text)
    assert changed.render_bytes() == source


# ---------------------------------------------------------------------------
# 语句与参数的编辑
# Statement and argument edits
# ---------------------------------------------------------------------------


def test_a_set_value_is_replaced_without_touching_the_rest_of_the_line() -> None:
    document = CMakeDocument.parse(SAMPLE)
    statement = document.top_level_statements()[0]
    changed = document.replace_argument(statement.arguments[1], "FreeRTOS")
    assert changed.render() == SAMPLE.replace(
        "set(LIBXR_SYSTEM None)", "set(LIBXR_SYSTEM FreeRTOS)"
    )
    # 命令名、括号和两侧空白都不动。
    # The command name, the parentheses and the whitespace around them stay.
    odd = CMakeDocument.parse("set(  LIBXR_SYSTEM   None  )\n")
    odd_statement = odd.top_level_statements()[0]
    assert odd.replace_argument(odd_statement.arguments[1], "X").render() == (
        "set(  LIBXR_SYSTEM   X  )\n"
    )


def test_a_quoted_value_gets_the_quoting_the_new_text_needs() -> None:
    document = CMakeDocument.parse('set(LIBXR_USER_SOURCES_GLOB "old")\n')
    statement = document.top_level_statements()[0]
    changed = document.replace_argument(statement.arguments[1], '"a b"')
    assert changed.render() == 'set(LIBXR_USER_SOURCES_GLOB "a b")\n'


def test_a_statement_without_a_value_is_replaced_whole() -> None:
    # set(LIBXR_SYSTEM ) 没有值：原地写入值，不在前面另插一行——前面插一行会让变量最后等于后面的
    # 空值。
    # set(LIBXR_SYSTEM ) has no value: the value is written in place instead of inserting a line
    # before it, which would leave the variable empty again after it.
    document = CMakeDocument.parse("set(LIBXR_SYSTEM )\nset(A 1)\n")
    changed = document.replace_statement(
        document.top_level_statements()[0], "set(LIBXR_SYSTEM None)\n"
    )
    assert changed.render() == "set(LIBXR_SYSTEM None)\nset(A 1)\n"


def test_a_statement_is_inserted_after_the_whole_line_of_the_other_statement() -> None:
    # 插在原语句所在的整行之后：行尾注释留在原行，不跟着新语句走。
    # The statement goes after the whole line of the other one: a comment at the end of that line
    # stays there and does not move with the new statement.
    document = CMakeDocument.parse(SAMPLE)
    system = document.top_level_statements()[0]
    changed = document.insert_after(system, "set(LIBXR_DRIVER st)\n")
    assert changed.render() == SAMPLE.replace(
        "set(LIBXR_SYSTEM None)\n", "set(LIBXR_SYSTEM None)\nset(LIBXR_DRIVER st)\n"
    )


def test_a_statement_is_inserted_after_a_line_that_ends_with_a_comment() -> None:
    document = CMakeDocument.parse("set(LIBXR_SYSTEM None) # rtos\nset(A 1)\n")
    system = document.top_level_statements()[0]
    changed = document.insert_after(system, "set(LIBXR_DRIVER st)\n")
    assert changed.render() == "set(LIBXR_SYSTEM None) # rtos\nset(LIBXR_DRIVER st)\nset(A 1)\n"


def test_inserting_uses_the_line_ending_of_the_document() -> None:
    document = CMakeDocument.parse("set(A 1)\r\nset(B 2)\r\n")
    changed = document.insert_after(document.top_level_statements()[0], "set(C 3)\n")
    assert changed.render() == "set(A 1)\r\nset(C 3)\r\nset(B 2)\r\n"


def test_inserting_keeps_the_leading_comments_of_the_new_statement() -> None:
    document = CMakeDocument.parse(SAMPLE)
    system = document.top_level_statements()[0]
    changed = document.insert_after(system, '# a comment\nset(LIBXR_USER_SOURCES_GLOB "")\n')
    assert changed.render() == SAMPLE.replace(
        "set(LIBXR_SYSTEM None)\n",
        'set(LIBXR_SYSTEM None)\n# a comment\nset(LIBXR_USER_SOURCES_GLOB "")\n',
    )


def test_inserting_refuses_text_that_is_not_exactly_one_statement() -> None:
    document = CMakeDocument.parse(SAMPLE)
    system = document.top_level_statements()[0]
    for text in ("", "set(A 1)\nset(B 2)\n"):
        with pytest.raises(ValueError, match="exactly one top-level CMake statement"):
            document.insert_after(system, text)
        with pytest.raises(ValueError, match="exactly one top-level CMake statement"):
            document.replace_statement(system, text)


# 插入点固定在被插语句所在那一行的换行之后：后面有几个空行、有没有行尾注释、有没有行尾空格、
# 是 LF 还是 CRLF 都不改变结果。生成器补写 set(LIBXR_DRIVER st) 与 XROBOT_MODULES_DIR 时依赖这一点，
# 写出的文件因此总是 CMake 能读的。
# The insertion point is fixed right after the line ending of the statement's own line: how many blank
# lines follow, whether the line carries a trailing comment or trailing spaces, and whether the file
# uses LF or CRLF change nothing. The generator relies on it when it adds set(LIBXR_DRIVER st) and
# XROBOT_MODULES_DIR, so the file it writes is always one CMake can read.
INSERT_CASES = [
    ("blank line after", "set(A 1)\n\nset(B 2)\n", "set(A 1)\nset(C 3)\n\nset(B 2)\n"),
    (
        "trailing comment and a blank line",
        "set(A 1) # d\n\nset(B 2)\n",
        "set(A 1) # d\nset(C 3)\n\nset(B 2)\n",
    ),
    ("blank line after the last setting", "set(A 1)\n\n# note\n", "set(A 1)\nset(C 3)\n\n# note\n"),
    (
        "trailing spaces and a blank line",
        "set(A 1)  \n\nset(B 2)\n",
        "set(A 1)  \nset(C 3)\n\nset(B 2)\n",
    ),
    (
        "CRLF and a blank line",
        "set(A 1)\r\n\r\nset(B 2)\r\n",
        "set(A 1)\r\nset(C 3)\r\n\r\nset(B 2)\r\n",
    ),
]


@pytest.mark.parametrize(
    "name, source, expected", INSERT_CASES, ids=[case[0] for case in INSERT_CASES]
)
def test_inserting_goes_after_the_line_ending_of_the_statement_line(
    name: str, source: str, expected: str
) -> None:
    del name
    document = CMakeDocument.parse(source)
    changed = document.insert_after(document.top_level_statements()[0], "set(C 3)\n")
    assert changed.render() == expected
    assert not CMakeParser().parse(changed.render_bytes()).diagnostics


@pytest.mark.parametrize(
    "name, source, expected", INSERT_CASES, ids=[case[0] for case in INSERT_CASES]
)
def test_an_inserted_statement_keeps_the_file_readable_by_cmake(
    name: str, source: str, expected: str
) -> None:
    # 写出的文件必须是 CMake 能读的：同一行出现两条命令是 CMake 的解析错误。
    # The written file must be one CMake can read: two commands on one line are a CMake parse error.
    del name, expected
    document = CMakeDocument.parse(source)
    changed = document.insert_after(document.top_level_statements()[0], "set(C 3)\n")
    assert_cmake_accepts(changed.render())


def assert_cmake_accepts(text: str) -> None:
    """让真正的 cmake 解析这段源码；没有安装 cmake 时跳过。
    Let the real cmake parse this source; skipped when cmake is not installed.
    """
    executable = shutil.which("cmake")
    if executable is None:
        pytest.skip("cmake is not installed")
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "CMakeLists.txt"
        script.write_text(text, encoding="utf-8", newline="")
        completed = subprocess.run(
            [executable, "-P", str(script)], capture_output=True, text=True, check=False
        )
    assert completed.returncode == 0, completed.stderr


def test_two_commands_on_one_line_are_diagnosed() -> None:
    # CMake 要求每条命令后面换行；同一行出现两条命令时 xr-syntax 报诊断，写文件前的校验因此能拦住它。
    # CMake requires a line ending after every command; two commands on one line are diagnosed, which
    # is what lets the check before a write refuse such a file.
    source = b"set(A 1) set(B 2)\n"
    document = CMakeDocument.parse(source)
    assert [
        (item.message, item.start_point.row, item.start_point.column)
        for item in document.diagnostics
    ] == [("expected a newline before this CMake command", 0, 9)]
    assert document.render_bytes() == source


@pytest.mark.parametrize(
    "source",
    [
        b"set(A 1) #[[ c\n ]] set(B 2)\n",
        b"#[[a]] set(A 1)\n",
        b'message(STATUS "x")\n#[[c]]message(STATUS y)\n',
        b"set(A 1)\r\n#[==[ c\r\n ]==] set(B 2)\r\n",
    ],
)
def test_a_command_after_a_bracket_comment_on_its_line_is_diagnosed(source: bytes) -> None:
    # bracket 注释内部的换行不结束一行；cmake 对这些输入都报 "Expected a newline"。
    # A newline inside a bracket comment does not end the line; cmake reports "Expected a
    # newline" for each of these inputs.
    document = CMakeDocument.parse(source)
    assert [item.message for item in document.diagnostics] == [
        "expected a newline before this CMake command"
    ]
    assert document.render_bytes() == source


def test_a_comment_after_a_command_is_not_a_second_command() -> None:
    # 命令后面的行注释与 bracket 注释属于这一行；bracket 注释还可以跨行。
    # A line comment and a bracket comment after a command belong to that line, and a bracket
    # comment may span lines.
    for source in (
        b"set(A 1) # c\nset(B 2)\n",
        b"set(A 1) #[[ c ]]\nset(B 2)\n",
        b"set(A 1) #[[ c\nd ]]\nset(B 2)\n",
        b"if(A)\n  x()\nendif() # c\n",
        b"set(A 1\n  2)\nset(B 2)\n",
        b"  \tset(A 1)\r\n#[[ c ]]\r\nset(B 2)",
        b"\xef\xbb\xbfset(A 1)\n",
    ):
        document = CMakeDocument.parse(source)
        assert not document.diagnostics
        assert document.render_bytes() == source


def test_a_block_on_one_line_is_diagnosed_like_any_other_command() -> None:
    # if() 也是命令：CMake 同样要求它后面换行。
    # if() is a command too, and CMake requires a line ending after it as well.
    document = CMakeDocument.parse(b"if(FOO) set(A 1) endif()\n")
    assert len(document.diagnostics) == 2
    assert {item.start_point.column for item in document.diagnostics} == {8, 17}


def test_a_command_is_removed_with_its_line() -> None:
    document = CMakeDocument.parse(SAMPLE)
    driver = document.command_views("set")[1]
    changed = document.remove_command(driver)
    assert changed.render() == SAMPLE.replace("set(LIBXR_DRIVER st)\n", "")


def test_a_command_is_removed_with_the_comment_at_the_end_of_its_line() -> None:
    # 独占一行的命令连同行尾注释整行删掉，与旧实现一致。
    # A command that has the line to itself takes the comment at the end of that line with it, as the
    # earlier implementation did.
    document = CMakeDocument.parse("set(MOD 1) # modules\nset(KEEP 1)\n")
    changed = document.remove_command(document.command_views("set")[0])
    assert changed.render() == "set(KEEP 1)\n"


def test_a_command_inside_a_block_is_removed_with_its_line_and_indentation() -> None:
    source = 'if(FOO)\n    set(XROBOT_MODULES_DIR "x")\n    set(KEEP 1)\nendif()\n'
    document = CMakeDocument.parse(source)
    target = next(
        view
        for view in document.command_views("set")
        if view.arguments and view.arguments[0].text == "XROBOT_MODULES_DIR"
    )
    changed = document.remove_command(target)
    assert changed.render() == "if(FOO)\n    set(KEEP 1)\nendif()\n"


@pytest.mark.parametrize(
    ("source", "index"),
    [
        ("set(A 1) set(B 2) set(C 3)\n", 1),
        ("set(A 1) set(B 2) set(C 3)\n", 0),
        ("if(FOO) set(X 1) endif()\n", 0),
        ("set(MOD 1) #[[ c ]] set(KEEP 1)\n", 0),
    ],
)
def test_a_command_that_shares_its_line_is_not_removed(source: str, index: int) -> None:
    # CMake 不允许同一行有两条命令，解析时已报诊断；删除只处理独占一行的命令。
    # CMake allows no two commands on one line and parsing already reports it; removal only handles
    # a command that has its line to itself.
    document = CMakeDocument.parse(source)
    assert document.diagnostics
    with pytest.raises(ValueError, match="has its line to itself"):
        document.remove_command(document.command_views("set")[index])


def test_a_command_with_a_multi_line_bracket_comment_is_removed_with_it() -> None:
    # 跨行的 bracket 注释属于命令所在的那一行，连同它后面的换行一起删掉。
    # A bracket comment spanning lines belongs to the line of the command and goes with the newline
    # after it.
    document = CMakeDocument.parse("set(A 1)\n  set(MOD 1) #[[ multi\nline ]]\nset(B 2)\n")
    changed = document.remove_command(document.command_views("set")[1])
    assert changed.render() == "set(A 1)\nset(B 2)\n"


def test_a_command_whose_line_has_no_newline_is_removed_with_its_line() -> None:
    document = CMakeDocument.parse("set(KEEP 1)\nset(MOD 1)")
    changed = document.remove_command(document.command_views("set")[1])
    assert changed.render() == "set(KEEP 1)\n"


def test_a_multi_line_command_is_removed_with_all_of_its_lines() -> None:
    document = CMakeDocument.parse('set(MOD\n    "x")\nset(KEEP 1)\n')
    changed = document.remove_command(document.command_views("set")[0])
    assert changed.render() == "set(KEEP 1)\n"


def test_removing_uses_the_line_ending_of_the_document() -> None:
    document = CMakeDocument.parse("set(A 1)\r\nset(MOD 1)\r\nset(B 2)\r\n")
    changed = document.remove_command(document.command_views("set")[1])
    assert changed.render() == "set(A 1)\r\nset(B 2)\r\n"


def test_a_low_level_edit_marks_the_diagnostics_unknown() -> None:
    document = CMakeDocument.parse(SAMPLE)
    assert document.tree.diagnostic_state == "clean"
    driver = document.command_views("set")[1]
    changed = document.replace_argument(driver.arguments[1], "hpm")
    assert changed.tree.diagnostic_state == "unknown"
    assert changed.diagnostics == ()
    assert changed.render() == SAMPLE.replace("set(LIBXR_DRIVER st)", "set(LIBXR_DRIVER hpm)")


def test_inserting_and_removing_lines_parse_again() -> None:
    # 按行插入和删除直接改源码再重新解析，编辑后的诊断可信。
    # Inserting and removing lines edit the source and parse it again, so the diagnostics after the
    # edit can be trusted.
    document = CMakeDocument.parse(SAMPLE)
    removed = document.remove_command(document.command_views("set")[1])
    assert removed.tree.diagnostic_state == "clean"
    inserted = document.insert_after(document.top_level_statements()[0], "set(C 3)\n")
    assert inserted.tree.diagnostic_state == "clean"


def test_the_cmake_builder_writes_a_user_region() -> None:
    builder = CMakeFileBuilder()
    builder.raw("set(A 1)")
    builder.user_region("CompileOptions")
    document = builder.build()
    assert document.render() == (
        "set(A 1)\n# User Code Begin CompileOptions\n# User Code End CompileOptions\n"
    )
    assert [(region.name, region.body_text) for region in document.user_regions()] == [
        ("CompileOptions", "\n")
    ]


def test_a_cmake_user_region_body_round_trips_through_the_builder() -> None:
    body = "\nadd_compile_options(-Wall)\n"
    builder = CMakeFileBuilder()
    builder.user_region("CompileOptions", body)
    document = builder.build()
    assert document.render() == (
        "# User Code Begin CompileOptions" + body + "# User Code End CompileOptions\n"
    )
    again = CMakeFileBuilder()
    again.user_region("CompileOptions", document.user_regions()[0].body_text)
    assert again.build().render() == document.render()


def test_a_trailing_empty_chunk_stays_a_blank_line() -> None:
    # 末尾的空 raw 是一个空行：build() 原样拼接每个片段，不做任何增删。空模块列表写出的
    # Modules/CMakeLists.txt 就是这样两行。
    # A trailing empty chunk is one blank line: build() joins every chunk as written and adds or
    # drops nothing. The Modules/CMakeLists.txt of an empty module list is exactly these two lines.
    builder = CMakeFileBuilder()
    builder.comment("Generated by `xrobot setup` from xrobot.lock; do not edit or commit.")
    builder.raw("")
    assert (
        builder.build().render()
        == "# Generated by `xrobot setup` from xrobot.lock; do not edit or commit.\n\n"
    )


def test_an_unterminated_block_reports_the_command_that_opens_it() -> None:
    document = CMakeDocument.parse("set(A 1)\nif(B)\nset(C 1)\n")
    # 位置是 if( 那一行，不是文件开头。
    # The position is the line of the if( and not the start of the file.
    assert [(d.message, d.start_point.row, d.start_point.column) for d in document.diagnostics] == [
        ("unterminated CMake block: endif is missing", 1, 0)
    ]
    assert document.render_bytes() == b"set(A 1)\nif(B)\nset(C 1)\n"


def test_a_block_command_gives_a_block_node_like_the_others() -> None:
    source = b"function(f)\nendfunction()\nblock()\n  set(LIBXR_DRIVER st)\nendblock()\n"
    document = CMakeDocument.parse(source)
    assert [
        node.kind
        for node in document.root.descendants(
            kinds={
                "if_condition",
                "foreach_loop",
                "while_loop",
                "function_def",
                "macro_def",
                "block",
            }
        )
    ] == ["function_def", "block"]
    assert document.render_bytes() == source
    # 两条块语句都出现在 top_level_statements() 里。
    # Both block statements appear in top_level_statements().
    assert [statement.name for statement in document.top_level_statements()] == [
        "function",
        "block",
    ]


def test_an_unterminated_block_reports_one_diagnostic_however_deep_it_is_nested() -> None:
    # 一层套一层的未闭合块只报最外面那一个，不重复。
    # A stack of unterminated blocks reports only the outermost one, once.
    document = CMakeDocument.parse("if(A)\nforeach(i IN LISTS L)\nset(B 1)\n")
    assert len(document.diagnostics) == 1
    assert document.diagnostics[0].start_point.row == 0
    assert document.diagnostics[0].message.endswith("endif is missing")


def test_one_problem_is_reported_once() -> None:
    # 未闭合的引号让扫描失败，也让命令本身没有结束：只记引号那一条。
    # An unterminated quote fails that argument and leaves the command unterminated too: only the
    # quote is reported.
    document = CMakeDocument.parse('set(A "x)\n')
    assert [d.message for d in document.diagnostics] == [
        "unterminated quoted argument",
        "unterminated CMake command",
    ]
