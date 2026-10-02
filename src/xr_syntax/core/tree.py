"""定义不可变的 SyntaxTree 快照。
The immutable SyntaxTree snapshot.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

from xr_syntax.core.diagnostic import Diagnostic
from xr_syntax.core.green import GreenNode
from xr_syntax.core.red import SyntaxNode
from xr_syntax.core.text import encode_source


@dataclass(frozen=True)
class SyntaxTree:
    """一次解析得到的不可变语法快照：green 根节点、诊断和来源名。
    The immutable syntax snapshot of one parse: the green root, diagnostics and source name.
    """

    language: str
    green_root: GreenNode
    diagnostics: tuple[Diagnostic, ...]
    source_name: str | None = None

    @property
    def root(self) -> SyntaxNode:
        """当前快照的 red 根节点。
        The red root view of this snapshot.
        """
        return SyntaxNode(
            self,
            self.green_root,
            parent=None,
            index=0,
            offset=0,
            field=None,
        )

    def render(self) -> str:
        """按 green root 原样渲染完整源码文本。
        Render the complete represented source without normalization.
        """
        return self._source_text

    def render_bytes(self) -> bytes:
        """按源码编码原样渲染完整源码字节。
        Render the complete represented source as bytes.
        """
        return self._source_bytes

    # 快照不可变，渲染结果只计算一次；行号、invocation 文本和解析后的无损检查都会用到它。
    # The snapshot is immutable, so it is rendered once; line numbers, invocation texts and
    # the lossless check after parsing all use the result.
    @functools.cached_property
    def _source_text(self) -> str:
        """渲染一次的源码文本。
        The source text, rendered once.
        """
        return self.green_root.render()

    @functools.cached_property
    def _source_bytes(self) -> bytes:
        """编码一次的源码字节。
        The source bytes, encoded once.
        """
        return encode_source(self._source_text)
