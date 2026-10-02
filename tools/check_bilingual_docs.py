"""检查 docstring、注释和 Markdown 的中英文写法。
Check the bilingual layout of docstrings, comments and Markdown files.

docstring 第一行是中文，第二行是英文；含中文的注释块后面接英文行；README 和 docs 下的
Markdown 同时有中文和英文。tests/ 中以 test_ 开头的测试函数由函数名说明，不检查 docstring。
A docstring starts with a Chinese line followed by an English line; a comment block holding
Chinese continues with English lines; README and the Markdown files under docs hold both
Chinese and English. Test functions in tests/ whose names start with test_ are described by
their names, and their docstrings are not checked.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import tokenize
from pathlib import Path

_CHINESE = re.compile(r"[㐀-䶿一-鿿]")
_ENGLISH_WORD = re.compile(r"[A-Za-z]{2,}")
_SKIP = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__", "build", "dist"}
_DIRECTIVE = re.compile(r"#\s*(noqa|type:|pragma)")

Issue = tuple[Path, int, str]


def _is_chinese(text: str) -> bool:
    """文本是否含中文。
    Whether text holds Chinese.
    """
    return bool(_CHINESE.search(text))


def _is_english(text: str) -> bool:
    """文本是否是英文：不含中文，并且有英文单词。
    Whether text is English: no Chinese and at least one English word.
    """
    return not _is_chinese(text) and bool(_ENGLISH_WORD.search(text))


def _python_files(root: Path) -> list[Path]:
    """列出源码、测试和工具中的 Python 文件。
    List the Python files of the source, tests and tools.
    """
    files: list[Path] = []
    for directory in ("src", "tests", "tools"):
        base = root / directory
        if base.exists():
            files.extend(
                path for path in base.rglob("*.py") if not any(part in _SKIP for part in path.parts)
            )
    return sorted(files)


def _check_docstring(issues: list[Issue], path: Path, node: ast.AST, label: str) -> None:
    """检查一个模块、类或函数的 docstring：第一行中文，第二行英文。
    Check the docstring of one module, class or function: a Chinese line, then English.
    """
    line = int(getattr(node, "lineno", 1))
    doc = ast.get_docstring(node, clean=True)
    if doc is None:
        issues.append((path, line, f"{label}: no docstring"))
        return
    lines = [text.strip() for text in doc.splitlines() if text.strip()]
    if not lines or not _is_chinese(lines[0]):
        issues.append((path, line, f"{label}: the docstring does not start with Chinese"))
    elif len(lines) < 2 or not _is_english(lines[1]):
        issues.append((path, line, f"{label}: the Chinese line is not followed by English"))


class _Visitor(ast.NodeVisitor):
    """遍历模块中的类和函数定义。
    Visit the class and function definitions of a module.
    """

    def __init__(self, path: Path, issues: list[Issue], is_test: bool) -> None:
        """保存当前文件、问题列表以及它是否是测试文件。
        Store the current file, the issue list and whether the file is a test.
        """
        self.path = path
        self.issues = issues
        self.is_test = is_test
        self.stack: list[str] = []

    def _visit_definition(self, node: ast.AST, name: str) -> None:
        """检查一个定义并继续遍历其子节点。
        Check one definition and continue with its children.
        """
        if not (self.is_test and name.startswith("test_")):
            _check_docstring(self.issues, self.path, node, ".".join([*self.stack, name]))
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


def _check_comments(issues: list[Issue], path: Path, source: str) -> None:
    """检查注释块：含中文的块在中文行之后要有英文行。
    Check comment blocks: a block holding Chinese has English lines after its Chinese ones.
    """
    blocks: list[list[tuple[int, str]]] = []
    previous = -1
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT or _DIRECTIVE.match(token.string):
            continue
        row = token.start[0]
        if blocks and row == previous + 1:
            blocks[-1].append((row, token.string))
        else:
            blocks.append([(row, token.string)])
        previous = row
    for block in blocks:
        texts = [text.lstrip("#").strip() for _, text in block]
        chinese = [index for index, text in enumerate(texts) if _is_chinese(text)]
        if chinese and not any(_is_english(text) for text in texts[chinese[-1] + 1 :]):
            issues.append((path, block[0][0], "comment: the Chinese is not followed by English"))


def _audit_python(root: Path) -> list[Issue]:
    """检查全部 Python 文件的 docstring 和注释。
    Check the docstrings and comments of all Python files.
    """
    issues: list[Issue] = []
    for path in _python_files(root):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        _check_docstring(issues, path, tree, "<module>")
        _Visitor(path, issues, is_test=path.parent.name == "tests").visit(tree)
        _check_comments(issues, path, source)
    return issues


def _audit_markdown(root: Path) -> list[Issue]:
    """检查 README 和 docs 下的 Markdown 同时有中文和英文。
    Check that README and the Markdown files under docs hold both Chinese and English.
    """
    paths = [root / "README.md"]
    docs = root / "docs"
    if docs.exists():
        paths.extend(sorted(docs.rglob("*.md")))
    issues: list[Issue] = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        prose = [line for line in text.splitlines() if line.strip() and not line.startswith("    ")]
        if not any(_is_chinese(line) for line in prose):
            issues.append((path, 1, "Markdown: no Chinese"))
        if not any(_is_english(line) and len(_ENGLISH_WORD.findall(line)) >= 5 for line in prose):
            issues.append((path, 1, "Markdown: no English prose"))
    return issues


def audit(root: Path) -> list[Issue]:
    """运行全部检查。
    Run all checks.
    """
    return _audit_python(root) + _audit_markdown(root)


def main() -> None:
    """运行检查；有问题时逐条列出并以退出码 1 结束。
    Run the checks; list every problem and exit with code 1 when there are any.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: the repository holding this script)",
    )
    args = parser.parse_args()
    issues = audit(args.root)
    for path, line, message in issues:
        print(f"{path}:{line}: {message}")
    print(f"missing_bilingual_docs={len(issues)}")
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
