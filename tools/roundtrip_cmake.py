"""批量扫描 CMake 文件并统计 parser 的无损 round-trip 和诊断结果。
Batch-scan CMake files and report lossless parser round-trip and diagnostic results.

用法：给出一个或多个目录（或单个文件），工具会递归找出 CMakeLists.txt 与 *.cmake。
Usage: give one or more directories, or single files; the tool finds CMakeLists.txt and *.cmake
recursively.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterable
from pathlib import Path

from xr_syntax.cmake import CMakeParser

# 跳过缓存和构建目录：它们里面有大量生成的 CMake 文件，不代表手写语料。
# Cache and build directories are skipped: they hold many generated CMake files that do not stand
# for hand-written corpus.
SKIP_DIRS = {
    ".git",
    ".cache",
    ".history",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "evidence",
    "node_modules",
}


def source_files(roots: Iterable[Path]) -> Iterable[Path]:
    """递归枚举需要参与 round-trip 验证的 CMake 文件，并跳过缓存和构建目录。
    Recursively enumerate the CMake files for round-trip validation while skipping cache and build
    directories.
    """
    for root in roots:
        if root.is_file():
            if root.name == "CMakeLists.txt" or root.suffix.lower() == ".cmake":
                yield root
            continue
        for directory, names, files in os.walk(root):
            names[:] = [name for name in names if name not in SKIP_DIRS]
            base = Path(directory)
            for name in files:
                path = base / name
                if name == "CMakeLists.txt" or path.suffix.lower() == ".cmake":
                    yield path


def main() -> None:
    """解析命令行参数并执行完整的往返验证流程。
    Parse the command-line arguments and run the complete round-trip validation.
    """
    arguments = argparse.ArgumentParser()
    arguments.add_argument("roots", nargs="+", type=Path)
    arguments.add_argument("--limit", type=int)
    arguments.add_argument("--json", type=Path)
    args = arguments.parse_args()

    parser = CMakeParser()
    paths = sorted(set(source_files(args.roots)))
    if args.limit:
        paths = paths[: args.limit]

    started = time.perf_counter()
    failures: list[dict[str, str]] = []
    diagnostic_files: list[dict[str, object]] = []
    bytes_total = 0

    for path in paths:
        data = path.read_bytes()
        bytes_total += len(data)
        try:
            tree = parser.parse(data, source_name=str(path))
            if tree.render_bytes() != data:
                failures.append({"path": str(path), "error": "round-trip mismatch"})
            if tree.diagnostics:
                diagnostic_files.append(
                    {
                        "path": str(path),
                        "count": len(tree.diagnostics),
                        "messages": sorted({item.message for item in tree.diagnostics}),
                    }
                )
        except Exception as error:  # noqa: BLE001 - 一个文件的异常不该中断整轮扫描。
            failures.append({"path": str(path), "error": repr(error)})

    elapsed = time.perf_counter() - started
    result = {
        "language": "cmake",
        "files": len(paths),
        "bytes": bytes_total,
        "diagnostic_files": len(diagnostic_files),
        "diagnostics": sum(int(item["count"]) for item in diagnostic_files),
        "diagnostic_file_list": diagnostic_files,
        "failures": failures,
        "elapsed_seconds": elapsed,
    }
    print(
        f"files={result['files']} bytes={result['bytes']} "
        f"diagnostic_files={result['diagnostic_files']} "
        f"diagnostics={result['diagnostics']} failures={len(failures)} "
        f"elapsed={elapsed:.3f}s"
    )
    for failure in failures[:30]:
        print(f"FAIL {failure['path']}: {failure['error']}")
    # 有诊断的文件按路径列出来：语料里出现诊断时报告要能点名。
    # The files with diagnostics are listed by path, so a report can name them when the corpus has
    # any.
    for item in diagnostic_files[:30]:
        print(f"DIAG {item['path']}: {item['count']}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")

    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
