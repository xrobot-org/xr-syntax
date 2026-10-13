"""提供只在 build() 边界解析一次的 CMake 文件构建器。
CMake file builder that parses once at the build() boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from xr_syntax.cmake.document import CMakeDocument
from xr_syntax.cmake.parser import CMakeParser
from xr_syntax.core import SourceDraft, SyntaxFragment

# CMake 的 User Code 标记；与 C++ 侧同样区分大小写。
# The CMake User Code markers; case-sensitive exactly like the C++ ones.
USER_REGION_BEGIN = "# User Code Begin {name}"
USER_REGION_END = "# User Code End {name}"


@dataclass
class CMakeFileBuilder:
    """累积 CMake source draft，并在 build() 时统一解析。
    Accumulate CMake source drafts and parse the complete file once in build().
    """

    parser: CMakeParser = field(default_factory=CMakeParser)
    items: list[SourceDraft | SyntaxFragment] = field(default_factory=list)

    def _add(self, item: SourceDraft | SyntaxFragment) -> SourceDraft | SyntaxFragment:
        """追加同语言 draft 或已验证 fragment。
        Append a same-language draft or validated fragment.
        """
        self._source_of(item)
        self.items.append(item)
        return item

    def raw(self, source: str) -> SourceDraft:
        """追加原始 CMake source draft，留到最终 parse 统一验证。
        Append raw CMake source for validation by the final parse.

        source 是一个完整的片段：已经以换行结束时原样追加，否则补一个换行，空字符串因此是空行。
        source is a complete chunk: it is appended as written when it already ends with a line ending
        and gets one otherwise, so an empty string is one blank line.
        """
        draft = SourceDraft("cmake", _line(source))
        self._add(draft)
        return draft

    def comment(self, text: str) -> SourceDraft:
        """追加一行 CMake 注释 draft。
        Append one CMake comment draft.
        """
        draft = SourceDraft("cmake", _line(f"# {text}"))
        self._add(draft)
        return draft

    def command(self, name: str, arguments: Iterable[str] = ()) -> SourceDraft:
        """追加一条 CMake 命令 draft：命令名和参数按调用方给出的形式写成一行。
        Append one CMake command draft: the command name and its arguments go on one line exactly as
        the caller gives them.

        生成的 CMake 没有排版工具，折行只会让输出随名字长度变化，因此这里不折行。
        Generated CMake has no formatter, so breaking a line would only make the output depend on how
        long a name happens to be; nothing here breaks a line.
        """
        draft = SourceDraft("cmake", _line(f"{name}(" + " ".join(arguments) + ")"))
        self._add(draft)
        return draft

    def user_region(self, name: str, body: str | None = None) -> SourceDraft:
        """追加一个 User Code Begin/End 区域 draft。
        Append one User Code Begin/End region draft.

        区域体是两条标记之间的原文，自己带换行：把已有文件某个区域的 body_text 原样交回来，得到的
        就是同一段字节。body 为 None 时是一条换行，两条标记各占一行。
        The body is the exact source between the two markers and carries its own line endings: passing
        the body_text of a region of an existing file back produces the same bytes. Without a body
        there is one newline, so the two markers take a line each.
        """
        draft = SourceDraft(
            "cmake",
            _line(
                USER_REGION_BEGIN.format(name=name)
                + ("\n" if body is None else body)
                + USER_REGION_END.format(name=name)
            ),
        )
        self._add(draft)
        return draft

    def build(self, *, require_clean: bool = False) -> CMakeDocument:
        """把全部片段原样拼成整份源码并只 parse 一次；可要求生成结果没有 diagnostics。
        Join every chunk as written and parse the complete file once; optionally require a clean
        result.

        拼接不做任何增删，每个片段自己带换行，因此末尾的空片段就是一个空行。
        The join adds and drops nothing: every chunk carries its own line endings, so a trailing empty
        chunk is one blank line.

        Raises:
            ValueError: require_clean 为真而生成结果有解析诊断。
                require_clean is set and the generated source has parse diagnostics.
        """
        source = "".join(self._source_of(item) for item in self.items)
        document = CMakeDocument.parse(source, parser=self.parser)
        if require_clean and document.diagnostics:
            messages = "; ".join(item.message for item in document.diagnostics)
            raise ValueError(f"generated CMake source has parser diagnostics: {messages}")
        return document

    def _source_of(self, item: SourceDraft | SyntaxFragment) -> str:
        """返回同语言 draft/fragment 的源码文本。
        Return source text from a same-language draft or syntax fragment.

        Raises:
            ValueError: draft 或 fragment 的语言不是 cmake。
                The draft or fragment is not tagged as cmake.
        """
        if isinstance(item, SourceDraft):
            return item.source_for("cmake")
        item.green_for("cmake")
        return item.render()


def _line(source: str) -> str:
    """片段的一行：已经以换行结束时原样返回，否则补一个换行。
    One line of a chunk: returned as written when it already ends with a line ending, and given one
    otherwise.
    """
    return source if source.endswith("\n") else source + "\n"
