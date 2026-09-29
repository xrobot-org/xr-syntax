"""检查 Python docstring 和 Markdown 是否同时包含中英文说明。
Check Python docstrings and Markdown files for Chinese and English documentation.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import tokenize
from pathlib import Path

_CHINESE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_ENGLISH_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9+-]*\b")
_SKIP = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__", "build", "dist"}


def _has_chinese(text: str | None) -> bool:
    """判断文本是否包含中文。
    Return whether text contains Chinese characters.
    """
    return bool(text and _CHINESE.search(text))


def _has_english(text: str | None) -> bool:
    """判断文本是否包含可读英文说明。
    Return whether text contains readable English prose.
    """
    return bool(text and len(_ENGLISH_WORD.findall(text)) >= 3)


def _python_files(root: Path) -> list[Path]:
    """列出项目源码、测试和工具中的 Python 文件。
    List Python files from project source, tests, and tools.
    """
    files: list[Path] = []
    for directory in ("src", "tests", "tools"):
        base = root / directory
        if not base.exists():
            continue
        files.extend(
            path for path in base.rglob("*.py") if not any(part in _SKIP for part in path.parts)
        )
    return sorted(files)


def _check_docstring(
    issues: list[tuple[Path, int, str]],
    path: Path,
    node: ast.AST,
    label: str,
) -> None:
    """检查一个 AST 节点的中英文 docstring。
    Check one AST node for a bilingual docstring.
    """
    doc = ast.get_docstring(node, clean=False)
    line = int(getattr(node, "lineno", 1))
    missing = []
    if not _has_chinese(doc):
        missing.append("中文")
    if not _has_english(doc):
        missing.append("English")
    if missing:
        issues.append((path, line, f"{label}: missing {' + '.join(missing)}"))


class _Visitor(ast.NodeVisitor):
    """遍历模块中的类和函数定义。
    Visit class and function definitions in a Python module.
    """

    def __init__(self, path: Path, issues: list[tuple[Path, int, str]]) -> None:
        """保存当前文件和问题列表。
        Store the current file and issue list.
        """
        self.path = path
        self.issues = issues
        self.stack: list[str] = []

    def _visit_definition(self, node: ast.AST, name: str) -> None:
        """检查定义并继续遍历其子节点。
        Check a definition and continue through its children.
        """
        qualified = ".".join(self.stack + [name])
        _check_docstring(self.issues, self.path, node, qualified)
        self.stack.append(name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """检查类定义。
        Check a class definition.
        """
        self._visit_definition(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """检查函数或方法定义。
        Check a function or method definition.
        """
        self._visit_definition(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """检查异步函数定义。
        Check an async function definition.
        """
        self._visit_definition(node, node.name)


def _audit_python(root: Path) -> list[tuple[Path, int, str]]:
    """检查全部 Python 模块、类、函数和 runtime 行注释。
    Audit Python docstrings and require Chinese line comments in runtime files.
    """
    issues: list[tuple[Path, int, str]] = []
    runtime_root = root / "src" / "xr_syntax"

    for path in _python_files(root):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        _check_docstring(issues, path, tree, "<module>")
        _Visitor(path, issues).visit(tree)

        if runtime_root in path.parents:
            comments = (
                token.string
                for token in tokenize.generate_tokens(io.StringIO(source).readline)
                if token.type == tokenize.COMMENT
            )
            if not any(_has_chinese(comment) for comment in comments):
                issues.append((path, 1, "<module>: missing 中文 # comment"))

    return issues


def _audit_markdown(root: Path) -> list[tuple[Path, int, str]]:
    """检查 README 和 docs 下的 Markdown 是否包含中英文。
    Check README and docs Markdown files for Chinese and English.
    """
    paths = [root / "README.md"]
    docs = root / "docs"
    if docs.exists():
        paths.extend(sorted(docs.rglob("*.md")))

    issues: list[tuple[Path, int, str]] = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        missing = []
        if not _has_chinese(text):
            missing.append("中文")
        if not _has_english(text):
            missing.append("English")
        if missing:
            issues.append((path, 1, f"Markdown: missing {' + '.join(missing)}"))
    return issues


def audit(root: Path) -> list[tuple[Path, int, str]]:
    """运行完整双语文档检查。
    Run the complete bilingual documentation audit.
    """
    return _audit_python(root) + _audit_markdown(root)


def main() -> None:
    """运行命令行检查并设置退出码。
    Run the command-line audit and set the process exit code.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    issues = audit(args.root)
    for path, line, message in issues:
        print(f"{path}:{line}: {message}")
    print(f"missing_bilingual_docs={len(issues)}")
    if issues and not args.report_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
