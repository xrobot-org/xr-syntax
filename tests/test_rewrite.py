"""验证不可变重写只重建修改路径，并复用未变化的 green 子树。
Test immutable rewrites, including reuse of unchanged green subtrees.
"""

from xr_syntax.cpp import CppDocument, CppFactory


def test_immutable_replace_reuses_unchanged_tree() -> None:
    """验证不可变 replace 会复用未发生变化的 green 子树。
    Verify that immutable replacement reuses unchanged green subtrees.
    """
    document = CppDocument.parse("int a = 1;\nint b = 2;\n")
    declarations = document.nodes("declaration")
    replacement = CppFactory().declaration("int a = 42")
    changed = document.tree.replace(declarations[0], replacement)

    assert document.render() == "int a = 1;\nint b = 2;\n"
    assert changed.render() == "int a = 42;\nint b = 2;\n"
    assert changed.green_root.children[-1] is document.tree.green_root.children[-1]
