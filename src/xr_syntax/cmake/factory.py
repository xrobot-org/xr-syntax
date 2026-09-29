"""提供 CMake 命令、注释和条件块的 parser-backed 片段工厂。
Factories for parser-backed CMake source fragments.
"""

from __future__ import annotations

from collections.abc import Iterable

from xr_syntax.core import GreenToken, SourceDraft, SyntaxElement, SyntaxFragment, SyntaxNode
from xr_syntax.format import Group, Indent, concat, join, line, render, softline

from .document import CMakeDocument
from .parser import CMakeParser

# ---------------------------------------------------------------------------
# 模块实现：提供 CMake 命令、注释和条件块的 parser-backed 片段工厂。
# ---------------------------------------------------------------------------


class CMakeFactory:
    """创建带 CMake 语言归属的 parser-backed 片段。
    Create parser-backed fragments carrying explicit CMake language provenance.
    """

    language = "cmake"

    def __init__(
        self,
        parser: CMakeParser | None = None,
        *,
        width: int = 100,
    ) -> None:
        """初始化 CMake 片段工厂并保存布局宽度。
        Initialize the CMake fragment factory and store its layout width.
        """
        self.parser = parser or CMakeParser()
        self.width = width

    def raw(self, source: str) -> SyntaxFragment:
        """创建显式 opaque 的原始 CMake 片段。
        Create an explicit opaque CMake source fragment.
        """
        return SyntaxFragment(
            self.language,
            GreenToken("raw", source, named=True),
            opaque=True,
        )

    def comment(self, text: str) -> SyntaxFragment:
        """创建一条 CMake 行注释片段。
        Create one CMake line-comment fragment.
        """
        draft = self._comment_draft(text)
        return self._fragment(self._first_element(draft.source, "comment"))

    def command(
        self,
        name: str,
        arguments: Iterable[str] = (),
    ) -> SyntaxFragment:
        """按给定宽度创建一个 CMake 命令片段。
        Create one CMake command fragment with width-aware argument layout.
        """
        draft = self._command_draft(name, arguments)
        return self._fragment(self._first_node(draft.source, "normal_command"))

    def if_block(
        self,
        condition: Iterable[str],
        body: Iterable[SyntaxFragment],
    ) -> SyntaxFragment:
        """由条件和 body 片段创建 if()/endif() 块。
        Create a complete if()/endif() block from condition and body fragments.
        """
        draft = self._if_block_draft(condition, body)
        return self._fragment(self._first_node(draft.source, "if_condition"))

    def _comment_draft(self, text: str) -> SourceDraft:
        """生成尚未解析的 CMake 注释源码。
        Build unparsed source for one CMake comment.
        """
        return SourceDraft(self.language, f"# {text}")

    def _command_draft(
        self,
        name: str,
        arguments: Iterable[str] = (),
    ) -> SourceDraft:
        """通过布局 IR 生成尚未解析的 CMake 命令源码。
        Render one unparsed CMake command through the layout IR.
        """
        document = Group(
            concat(
                name,
                "(",
                Indent(
                    concat(
                        softline,
                        join(line, tuple(arguments)),
                    )
                ),
                softline,
                ")",
            )
        )
        return SourceDraft(self.language, render(document, width=self.width))

    def _if_block_draft(
        self,
        condition: Iterable[str],
        body: Iterable[SourceDraft | SyntaxFragment],
    ) -> SourceDraft:
        """生成尚未解析的 if()/endif() 块源码。
        Build unparsed source for one if()/endif() block.
        """
        opening = self._command_draft("if", condition).source
        body_text = "\n".join(self._source_of(item).rstrip("\r\n") for item in body)
        rendered = [opening]
        if body_text:
            rendered.append(body_text)
        rendered.append("endif()")
        return SourceDraft(self.language, "\n".join(rendered))

    def _source_of(self, item: SourceDraft | SyntaxFragment) -> str:
        """返回同语言 draft/fragment 的源码文本。
        Return source text from a same-language draft or syntax fragment.
        """
        if isinstance(item, SourceDraft):
            return item.source_for(self.language)
        item.green_for(self.language)
        return item.render()

    def _fragment(self, element: SyntaxElement) -> SyntaxFragment:
        """把解析元素包装成 CMake fragment。
        Wrap one parsed syntax element as a CMake fragment.
        """
        return SyntaxFragment(self.language, element.green)

    def _first_element(self, source: str, kind: str) -> SyntaxElement:
        """返回临时解析结果中指定 kind 的第一个元素。
        Return the first parsed syntax element of the requested kind.
        """
        document = CMakeDocument.parse(source, parser=self.parser)
        elements = document.elements(kind)
        if not elements:
            raise ValueError(f"generated CMake fragment did not contain {kind}")
        return elements[0]

    def _first_node(self, source: str, kind: str) -> SyntaxNode:
        """返回临时解析结果中指定 kind 的第一个节点。
        Return the first parsed node of the requested kind.
        """
        document = CMakeDocument.parse(source, parser=self.parser)
        nodes = document.nodes(kind)
        if not nodes:
            raise ValueError(f"generated CMake fragment did not contain {kind}")
        return nodes[0]
