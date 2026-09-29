"""定义持久化语法树重写器；未修改的 green 子树保持对象复用。
Persistent syntax-tree rewriter that preserves unchanged green subtrees.
"""

from __future__ import annotations

from .green import GreenChild, GreenElement, GreenNode, GreenToken, GreenTrivia
from .tree import SyntaxTree

# ---------------------------------------------------------------------------
# 模块实现：定义持久化语法树重写器；未修改的 green 子树保持对象复用。
# ---------------------------------------------------------------------------


class SyntaxRewriter:
    """按函数式方式重写 green 树；钩子返回原对象时保持 identity，使未变化的祖先分支可以继续复用。
    Functional green-tree rewriter.
    """

    def rewrite(self, tree: SyntaxTree) -> SyntaxTree:
        """重写整棵树；发生修改时将 diagnostics 标记为未知。
        Rewrite a tree and mark diagnostics unknown when the green root changes.
        """
        root = self.visit_node(tree.green_root)
        if root is tree.green_root:
            return tree
        return SyntaxTree(tree.language, root, None, tree.source_name)

    def visit_node(self, node: GreenNode) -> GreenNode:
        """递归重写 children，仅在至少一个 child 改变时重建当前 GreenNode。
        Rewrite children recursively and rebuild this node only if some child changed.
        """
        changed = False
        children: list[GreenChild] = []
        for child in node.children:
            element = self.visit(child.element)
            changed |= element is not child.element
            children.append(GreenChild(element, child.field))
        if not changed:
            return node
        return GreenNode(
            node.kind,
            tuple(children),
            node.named,
            node.missing,
            node.error,
        )

    def visit_token(self, token: GreenToken) -> GreenElement:
        """处理一个 GreenToken；默认保持原对象不变。
        Handle one syntax token.
        """
        return token

    def visit_trivia(self, trivia: GreenTrivia) -> GreenElement:
        """处理一个 GreenTrivia；默认保持原对象不变。
        Handle one preserved trivia element.
        """
        return trivia

    def visit(self, element: GreenElement) -> GreenElement:
        """按 GreenNode、GreenToken 或 GreenTrivia 类型分派到对应重写钩子。
        Dispatch this element to the appropriate visitor or rewriter hook.
        """
        if isinstance(element, GreenNode):
            return self.visit_node(element)
        if isinstance(element, GreenToken):
            return self.visit_token(element)
        return self.visit_trivia(element)
