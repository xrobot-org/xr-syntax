"""提供只在 build() 边界解析一次的 CMake 文件构建器。
CMake file builder that parses once at the build() boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from xr_syntax.core import SourceDraft, SyntaxFragment

from .document import CMakeDocument
from .factory import CMakeFactory

# ---------------------------------------------------------------------------
# 模块实现：提供只在 build() 边界解析一次的 CMake 文件构建器。
# ---------------------------------------------------------------------------


@dataclass
class CMakeFileBuilder:
    """累积 CMake source draft，并在 build() 时统一解析。
    Accumulate CMake source drafts and parse the complete file once in build().
    """

    factory: CMakeFactory = field(default_factory=CMakeFactory)
    items: list[SourceDraft | SyntaxFragment] = field(default_factory=list)

    def add(self, item: SourceDraft | SyntaxFragment) -> SourceDraft | SyntaxFragment:
        """追加同语言 draft 或已验证 fragment。
        Append a same-language draft or validated fragment.
        """
        self.factory._source_of(item)
        self.items.append(item)
        return item

    def raw(self, source: str) -> SourceDraft:
        """追加原始 CMake source draft。
        Append raw CMake source for validation by the final parse.
        """
        draft = SourceDraft(self.factory.language, source)
        self.add(draft)
        return draft

    def comment(self, text: str) -> SourceDraft:
        """追加 CMake 注释 draft。
        Append one CMake comment draft.
        """
        draft = self.factory._comment_draft(text)
        self.add(draft)
        return draft

    def command(
        self,
        name: str,
        arguments: Iterable[str] = (),
    ) -> SourceDraft:
        """追加 CMake 命令 draft。
        Append one CMake command draft.
        """
        draft = self.factory._command_draft(name, arguments)
        self.add(draft)
        return draft

    def if_block(
        self,
        condition: Iterable[str],
        body: Iterable[SourceDraft | SyntaxFragment],
    ) -> SourceDraft:
        """追加完整的 if()/endif() 条件块 draft。
        Append one complete if()/endif() block draft.
        """
        draft = self.factory._if_block_draft(condition, body)
        self.add(draft)
        return draft

    def build(self, *, require_clean: bool = False) -> CMakeDocument:
        """渲染全部源码并只 parse 一次；可要求生成结果没有 diagnostics。
        Parse the complete generated file once and optionally require a clean result.
        """
        rendered = [self.factory._source_of(item).rstrip("\r\n") for item in self.items]
        source = "\n".join(rendered)
        if source and not source.endswith("\n"):
            source += "\n"
        document = CMakeDocument.parse(source, parser=self.factory.parser)
        if require_clean and document.diagnostics:
            messages = "; ".join(item.message for item in document.diagnostics)
            raise ValueError(f"generated CMake source has parser diagnostics: {messages}")
        return document
