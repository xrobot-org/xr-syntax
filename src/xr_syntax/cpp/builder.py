"""提供 C++ 文件的批量源码构建器：在 build() 边界只解析一次。
Batch C++ file builder that parses the complete file once at the build() boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xr_syntax.core import SourceDraft, SyntaxFragment
from xr_syntax.cpp.document import CppDocument
from xr_syntax.cpp.parser import CppParser

# 生成文件里 clang-format 区域的标记；区域体由调用方给出，逐字保留。
# The markers of the clang-format region of a generated file; the body comes from the caller and is
# kept verbatim.
CLANG_FORMAT_OFF = "// clang-format off"
CLANG_FORMAT_ON = "// clang-format on"


@dataclass
class CppFileBuilder:
    """累积 C++ source draft，并在 build() 时只解析完整文件一次。
    Accumulate C++ source drafts and parse the complete file once in build().

    header 为真时先放入一条 #pragma once。每一行都已由调用方排版（生成语句用
    xr_syntax.format 的排版函数），这里只负责顺序、区域的标记和最终的整文件校验。
    With header, a #pragma once goes in first. The caller has already laid out every line (generated
    statements go through the layout functions of xr_syntax.format); this only keeps the order, the
    region markers and the final whole-file check.
    """

    header: bool = False
    items: list[SourceDraft | SyntaxFragment] = field(default_factory=list)
    parser: CppParser = field(default_factory=CppParser)

    def __post_init__(self) -> None:
        """在头文件模式下加入 pragma once draft。
        Add a pragma-once draft when building a header.
        """
        if self.header:
            self.directive("#pragma once")

    def _add(self, item: SourceDraft | SyntaxFragment) -> SourceDraft | SyntaxFragment:
        """追加同语言 draft 或已验证 fragment。
        Append a same-language draft or validated fragment.

        Raises:
            ValueError: draft 或 fragment 的语言不是 cpp。
                The draft or fragment is not tagged as cpp.
        """
        self._source_of(item)
        self.items.append(item)
        return item

    def directive(self, source: str) -> SourceDraft:
        """追加一条预处理指令 draft。
        Append one preprocessor-directive draft.
        """
        draft = SourceDraft("cpp", source.rstrip() + "\n")
        self._add(draft)
        return draft

    def include(self, header: str, *, system: bool = False) -> SourceDraft:
        """追加一条 include draft；system 为真时写成 <...>，否则写成 "..."。
        Append one include draft; system writes <...> and otherwise "..." is written.
        """
        delimiters = ("<", ">") if system else ('"', '"')
        draft = SourceDraft("cpp", f"#include {delimiters[0]}{header}{delimiters[1]}\n")
        self._add(draft)
        return draft

    def raw(self, source: str) -> SourceDraft:
        """追加原始 source draft，留到最终 parse 统一验证。
        Append raw source for validation by the final parse.

        source 是一个完整的片段：已经以换行结束时原样追加，否则补一个换行，空字符串因此是空行。
        source is a complete chunk: it is appended as written when it already ends with a line ending
        and gets one otherwise, so an empty string is one blank line.
        """
        draft = SourceDraft("cpp", _line(source))
        self._add(draft)
        return draft

    def format_region(self, body: str | None = None) -> SourceDraft:
        """追加 clang-format off/on 区域 draft。
        Append one clang-format off/on region draft.
        """
        draft = self._region_draft(CLANG_FORMAT_OFF, CLANG_FORMAT_ON, body)
        self._add(draft)
        return draft

    def build(self, *, require_clean: bool = False) -> CppDocument:
        """把全部片段原样拼成整份源码并只解析一次；可要求生成结果没有 diagnostics。
        Join every chunk as written and parse the complete file once; optionally require a clean
        result.

        拼接不做任何增删，每个片段自己带换行，因此末尾的空片段就是一个空行。
        The join adds and drops nothing: every chunk carries its own line endings, so a trailing empty
        chunk is one blank line.

        require_clean 只在生成文件不含用户手写代码时使用：User Code 区域里的内容不受生成器控制，
        它自身的诊断不该让生成失败。
        require_clean belongs to files without hand-written user code: the contents of a User Code
        region are outside the generator's control and their diagnostics must not fail a generation.

        Raises:
            ValueError: require_clean 为真而生成结果有解析诊断。
                require_clean is set and the generated source has parse diagnostics.
        """
        source = "".join(self._source_of(item) for item in self.items)
        # 生成结束后只在这里做一次完整 parse，确保 builder 输出和读取已有源码使用完全相同的模型。
        # The one complete parse happens here, so the builder output and reading existing source use
        # exactly the same model.
        document = CppDocument.parse(source, parser=self.parser)
        if require_clean and document.diagnostics:
            messages = "; ".join(item.message for item in document.diagnostics)
            raise ValueError(f"generated C++ source has parser diagnostics: {messages}")
        return document

    def _region_draft(self, begin: str, end: str, body: str | None) -> SourceDraft:
        """由标记和区域体拼出一个保护区域。
        Build one protected region from its markers and body.

        区域体是两条标记之间的原文，自己带换行：把已有文件某个区域的 body_text 原样交回来，得到的
        就是同一段字节。body 为 None 时是一条换行，两条标记各占一行。
        The body is the exact source between the two markers and carries its own line endings: passing
        the body_text of a region of an existing file back produces the same bytes. Without a body
        there is one newline, so the two markers take a line each.
        """
        return SourceDraft("cpp", _line(begin + ("\n" if body is None else body) + end))

    def _source_of(self, item: SourceDraft | SyntaxFragment) -> str:
        """返回同语言 draft/fragment 的源码文本。
        Return source text from a same-language draft or syntax fragment.

        Raises:
            ValueError: draft 或 fragment 的语言不是 cpp。
                The draft or fragment is not tagged as cpp.
        """
        if isinstance(item, SourceDraft):
            return item.source_for("cpp")
        item.green_for("cpp")
        return item.render()


def _line(source: str) -> str:
    """片段的一行：已经以换行结束时原样返回，否则补一个换行。
    One line of a chunk: returned as written when it already ends with a line ending, and given one
    otherwise.
    """
    return source if source.endswith("\n") else source + "\n"
