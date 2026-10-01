"""比较两个版本的 C++ parser 对同一批源码给出的语法树和诊断，用来确认重构没有改变解析结果。
Compare the syntax trees and diagnostics two versions of the C++ parser give for the same sources,
to confirm that a refactoring did not change parsing results.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import multiprocessing
import os
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp"}
SKIP_DIRS = {
    ".git",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


def source_files(roots: Iterable[Path]) -> list[str]:
    """递归列出 C/C++ 源码和头文件，跳过缓存和构建目录。
    Recursively list C/C++ sources and headers, skipping cache and build directories.
    """
    files: list[str] = []
    for root in roots:
        if root.is_file():
            files.append(str(root))
            continue
        for directory, names, entries in os.walk(root):
            names[:] = [name for name in names if name not in SKIP_DIRS]
            files.extend(
                str(Path(directory) / name)
                for name in entries
                if Path(name).suffix.lower() in SUFFIXES
            )
    return sorted(files)


def extract_revision(revision: str, target: Path) -> Path:
    """把 git 版本中的 src 目录解压到 target，返回解压出的 src 路径。
    Extract the src directory of a git revision into target and return the extracted src path.
    """
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", revision, "src"],
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter="data")
    return target / "src"


def _use_source(source_root: str) -> None:
    """worker 初始化：之后的 import xr_syntax 都来自 source_root。
    Worker initializer: every later import of xr_syntax comes from source_root.
    """
    sys.path.insert(0, source_root)


def canonical(path: str) -> str:
    """一个文件的规范化解析结果：按先序列出每个 green 元素，最后列出诊断；解析失败时给出异常。
    The canonical parsing result of one file: every green element in pre-order, then the
    diagnostics; the exception when parsing fails.

    用显式栈遍历，树再深也能输出。
    Walks with an explicit stack, so any tree depth can be written out.
    """
    from xr_syntax.core import GreenNode, GreenToken
    from xr_syntax.cpp import CppParser

    try:
        tree = CppParser().parse(Path(path).read_bytes())
    except Exception as error:  # noqa: BLE001 - 异常本身就是要比较的结果 / the exception is the result
        return f"error {type(error).__name__}: {error}"
    lines = []
    stack: list[tuple[object, str | None, int]] = [(tree.green_root, None, 0)]
    while stack:
        element, field, depth = stack.pop()
        if isinstance(element, GreenNode):
            flags = f"{element.named:d}{element.missing:d}{element.error:d}"
            lines.append(f"{depth} node {element.kind} {flags} {field}")
            stack.extend(
                (child.element, child.field, depth + 1) for child in reversed(element.children)
            )
        elif isinstance(element, GreenToken):
            flags = f"{element.named:d}{element.missing:d}{element.error:d}"
            lines.append(f"{depth} token {element.kind} {flags} {field} {element.text!r}")
        else:
            lines.append(f"{depth} trivia {element.kind} {field} {element.text!r}")  # type: ignore[attr-defined]
    lines.extend(
        f"diagnostic {item.message!r} {item.span.start} {item.span.end}"
        for item in tree.diagnostics
    )
    return "\n".join(lines)


def _digest(path: str) -> tuple[str, str]:
    """一个文件规范化结果的摘要。
    The digest of one file's canonical result.
    """
    text = canonical(path).encode("utf-8", errors="surrogateescape")
    return path, hashlib.blake2b(text, digest_size=16).hexdigest()


def _origin(_: object) -> str:
    """worker 实际导入的 xr_syntax 所在目录。
    The directory of the xr_syntax package the worker actually imports.
    """
    import xr_syntax

    return str(Path(xr_syntax.__file__).parent.parent)


def digests(source_root: Path, files: list[str], jobs: int) -> tuple[str, dict[str, str]]:
    """用 source_root 下的 parser 并行处理全部文件，返回实际使用的源码目录和每个文件的摘要。
    Process every file with the parser under source_root in parallel; return the source directory
    actually used and the digest of each file.
    """
    context = multiprocessing.get_context("spawn")
    with context.Pool(jobs, initializer=_use_source, initargs=(str(source_root),)) as pool:
        origin = pool.apply(_origin, (None,))
        return origin, dict(pool.imap_unordered(_digest, files, chunksize=8))


def canonical_with(source_root: Path, path: str) -> list[str]:
    """用 source_root 下的 parser 求一个文件的规范化结果（按行）。
    The canonical result of one file with the parser under source_root, as lines.
    """
    context = multiprocessing.get_context("spawn")
    with context.Pool(1, initializer=_use_source, initargs=(str(source_root),)) as pool:
        return pool.apply(canonical, (path,)).splitlines()


def main() -> int:
    """解析命令行参数，比较两个版本，打印差异；有差异时返回 1。
    Parse the command line, compare the two versions and print the differences; return 1 when
    something differs.
    """
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument(
        "roots", nargs="+", type=Path, help="源码文件或目录 / source files or directories"
    )
    arguments.add_argument(
        "--base", default="HEAD", help="作为基准的 git 版本 / git revision to compare against"
    )
    arguments.add_argument(
        "--head",
        help="要检查的 git 版本，省略时用工作区 / git revision to check; the working tree if omitted",
    )
    arguments.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    arguments.add_argument(
        "--show", type=int, default=3, help="打印差异的文件数 / files whose diff is printed"
    )
    arguments.add_argument("--lines", type=int, default=40, help="每个差异的行数 / lines per diff")
    options = arguments.parse_args()

    files = source_files(options.roots)
    with tempfile.TemporaryDirectory() as temporary:
        base_root = extract_revision(options.base, Path(temporary) / "base")
        head_root = (
            extract_revision(options.head, Path(temporary) / "head")
            if options.head
            else ROOT / "src"
        )
        base_origin, base = digests(base_root, files, options.jobs)
        head_origin, head = digests(head_root, files, options.jobs)
        differ = [path for path in files if base[path] != head[path]]
        print(f"base {options.base}: {base_origin}")
        print(f"head {options.head or 'working tree'}: {head_origin}")
        print(f"{len(files)} files, {len(differ)} differ")
        for path in differ[: options.show]:
            diff = difflib.unified_diff(
                canonical_with(base_root, path),
                canonical_with(head_root, path),
                "base",
                "head",
                n=3,
                lineterm="",
            )
            print(f"--- {path}")
            for line in list(diff)[: options.lines]:
                print(line)
        for path in differ[options.show :]:
            print(path)
    return 1 if differ else 0


if __name__ == "__main__":
    # 差异里有源码文本，管道输出时也按 UTF-8 写。
    # Diffs contain source text, so piped output is written as UTF-8 as well.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[union-attr]
    sys.exit(main())
