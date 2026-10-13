"""验证 0.2.0 的用户不会为 CMake、排版引擎和 CMake schema 付导入代价。
Check that a 0.2.0 user pays nothing for the CMake, layout and CMake schema modules.

用一个干净的子进程检查 sys.modules，而不是在当前进程里检查：测试本身已经导入了全部前端。
A fresh subprocess checks sys.modules, rather than this process, because the tests themselves import
every frontend.
"""

from __future__ import annotations

import json
import subprocess
import sys

# 只想使用其中一部分的用户：他们导入的东西不该把其余部分拖进来。
# Users of one part only: what they import must not pull in the rest.
PARTS = ("xr_syntax.i18n", "xr_syntax.cpp", "xr_syntax.core")

# 不属于核心的部分；顶层包的惰性属性不算，这里只看导入。
# The parts that are not core; the lazy attributes of the top-level package do not count, because only
# imports do.
EXPENSIVE = {"xr_syntax.cmake", "xr_syntax.format"}

# 在子进程里做一次导入，打印已加载的顶层 xr_syntax 模块名。
# Import once in the subprocess and print the loaded top-level xr_syntax module names.
_CODE = (
    "import json, sys\n"
    "{imports}\n"
    "print(json.dumps(sorted(n for n in sys.modules if n.startswith('xr_syntax'))))"
)


def loaded_modules(imports: str) -> set[str]:
    """在干净的子进程里做一次导入，返回已加载的 xr_syntax 模块名。
    Import once in a fresh subprocess and return the loaded xr_syntax module names.
    """
    result = subprocess.run(
        [sys.executable, "-c", _CODE.format(imports=imports)],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(json.loads(result.stdout))


def test_importing_one_part_does_not_load_the_others() -> None:
    for name in PARTS:
        loaded = loaded_modules(f"import {name}")
        assert not (loaded & EXPENSIVE), loaded
        # 只导入 C++ 时连 CMake 的子模块都不该出现。
        # Importing the C++ alone must not even show a CMake submodule.
        if name == "xr_syntax.cpp":
            assert not any(item.startswith("xr_syntax.cmake") for item in loaded), loaded
            # 只读地使用 C++ 前端时，文件构建器和它依赖的片段模块也不该被加载。
            # Using the C++ frontend read-only must not load the file builder either, nor the
            # fragment module it depends on.
            assert "xr_syntax.cpp.builder" not in loaded, loaded
            assert "xr_syntax.core.fragment" not in loaded, loaded
        # 只导入 C++ 时不该出现排版引擎。
        # Importing the C++ alone must not show the layout engine.
        assert not any(item.startswith("xr_syntax.format") for item in loaded), loaded


def test_top_level_names_reach_their_submodules() -> None:
    # 顶层包的每个公开名字仍可用，第一次使用才导入对应的子模块。
    # Every public name of the top-level package still works, and the submodule behind it is imported
    # on first use.
    import xr_syntax

    assert xr_syntax.CMakeDocument.__name__ == "CMakeDocument"
    assert xr_syntax.CppDocument.__name__ == "CppDocument"
    assert xr_syntax.CMakeFileBuilder.__name__ == "CMakeFileBuilder"
    assert xr_syntax.CppFileBuilder.__name__ == "CppFileBuilder"


def test_the_fragment_module_comes_in_only_when_a_fragment_is_used() -> None:
    # 只读地使用核心抽象时不加载片段模块；真的用到片段时它仍然可用。
    # Using the core abstractions read-only does not load the fragment module, which stays reachable
    # when a fragment is really used.
    assert "xr_syntax.core.fragment" not in loaded_modules("import xr_syntax.core")
    script = (
        "import xr_syntax\n"
        "import xr_syntax.core as core\n"
        "print(core.SyntaxFragment.__name__, core.SourceDraft.__name__)\n"
        "print(xr_syntax.SyntaxFragment.__name__, xr_syntax.SourceDraft.__name__)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.split() == [
        "SyntaxFragment",
        "SourceDraft",
        "SyntaxFragment",
        "SourceDraft",
    ]
