"""排版测试用的固定版本 clang-format。
The pinned clang-format used by the layout tests.

排版引擎的契约是"与 LibXR 的 .clang-format 结果相同"，所以测试必须用一个固定版本的
clang-format 核对；版本不同排版可能不同，没有这个版本时相关测试跳过。
The layout engine's contract is "the same as clang-format with LibXR's .clang-format", so the tests
check it with one pinned version; another version may format differently, and the tests that need
this one are skipped without it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# 生成的 C++ 按这个版本的 clang-format 和 LibXR 的 .clang-format 核对。
# The generated C++ is checked against this version of clang-format and LibXR's .clang-format.
CLANG_FORMAT_VERSION = "21.1.8"
LIBXR_CLANG_FORMAT = Path(__file__).with_name("libxr.clang-format")


def clang_format_command() -> str | None:
    """固定版本的 clang-format 可执行文件；没有安装或版本不同时为 None。
    The clang-format executable of the pinned version; None when it is not installed or has another
    version.

    先找 PATH，再找运行测试的 Python 的脚本目录（pip install clang-format==21.1.8 装到那里）。
    PATH is searched first, then the scripts directory of the Python running the tests, where
    pip install clang-format==21.1.8 puts it.
    """
    candidates = [shutil.which("clang-format")]
    scripts = Path(sys.executable).parent
    candidates += [str(scripts / name) for name in ("clang-format", "clang-format.exe")]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        version = subprocess.run([candidate, "--version"], capture_output=True, text=True)
        if version.returncode == 0 and CLANG_FORMAT_VERSION in version.stdout:
            return candidate
    return None


requires_clang_format = pytest.mark.skipif(
    clang_format_command() is None,
    reason=(
        f"clang-format {CLANG_FORMAT_VERSION} is not installed "
        f"(pip install clang-format=={CLANG_FORMAT_VERSION})"
    ),
)


def clang_format(text: str, file_name: str) -> str:
    """text 按 LibXR 的风格由 clang-format 排版的结果，视作名为 file_name 的文件。
    The text formatted by clang-format in the style of LibXR, as if it were the file named
    file_name.
    """
    result = subprocess.run(
        [
            str(clang_format_command()),
            f"--style=file:{LIBXR_CLANG_FORMAT}",
            f"--assume-filename={file_name}",
        ],
        input=text,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout
