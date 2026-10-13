"""定义不可变 SyntaxTree 快照以及底层的 replace 结构编辑。
The immutable SyntaxTree snapshot and its low-level structural replace.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

from xr_syntax.core.diagnostic import Diagnostic
from xr_syntax.core.fragment import SyntaxFragment
from xr_syntax.core.green import GreenElement, GreenNode
from xr_syntax.core.red import SyntaxElement, SyntaxNode
from xr_syntax.core.text import encode_source


@dataclass(frozen=True)
class SyntaxTree:
    """一次解析得到的不可变语法快照：green 根节点、诊断和来源名。
    The immutable syntax snapshot of one parse: the green root, diagnostics and source name.

    diagnostics 为 None 表示这份快照的诊断**未经验证**：快照由底层编辑得到，没有重新解析，
    因此既不能读作"没有诊断"，也不能读作"有诊断"。用 diagnostic_state 区分。
    A None diagnostics means the snapshot's diagnostics are unverified: the snapshot came from a
    low-level edit without reparsing, so it must be read neither as "no diagnostics" nor as "has
    diagnostics". diagnostic_state tells the three apart.
    """

    language: str
    green_root: GreenNode
    diagnostics: tuple[Diagnostic, ...] | None
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

    @property
    def diagnostic_state(self) -> str:
        """诊断状态：clean（解析过且没有诊断）、diagnosed（解析过且有诊断）、unknown（未验证）。
        The diagnostic state: clean (parsed, no diagnostic), diagnosed (parsed, with diagnostics)
        or unknown (not verified).
        """
        if self.diagnostics is None:
            return "unknown"
        return "diagnosed" if self.diagnostics else "clean"

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

    # -----------------------------------------------------------------------
    # 底层结构编辑：只沿 target 的结构路径重建祖先链，路径之外的 green 子树继续复用；
    # 编辑后 diagnostics 变为未知，需要重新解析才能恢复（见 diagnostic_state）。
    # Low-level structural edits rebuild only the ancestor chain of the target path and keep
    # reusing the green subtrees outside it; diagnostics become unknown afterwards and need a
    # reparse to be trustworthy again (see diagnostic_state).
    # -----------------------------------------------------------------------
    def replace(
        self,
        target: SyntaxElement,
        replacement: SyntaxElement | SyntaxFragment,
    ) -> SyntaxTree:
        """持久化替换一个元素，仅重建目标到根路径上的节点。
        Persistently replace one element, reusing unaffected green subtrees.

        Raises:
            ValueError: 目标不属于当前快照。
                The target belongs to a different snapshot.
            TypeError: 替换内容既不是本快照的元素，也不是带语言归属的片段。
                The replacement is neither an element of this snapshot nor a language-tagged
                fragment.
        """
        self._check_target(target)
        green = self._coerce_insertable(replacement)
        if not target.path:
            if not isinstance(green, GreenNode):
                raise TypeError("syntax tree root must remain a GreenNode")
            return self._with_root(green)
        return self._with_root(_replace_at(self.green_root, target.path, green))

    def _check_target(self, target: SyntaxElement) -> None:
        """确认待编辑 red 元素属于当前 SyntaxTree 快照。
        Verify that the edited red element belongs to this SyntaxTree snapshot.

        Raises:
            ValueError: 目标属于另一份快照。
                The target belongs to a different snapshot.
        """
        if target.tree is not self:
            raise ValueError("target belongs to a different immutable syntax snapshot")

    def _coerce_insertable(
        self,
        value: SyntaxElement | SyntaxFragment,
    ) -> GreenElement:
        """取得可插入 green 元素并校验语言归属。
        Resolve an insertable green element and validate its language provenance.

        同语言但来自另一份快照的元素是允许的：green 元素不带位置，跨快照拼接安全。跨语言一律拒绝，
        裸 GreenElement 也拒绝，要求调用方用 SyntaxFragment 显式标注语言。
        An element of the same language from another snapshot is allowed: green elements carry no
        position, so splicing them across snapshots is safe. A different language is always
        rejected, and a bare GreenElement is rejected too: wrap it in a SyntaxFragment that states
        its language.

        Raises:
            ValueError: 语言不匹配。
                The language does not match.
            TypeError: 既不是 SyntaxElement 也不是 SyntaxFragment。
                The value is neither a SyntaxElement nor a SyntaxFragment.
        """
        if isinstance(value, SyntaxElement):
            if value.tree.language != self.language:
                raise ValueError(
                    f"element language {value.tree.language!r} does not match tree language "
                    f"{self.language!r}"
                )
            return value.green
        if isinstance(value, SyntaxFragment):
            return value.green_for(self.language)
        raise TypeError(
            "low-level edits accept SyntaxElement or SyntaxFragment; "
            "wrap generated/raw green data in SyntaxFragment with an explicit language"
        )

    def _with_root(self, root: GreenNode) -> SyntaxTree:
        """用新 green root 构造诊断状态未知的新 SyntaxTree。
        Create a new SyntaxTree whose diagnostics are unknown until reparsed.
        """
        return SyntaxTree(
            language=self.language,
            green_root=root,
            diagnostics=None,
            source_name=self.source_name,
        )


# ---------------------------------------------------------------------------
# 结构路径递归操作：只处理 green tree，不触碰 parser 与诊断
# Structural-path recursion over the green tree only; parser and diagnostics are untouched
# ---------------------------------------------------------------------------


def _replace_at(
    root: GreenNode,
    path: tuple[int, ...],
    element: GreenElement,
) -> GreenNode:
    """按结构路径递归替换 green 元素，并复用路径外的子树。
    Recursively replace a green element by structural path while reusing subtrees outside the path.

    Raises:
        ValueError: 路径中途经过非节点元素。
            The path crosses a non-node element.
    """
    index = path[0]
    if len(path) == 1:
        return root.replacing_child(index, element)
    child = root.children[index].element
    if not isinstance(child, GreenNode):
        raise ValueError("rewrite path crosses a non-node")
    return root.replacing_child(index, _replace_at(child, path[1:], element))
