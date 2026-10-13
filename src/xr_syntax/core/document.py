"""定义语言无关的 SyntaxDocument：一个语法树快照、它的查询和成对注释区域的编辑。
The language-neutral SyntaxDocument: one syntax-tree snapshot, its queries and the editing of
paired comment regions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, TypeVar

from xr_syntax.core.diagnostic import Diagnostic
from xr_syntax.core.red import SyntaxElement, SyntaxNode
from xr_syntax.core.span import SourceSpan
from xr_syntax.core.text import encode_source
from xr_syntax.core.tree import SyntaxTree


class SyntaxParserProtocol(Protocol):
    """SyntaxDocument 需要的解析器接口。
    The parser interface SyntaxDocument needs.
    """

    def parse(
        self,
        source: str | bytes,
        *,
        source_name: str | None = None,
    ) -> SyntaxTree:
        """把源码文本或字节解析为一个不可变 SyntaxTree 快照。
        Parse text or bytes into one immutable syntax-tree snapshot.
        """
        ...


_DocumentT = TypeVar("_DocumentT", bound="SyntaxDocument")


@dataclass(frozen=True)
class SourceRegion:
    """由成对注释标记界定的源码区域，例如 User Code、clang-format 或 NOLINT。
    A source region delimited by paired comment markers, such as User Code, clang-format or
    NOLINT.

    begin 与 end 是两条标记注释元素；body_span 是它们之间的半开字节范围，body_text 是这段
    源码文本（非 UTF-8 字节用 surrogateescape 保留）。region 绑定它所属的快照，只能用于该快照
    的文档；语言可以从 begin.tree.language 读到。
    begin and end are the two marker comment elements; body_span is the half-open byte range
    between them and body_text is that source text (bytes that are not UTF-8 are kept through
    surrogateescape). A region is bound to the snapshot it came from and may only be used with
    that snapshot's document; its language is available as begin.tree.language.
    """

    kind: str
    name: str | None
    begin: SyntaxElement
    end: SyntaxElement
    body_span: SourceSpan
    body_text: str


class SyntaxDocument:
    """某一语言的不可变文档快照。
    An immutable document snapshot of one language.
    """

    __slots__ = ("tree", "_parser")

    language: str

    def __init__(
        self,
        tree: SyntaxTree,
        parser: SyntaxParserProtocol,
    ) -> None:
        """绑定语法树和解析器；解析器用于修改后重新解析。
        Bind a syntax tree and its parser; the parser reparses the source after a change.

        Raises:
            ValueError: 语法树的语言与文档语言不符。
                The tree language is not the language of this document.
        """
        if tree.language != self.language:
            raise ValueError(f"expected {self.language!r} syntax tree, got {tree.language!r}")
        self.tree = tree
        self._parser = parser

    @property
    def root(self) -> SyntaxNode:
        """当前文档快照的 red 根节点。
        The red root view of this document snapshot.
        """
        return self.tree.root

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        """解析时记录的诊断；快照的诊断未经验证时为空元组。
        The diagnostics recorded while parsing; an empty tuple when the snapshot's diagnostics
        are unverified.

        空元组本身不区分"没有诊断"和"未验证"，两者用 diagnostic_state 区分。
        An empty tuple alone does not tell "no diagnostics" from "not verified"; use
        diagnostic_state for that.
        """
        return self.tree.diagnostics or ()

    def render(self) -> str:
        """按语法树中保存的源码内容原样渲染文本，不执行格式化。
        Render represented source text without applying formatting rules.
        """
        return self.tree.render()

    def render_bytes(self) -> bytes:
        """按原始编码规则渲染源码字节，并保留 surrogateescape 字节。
        Render represented source bytes while preserving surrogate-escaped input.
        """
        return self.tree.render_bytes()

    def elements(self, kind: str) -> tuple[SyntaxElement, ...]:
        """按源码顺序返回 kind 相同的全部节点和 token。
        All nodes and tokens of the given kind, in source order.
        """
        return tuple(self.root.descendants(kind, include_self=True))

    def nodes(self, kind: str) -> tuple[SyntaxNode, ...]:
        """按源码顺序返回 kind 相同的节点。
        The nodes of the given kind, in source order.
        """
        return tuple(element for element in self.elements(kind) if isinstance(element, SyntaxNode))

    # -----------------------------------------------------------------------
    # 成对注释区域：两种语言共用同一套配对与校验规则，只在注释语法与标记正则上不同。
    # Paired comment regions: both languages share one pairing and validation rule set and differ
    # only in comment syntax and marker patterns.
    # -----------------------------------------------------------------------
    def paired_comment_regions(
        self,
        *,
        kind: str,
        begin: re.Pattern[str],
        end: re.Pattern[str],
    ) -> tuple[SourceRegion, ...]:
        """按 begin/end 正则匹配成对注释，构造带 body span 的区域对象，按源码顺序返回。
        Pair begin/end comments, build region objects with their body spans and return them in
        source order.

        配对规则（两种语言一致）：
        The pairing rules, the same for both languages:

        1. 正则 fullmatch 于注释文本 strip() 之后；名字取捕获组 1 并 strip()。
           The pattern must fullmatch the stripped comment text; the name is capture group 1,
           stripped.
        2. End 的名字与栈顶不符时既不弹栈也不产生区域，因此 Begin A / End B / End A 仍得到区域 A。
           An End whose name differs from the top of the stack neither pops nor produces a region,
           so Begin A / End B / End A still yields region A.
        3. 嵌套按源码顺序配对；同名嵌套按栈配对，没有歧义。
           Nesting pairs in source order; a nested duplicate name pairs through the stack without
           ambiguity.
        4. 未配对的 Begin 与孤立的 End 不产生区域。
           An unpaired Begin and a lone End produce no region.
        """
        source = self.render_bytes()
        stack: list[tuple[SyntaxElement, str | None]] = []
        regions: list[SourceRegion] = []
        for comment in self.elements("comment"):
            begin_match = begin.fullmatch(comment.text.strip())
            if begin_match:
                name = begin_match.group(1).strip() if begin_match.lastindex else None
                stack.append((comment, name))
                continue
            end_match = end.fullmatch(comment.text.strip())
            if not end_match or not stack:
                continue
            start, name = stack[-1]
            end_name = (
                end_match.group(1).strip()
                if end_match.lastindex and end_match.group(1) is not None
                else None
            )
            if end_name != name:
                continue
            stack.pop()
            body = SourceSpan(start.span.end, comment.span.start)
            regions.append(
                SourceRegion(
                    kind,
                    name,
                    start,
                    comment,
                    body,
                    source[body.start : body.end].decode("utf-8", errors="surrogateescape"),
                )
            )
        return tuple(sorted(regions, key=lambda region: region.begin.span.start))

    def replace_region_body(self: _DocumentT, region: SourceRegion, body: str) -> _DocumentT:
        """替换当前文档中一个已验证区域的 body，并重新解析得到新的文档快照。
        Replace the body of a validated region of this document and reparse into a new snapshot.

        只改 body 的字节，两侧标记原文不动；重新解析使新快照的诊断仍然可信。
        Only the body bytes change and the markers stay as written; reparsing keeps the new
        snapshot's diagnostics trustworthy.

        Raises:
            ValueError: 区域属于另一份快照，body span 与标记不符，或超出当前源码范围。
                The region belongs to a different snapshot, its body span does not match the
                markers, or it exceeds the current source.
        """
        source = self.render_bytes()
        self._validate_region(region, len(source))
        replacement = encode_source(body)
        changed = source[: region.body_span.start] + replacement + source[region.body_span.end :]
        return self._reparse(changed)

    def _validate_region(self, region: SourceRegion, source_size: int) -> None:
        """确认 region 属于当前快照且 body span 与 marker 一致。
        Verify region ownership and ensure its body span matches the paired markers.

        Raises:
            ValueError: 区域不属于当前快照、body span 与标记不符，或超出当前源码范围。
                The region belongs to a different snapshot, its body span does not match the
                markers, or it exceeds the current source.
        """
        if region.begin.tree is not self.tree or region.end.tree is not self.tree:
            raise ValueError("region belongs to a different immutable syntax snapshot")
        expected = SourceSpan(region.begin.span.end, region.end.span.start)
        if region.body_span != expected:
            raise ValueError("region body span does not match its begin/end markers")
        if region.body_span.end > source_size:
            raise ValueError("region body span exceeds the current source range")

    def _reparse(self: _DocumentT, source: bytes) -> _DocumentT:
        """用同一个解析器重新解析修改后的源码，得到新的文档快照。
        Reparse changed source with the same parser into a new document snapshot.
        """
        tree = self._parser.parse(source, source_name=self.tree.source_name)
        return type(self)(tree, self._parser)
