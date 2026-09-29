"""批量扫描 C/C++/头文件并统计原生 C++ parser 的无损 round-trip 和诊断结果。
Batch-scan C/C++ sources and headers and report native-parser round-trip and diagnostic results.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterable
from pathlib import Path

from xr_syntax.cpp import CppParser

SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
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


def source_files(
    roots: Iterable[Path],
    suffixes: set[str] = SUFFIXES,
) -> Iterable[Path]:
    """递归枚举需要参与 round-trip 验证的源码文件，并跳过缓存和构建目录。
    Recursively enumerate source files for round-trip validation while skipping cache and build directories.
    """
    for root in roots:
        if root.is_file():
            if root.suffix.lower() in suffixes:
                yield root
            continue
        for directory, names, files in os.walk(root):
            names[:] = [name for name in names if name not in SKIP_DIRS]
            base = Path(directory)
            for name in files:
                path = base / name
                if path.suffix.lower() in suffixes:
                    yield path


def main() -> None:
    """解析命令行参数并执行当前工具的完整验证流程。
    Parse command-line arguments and execute the complete validation workflow.
    """
    arguments = argparse.ArgumentParser()
    arguments.add_argument("roots", nargs="+", type=Path)
    arguments.add_argument("--limit", type=int)
    arguments.add_argument(
        "--suffix",
        action="append",
        help="File suffix to include; repeat to override the default C/C++ set.",
    )
    arguments.add_argument("--json", type=Path)
    arguments.add_argument("--progress", action="store_true")
    args = arguments.parse_args()

    parser = CppParser()
    suffixes = (
        {value if value.startswith(".") else "." + value for value in args.suffix}
        if args.suffix
        else SUFFIXES
    )
    paths = sorted(set(source_files(args.roots, suffixes)))
    if args.limit:
        paths = paths[: args.limit]

    started = time.perf_counter()
    failures: list[dict[str, str]] = []
    diagnostic_files: list[dict[str, object]] = []
    bytes_total = 0

    for index, path in enumerate(paths, 1):
        if args.progress:
            print(f"PARSE {index}/{len(paths)} {path}", flush=True)
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
                    }
                )
        except Exception as error:
            failures.append({"path": str(path), "error": repr(error)})

    elapsed = time.perf_counter() - started
    result = {
        "language": "cpp",
        "files": len(paths),
        "bytes": bytes_total,
        "diagnostic_files": len(diagnostic_files),
        "diagnostics": sum(int(item["count"]) for item in diagnostic_files),
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

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")

    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
