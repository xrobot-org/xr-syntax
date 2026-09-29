"""测量 C++ parse、query 和高层编辑的基础耗时。
Benchmark baseline C++ parse, query, and high-level edit costs.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterable
from dataclasses import dataclass

from xr_syntax.cpp import CppDocument, CppFactory


@dataclass(frozen=True)
class BenchmarkResult:
    """保存一个输入规模的基准结果。
    Store benchmark measurements for one input size.
    """

    bytes: int
    declarations: int
    parse_ms: float
    query_ms: float
    single_edit_ms: float
    batch_edit_ms: float
    batch_edits: int


def _make_source(target_bytes: int) -> bytes:
    """生成接近指定字节数的稳定 C++ declaration corpus。
    Build a deterministic C++ declaration corpus near the requested byte size.
    """
    lines: list[str] = []
    size = 0
    index = 0
    while size < target_bytes:
        line = f"static int value_{index} = {index};\n"
        lines.append(line)
        size += len(line.encode("utf-8"))
        index += 1
    return "".join(lines).encode("utf-8")


def _elapsed_ms(callback) -> tuple[float, object]:
    """运行回调并返回毫秒耗时和结果。
    Run a callback and return elapsed milliseconds together with its result.
    """
    start = time.perf_counter()
    result = callback()
    return (time.perf_counter() - start) * 1000.0, result


def benchmark_case(target_bytes: int, batch_edits: int) -> BenchmarkResult:
    """测量一个输入规模的 parse、query、单次编辑和批量编辑。
    Measure parse, query, single-edit, and repeated-edit costs for one input size.
    """
    source = _make_source(target_bytes)
    parse_ms, parsed = _elapsed_ms(lambda: CppDocument.parse(source))
    document = parsed
    assert isinstance(document, CppDocument)

    query_ms, declarations = _elapsed_ms(lambda: document.nodes("declaration"))
    declaration_nodes = declarations
    assert isinstance(declaration_nodes, tuple)
    if not declaration_nodes:
        raise RuntimeError("benchmark source did not produce declarations")

    factory = CppFactory()
    single_edit_ms, changed = _elapsed_ms(
        lambda: document.replace(
            declaration_nodes[0],
            factory.declaration("static int value_0 = 42"),
        )
    )
    assert isinstance(changed, CppDocument)

    def run_batch() -> CppDocument:
        """连续执行多次高层编辑并返回最终文档。
        Run repeated high-level edits and return the final document.
        """
        current = document
        for index in range(batch_edits):
            target = current.nodes("declaration")[0]
            current = current.replace(
                target,
                factory.declaration(f"static int value_0 = {100 + index}"),
            )
        return current

    batch_edit_ms, batch_result = _elapsed_ms(run_batch)
    assert isinstance(batch_result, CppDocument)
    return BenchmarkResult(
        bytes=len(source),
        declarations=len(declaration_nodes),
        parse_ms=parse_ms,
        query_ms=query_ms,
        single_edit_ms=single_edit_ms,
        batch_edit_ms=batch_edit_ms,
        batch_edits=batch_edits,
    )


def run(sizes: Iterable[int], batch_edits: int) -> list[BenchmarkResult]:
    """依次运行多个输入规模。
    Run benchmark cases for each requested input size.
    """
    return [benchmark_case(size, batch_edits) for size in sizes]


def _print_results(results: Iterable[BenchmarkResult]) -> None:
    """以 TSV 输出结果，便于复制到表格或日志。
    Print results as TSV for easy capture in logs or spreadsheets.
    """
    print("bytes\tdeclarations\tparse_ms\tquery_ms\tsingle_edit_ms\tbatch_edits\tbatch_edit_ms")
    for item in results:
        print(
            f"{item.bytes}\t{item.declarations}\t{item.parse_ms:.3f}\t"
            f"{item.query_ms:.3f}\t{item.single_edit_ms:.3f}\t"
            f"{item.batch_edits}\t{item.batch_edit_ms:.3f}"
        )


def main() -> None:
    """解析命令行参数并运行基准。
    Parse command-line options and run the benchmark.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[10_000, 100_000, 1_000_000],
        help="target source sizes in bytes",
    )
    parser.add_argument("--batch-edits", type=int, default=3)
    args = parser.parse_args()
    if args.batch_edits < 1:
        raise SystemExit("--batch-edits must be >= 1")
    _print_results(run(args.sizes, args.batch_edits))


if __name__ == "__main__":
    main()
