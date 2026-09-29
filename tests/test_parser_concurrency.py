"""验证共享 native parser 实例的并发 parse 行为。
Test concurrent parse calls on shared native parser instances.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from xr_syntax.cmake import CMakeParser
from xr_syntax.cpp import CppParser


def _run_many(parser, sources: list[bytes]) -> list[bytes]:
    """并发解析输入并返回 round-trip 字节。
    Parse inputs concurrently and return their round-tripped bytes.
    """

    def parse(source: bytes) -> bytes:
        """执行单次无损解析。
        Run one lossless parse operation.
        """
        return parser.parse(source).render_bytes()

    with ThreadPoolExecutor(max_workers=8) as executor:
        return list(executor.map(parse, sources))


def test_cpp_parser_instance_supports_concurrent_parse_calls() -> None:
    """同一个 CppParser 实例可并发处理独立源码。
    A shared CppParser instance can parse independent sources concurrently.
    """
    parser = CppParser()
    sources = [f"void f{i}() {{ target({i}); }}\n".encode() for i in range(64)]
    assert _run_many(parser, sources) == sources


def test_cmake_parser_instance_supports_concurrent_parse_calls() -> None:
    """同一个 CMakeParser 实例可并发处理独立源码。
    A shared CMakeParser instance can parse independent sources concurrently.
    """
    parser = CMakeParser()
    sources = [
        f"project(Demo{i})\nadd_library(lib{i} STATIC file{i}.cpp)\n".encode() for i in range(64)
    ]
    assert _run_many(parser, sources) == sources
