# 验证 / Validation

## CI

CI 在 Linux 和 Windows 上用 Python 3.10 至 3.14 运行测试，与 XRobot、LibXR_CppCodeGenerator 支持的版本一致。
质量检查包括 `ruff format --check`、`ruff check`、`mypy --strict`、`tools/check_bilingual_docs.py`，以及 wheel
和 sdist 的打包检查。

CI runs the tests on Linux and Windows with Python 3.10 through 3.14, the versions XRobot and
LibXR_CppCodeGenerator support. The quality checks are `ruff format --check`, `ruff check`,
`mypy --strict`, `tools/check_bilingual_docs.py`, and packaging checks of the wheel and sdist.

## 解析器版本对比 / Comparing Parser Revisions

`tools/compare_parsers.py` 对同一批源码比较两个版本的解析结果。它从 git 取出 `--base`（以及可选的 `--head`）
版本的 `src`，省略 `--head` 时与工作区比较；每个文件的结果按先序列出全部 green 元素，再列出诊断的消息和字节
范围。有差异时打印前几个文件的差异并返回 1，解析抛出的异常也作为结果参与比较。

`tools/compare_parsers.py` compares the parsing results of two revisions on the same sources. It
takes `src` of the `--base` revision (and optionally of `--head`) from git and compares it with the
working tree when `--head` is omitted. Each file's result lists every green element in pre-order,
then the message and byte span of each diagnostic. On differences it prints the diffs of the first
files and returns 1; an exception raised by the parser is compared as a result too.

```bash
python tools/compare_parsers.py --base HEAD ../libxr ../BSP ../Modules
```

对比使用的语料是 libxr、BSP 和模块仓库中的 11,769 个 C/C++ 文件（242.8 MiB），其中包括 CMSIS、STM32 HAL、
FreeRTOS 和 Eigen。

The corpus used for comparisons is 11,769 C/C++ files (242.8 MiB) from libxr, the BSPs and the
modules, including CMSIS, the STM32 HAL, FreeRTOS and Eigen.

## CMake 往返 / CMake Round-Trip

`tools/roundtrip_cmake.py` 对一批 CMake 文件逐个解析、要求渲染出的字节与输入相同，并统计诊断。语料是各 BSP
仓库、libxr 与模块仓库中的全部 `CMakeLists.txt` 与 `*.cmake`（跳过构建目录）。

`tools/roundtrip_cmake.py` parses a set of CMake files one by one, requires the rendered bytes to equal
the input and counts diagnostics. The corpus is every `CMakeLists.txt` and `*.cmake` of the BSP
repositories, libxr and the module repositories, with build directories skipped.

```bash
python tools/roundtrip_cmake.py ../BSP ../libxr ../Modules
```

## 排版 / Layout

`tests/test_format_statement.py` 把随机生成的 400 条语句交给固定版本的 clang-format 排版，要求
`layout_statement()` 的断行逐行相同；`tests/test_format_value.py` 检查值、声明、调用、宏、注释和 include 的
排版结果。两个生成器自己的 clang-format 测试（生成结果经固定版本 clang-format 后逐字节不变）留在各自的仓库里，
是排版引擎替换后的验收门槛。

`tests/test_format_statement.py` hands 400 randomly generated statements to the pinned clang-format and
requires `layout_statement()` to break the lines exactly the same way; `tests/test_format_value.py`
checks the layout of values, declarations, calls, macros, comments and includes. The clang-format tests
of the two generators (their output is unchanged by the pinned clang-format) stay in their own
repositories and are the acceptance gate for replacing the layout engine.

## 结果记录 / Recorded Results

| 日期 Date | 改动 Change | 结果 Result |
| --- | --- | --- |
| 2026-10-01 | 解析器重写为单遍扫描 / Parser rewritten as one pass | 11,242 个文件的语法树和诊断与重写前完全一致；随后赋值改为右结合，938 个文件变化，全部是连续赋值 / Syntax trees and diagnostics of 11,242 files identical to the old parser; making assignment right-associative afterwards changed 938 files, all in runs of assignments |
| 2026-10-02 | 修正审查中发现的误读 / Fixes for misreadings found in review | 11,769 个文件全部解析并还原源码；9,801 个文件变化，主要是 124,793 个参数节点去掉了两端空白，以及 C 头文件 `extern "C"` 块中原先作为一个表达式的宏定义和声明被分别解析；抽查的语句级变化都更符合源码 / All 11,769 files parse and reproduce their source; 9,801 files change, mostly 124,793 parameter nodes losing their surrounding whitespace and the `extern "C"` blocks of C headers, whose defines and declarations were one expression before; sampled statement-level changes all read the source better |
| 2026-10-02 | 消融发现的修正 / Fixes found by ablation | 11,769 个文件全部解析；9,436 个文件变化：函数返回类型去掉结尾空白（102,963 处）、模板非类型参数名（19,835 处）、类外定义的限定名（5,364 处）、`do` 语句带上它的 `while (...);`（1,192 处）/ All 11,769 files parse; 9,436 files change: function return types without trailing whitespace (102,963), names of non-type template parameters (19,835), qualified names of out-of-class definitions (5,364), `do` statements taking their `while (...);` (1,192) |
| 2026-10-12 | CMake 前端加入 / CMake frontend added | 各 BSP、libxr 与模块仓库的 849 个 CMake 文件（2,609,578 字节）全部逐字节还原，0 个诊断、0 个失败（3.2 s）/ All 849 CMake files of the BSPs, libxr and the module repositories (2,609,578 bytes) round-trip byte for byte with 0 diagnostics and 0 failures (3.2 s) |
| 2026-10-12 | 排版引擎加入 / Layout engine added | 400 条随机语句与固定版本 clang-format 21.1.8 的断行逐行相同；值、声明、调用、宏、注释和 include 的排版与 clang-format 相同 / 400 random statements break exactly where clang-format 21.1.8 breaks them; the layout of values, declarations, calls, macros, comments and includes equals clang-format's |

2026-10-02 的修正同时用 XRobot（397 个测试）和 LibXR_CppCodeGenerator（201 个测试）的测试套件验证。在同一
进程中交替解析语料的十六分之一，解析时间增加约 1.5%，来自新解析出的 `extern "C"` 块内容。

The 2026-10-02 fixes were also verified with the test suites of XRobot (397 tests) and
LibXR_CppCodeGenerator (201 tests). Parsing a sixteenth of the corpus alternately in one process
takes about 1.5 % longer, spent on the newly parsed contents of `extern "C"` blocks.
