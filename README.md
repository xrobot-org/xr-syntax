# xr-syntax

C++ 与 CMake 源码的无损解析、结构编辑与生成 / Lossless parsing, structural editing and code
generation of C++ and CMake source

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/xrobot-org/xr-syntax/blob/master/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/xr-syntax)](https://pypi.org/project/xr-syntax/)
[![GitHub Repo](https://img.shields.io/github/stars/xrobot-org/xr-syntax?style=social)](https://github.com/xrobot-org/xr-syntax)
[![GitHub Issues](https://img.shields.io/github/issues/xrobot-org/xr-syntax)](https://github.com/xrobot-org/xr-syntax/issues)
[![test](https://github.com/xrobot-org/xr-syntax/actions/workflows/test.yml/badge.svg)](https://github.com/xrobot-org/xr-syntax/actions/workflows/test.yml)

xr-syntax 是 [XRobot](https://github.com/xrobot-org/XRobot) 和
[LibXR_CppCodeGenerator](https://github.com/xrobot-org/LibXR_CppCodeGenerator) 读写 C++ 与 CMake 源码
时使用的 Python 库。它把源码解析为语法树，提供 include、类与构造函数、宏式调用、`User Code` 区域等
结构查询；按 LibXR 的 clang-format 风格排版生成的代码；并用文件构建器把生成结果拼成整份文件。语法树
逐字节保留源码，输出与输入完全相同。两个工具共用的输出语言设置也在这里。

xr-syntax is the Python library [XRobot](https://github.com/xrobot-org/XRobot) and
[LibXR_CppCodeGenerator](https://github.com/xrobot-org/LibXR_CppCodeGenerator) use to read and write
C++ and CMake source. It parses source into a syntax tree and answers structural queries: includes,
classes and their constructors, macro-style invocations and `User Code` regions. It lays out
generated code in the clang-format style of LibXR, and file builders assemble the result into whole
files. The syntax tree keeps every byte, so its output equals its input. The output-language setting
both tools share lives here too.

---

## 🔧 安装 / Installation

```bash
pip install xr-syntax
```

从源码安装 / Install from source:

```bash
git clone https://github.com/xrobot-org/xr-syntax.git
cd xr-syntax
pip install .
```

需要 Python 3.10 或更高版本，没有其他依赖。

Requires Python 3.10 or later and has no other dependencies.

---

## 📚 基本概念 / Concepts

以一个 STM32 工程的入口源文件 `app_main.cpp` 为例：

Take the entry source `app_main.cpp` of an STM32 project as an example:

```cpp
#include "app_main.h"

#include "libxr.hpp"

/* User Code Begin 1 */
static int blink_period = 250;
/* User Code End 1 */

class BlinkLED {
 public:
  BlinkLED(LibXR::GPIO& led, int period = 250) : led_(led), period_(period) {}
  BlinkLED(const BlinkLED&) = delete;

 private:
  LibXR::GPIO& led_;
  int period_;
};

extern "C" void app_main(void) {
  static LibXR::STM32GPIO led(LED_GPIO_Port, LED_Pin);
  XR_REGISTER(led, LibXR::GPIO);
  XR_REGISTER(spi1, LibXR::SPI);
}
```

| 概念 Concept | 在这个例子里 | In this example |
| --- | --- | --- |
| 文档 Document | `CppDocument.parse()` 得到的不可变快照；`render_bytes()` 输出的字节与文件相同 | The immutable snapshot `CppDocument.parse()` returns; `render_bytes()` gives back the bytes of the file |
| 视图 View | `include_views()` 给出两个 include，`class_views("BlinkLED")` 给出类及其构造函数，`invocation_views("XR_REGISTER")` 给出两次注册及其实参 | `include_views()` gives the two includes, `class_views("BlinkLED")` the class and its constructors, `invocation_views("XR_REGISTER")` the two registrations and their arguments |
| 区域 Region | `/* User Code Begin 1 */` 与 `/* User Code End 1 */` 之间的内容 | The text between `/* User Code Begin 1 */` and `/* User Code End 1 */` |
| 语法树 Syntax tree | 文档的 `root`，节点有类型、源码文字、字节范围和字段，例如类的 `name` 和 `body` | The document's `root`; nodes have a kind, source text, byte span and fields, such as the `name` and `body` of the class |
| 诊断 Diagnostic | 源码不完整时（例如缺少右括号）记录的问题及其行列；源码照样完整保留 | A problem and its row and column, recorded when the source is incomplete (a missing closing parenthesis, for example); the source is still kept whole |

---

## 🔍 查询 / Queries

视图按源码中写的内容给出结构，参数类型和默认值都是源码文字：

Views give the structure as written in the source; parameter types and defaults are source text:

```python
from pathlib import Path

from xr_syntax.cpp import CppDocument

document = CppDocument.parse(Path("app_main.cpp").read_bytes(), source_name="app_main.cpp")

for include in document.include_views():
    print(include.header, include.system)
blink = document.class_views("BlinkLED")[0]
for constructor in blink.constructors(callable_only=True):
    print([(item.name, item.type, item.default) for item in constructor.parameters])
for invocation in document.invocation_views("XR_REGISTER", template_angles=True):
    print(invocation.line, invocation.arguments)
```

```text
app_main.h False
libxr.hpp False
[('led', 'LibXR::GPIO&', None), ('period', 'int', '250')]
21 ('led', 'LibXR::GPIO')
22 ('spi1', 'LibXR::SPI')
```

`callable_only=True` 去掉了 `= delete` 的拷贝构造函数；`public_only=True` 只保留 `public` 下的构造函数。
`template_angles=True` 让 `std::array<int, 2>` 这样的模板实参保持为一项。

`callable_only=True` leaves out the `= delete` copy constructor; `public_only=True` keeps only the
constructors under `public`. `template_angles=True` keeps a template argument such as
`std::array<int, 2>` as one item.

---

## 🌳 语法树 / Syntax Tree

视图之外，可以直接遍历语法树，按节点类型筛选：

Beyond the views, the syntax tree can be walked directly and filtered by node kind:

```python
for node in document.root.descendants(kinds={"class_specifier", "function_definition"}):
    print(node.kind, node.span.start, node.text.splitlines()[0])
print(document.render_bytes() == Path("app_main.cpp").read_bytes())
```

```text
class_specifier 123 class BlinkLED {
function_definition 151 BlinkLED(LibXR::GPIO& led, int period = 250) : led_(led), period_(period) {}
function_definition 317 extern "C" void app_main(void) {
True
```

不完整的源码同样得到语法树，问题记录在 `diagnostics` 中，行号和列号从 0 开始（以下为英文环境
`XR_LANG=en` 的输出）：

Incomplete source gets a syntax tree too; the problems are recorded in `diagnostics`, with rows and
columns counted from 0 (output with `XR_LANG=en`):

```python
broken = CppDocument.parse("void f() {\n  call(1,\n}\n")
for diagnostic in broken.diagnostics:
    print(diagnostic.message, diagnostic.start_point)
print(broken.render() == "void f() {\n  call(1,\n}\n")
```

```text
unmatched closing delimiter SourcePoint(row=2, column=0)
unclosed delimiter SourcePoint(row=0, column=9)
unclosed delimiter SourcePoint(row=1, column=6)
True
```

`SyntaxTree.diagnostics` 解析后是诊断元组；底层结构编辑 `SyntaxTree.replace()` 只重建语法树、
不重新解析，此时它是 `None`，表示"未验证"——既不能读作"没有问题"，也不能读作"有诊断"。文档层的 `diagnostics` 属性把 `None` 显示为空元组；需要区分这两种情况时读
`SyntaxTree.diagnostic_state`（`clean`、`diagnosed` 或 `unknown`）。

`SyntaxTree.diagnostics` holds the diagnostics after a parse; the low-level structural edit
`SyntaxTree.replace()` rebuilds the tree without reparsing, so it is `None` then, meaning "unverified": it must be read neither as "no diagnostics" nor as "has
diagnostics". The `diagnostics` property of the document shows `None` as an empty tuple; read
`SyntaxTree.diagnostic_state` (`clean`, `diagnosed` or `unknown`) when the difference matters.

`CppRegion` 现在是 `SourceRegion` 的别名，两者等价；`SourceRegion` 在 `xr_syntax.core` 里，C++ 与
CMake 共用。判断区域属于哪一门前端读 `begin.tree.language`。

`CppRegion` is now an alias of `SourceRegion` and the two are equivalent; `SourceRegion` lives in
`xr_syntax.core` and is shared by C++ and CMake. Read `begin.tree.language` to tell which frontend a
region belongs to.

---

## ✏️ User Code 区域 / User Code Regions

`replace_region_body()` 替换区域内的文字，返回新的文档，原文档不变：

`replace_region_body()` replaces the text inside a region and returns a new document; the original
stays unchanged:

```python
region = document.user_regions()[0]
print(region.name, repr(region.body_text))
changed = document.replace_region_body(region, "\nstatic int blink_period = 500;\n")
print(changed.render().splitlines()[5])
print(document.render().splitlines()[5])
```

```text
1 '\nstatic int blink_period = 250;\n'
static int blink_period = 500;
static int blink_period = 250;
```

---

## 🔤 词法查询 / Lexical Queries

不需要语法树时，词法查询直接处理源码文字，跳过注释和预处理行；字符串字面量整体是一个记号，其中的文字不算作标识符：

When no syntax tree is needed, the lexical queries work on source text directly and skip comments
and preprocessor lines; a string literal is one token as a whole, and the text inside it counts as
no identifier:

```python
from xr_syntax.cpp import code_tokens, identifier_occurrences, split_source_list

print(split_source_list("std::array<int, 2>, Type&", template_angles=True))
for item in identifier_occurrences('led.Write(on); // led\nlog("led");'):
    print(item.text, item.previous, item.following)
print([token.text for token in code_tokens("x = a<b>(1); // c")])
```

```text
('std::array<int, 2>', 'Type&')
led None .
Write . (
on ( )
log ; (
['x', '=', 'a', '<', 'b', '>', '(', '1', ')', ';']
```

---

## 🧱 CMake / CMake

CMake 前端与 C++ 前端共用同一套语法树、结构化编辑和区域规则。它识别命令、参数（引号、方括号和普通写法）、
注释，以及 `if`/`foreach`/`while`/`function`/`macro` 到各自结束命令的整块；User Code 区域写作
`# User Code Begin <name>` 与 `# User Code End <name>`。

The CMake frontend shares one syntax tree, one structural editing model and one region rule set with
the C++ frontend. It recognizes commands, arguments (quoted, bracketed and plain), comments, and whole
blocks from `if`/`foreach`/`while`/`function`/`macro` to their end command; a User Code region is
written `# User Code Begin <name>` and `# User Code End <name>`.

```python
from xr_syntax.cmake import CMakeDocument

document = CMakeDocument.parse(b'# ---- Project settings ----\nset(LIBXR_SYSTEM None)\n')
print([(view.name, [item.text for item in view.arguments]) for view in document.command_views()])
statement = document.top_level_statements()[0]
changed = document.replace_argument(statement.arguments[1], "FreeRTOS")
print(changed.render().splitlines()[1])
```

```text
[('set', ['LIBXR_SYSTEM', 'None'])]
set(LIBXR_SYSTEM FreeRTOS)
```

---

## 🖨️ 排版与生成 / Layout and Generation

`xr_syntax.format` 按 LibXR 的 clang-format 风格（Google、列宽 90、Allman）排版生成的代码，运行时不调用
clang-format：`layout_statement()` 排版一条语句，`layout_value()`、`layout_declaration()`、`layout_call()`、
`layout_macro()`、`sort_includes()` 和 `wrap_comment()` 排版值、声明、调用、宏、include 块和注释。测试用固定
版本的 clang-format 核对输出逐字节相同。

`xr_syntax.format` lays out generated code in the clang-format style of LibXR (Google based, column
limit 90, Allman) without calling clang-format at run time: `layout_statement()` lays out one
statement, and `layout_value()`, `layout_declaration()`, `layout_call()`, `layout_macro()`,
`sort_includes()` and `wrap_comment()` lay out values, declarations, calls, macros, include blocks and
comments. The tests check the output byte for byte against a pinned clang-format.

`CppFileBuilder` 与 `CMakeFileBuilder` 把生成结果拼成整份文件，`build()` 只解析一次，可以用
`require_clean=True` 要求生成结果没有解析诊断。

`CppFileBuilder` and `CMakeFileBuilder` assemble the result into a whole file; `build()` parses it
once, and `require_clean=True` requires the result to have no parse diagnostics.

```python
from xr_syntax.cmake import CMakeFileBuilder
from xr_syntax.cpp import CppFileBuilder

cpp = CppFileBuilder(header=True)
cpp.include("libxr.hpp")
cpp.raw("")
cpp.raw("static int blink_period = 250;")
print(cpp.build(require_clean=True).render())

cmake = CMakeFileBuilder()
cmake.comment("generated")
cmake.command("project", ["Demo", "LANGUAGES", "CXX"])
print(cmake.build(require_clean=True).render())
```

```text
#pragma once
#include "libxr.hpp"

static int blink_period = 250;

# generated
project(Demo LANGUAGES CXX)
```

---

## 🌐 输出语言 / Output Language

`xrobot` 和 `libxr` 两个命令行工具用 `xr_syntax.i18n` 选择输出语言：环境变量 `XR_LANG`、`LANGUAGE`、
`LC_ALL`、`LC_MESSAGES`、`LANG` 中第一个非空的值以 `zh` 开头时输出中文，否则输出英文；这些变量都未设置时，
Windows 上按系统界面语言选择。
`localize_argparse()` 让 argparse 自带的用法、标题和错误信息随之切换，含中文的帮助文字按终端列宽折行。

The `xrobot` and `libxr` command-line tools choose their output language with `xr_syntax.i18n`:
when the first non-empty of the environment variables `XR_LANG`, `LANGUAGE`, `LC_ALL`,
`LC_MESSAGES` and `LANG` starts with `zh`, the output is Chinese, otherwise English; when none of
them is set, Windows follows the system display language.
`localize_argparse()` makes argparse's own usage, headings and error messages follow, and wraps help
text holding Chinese by terminal column width.

```console
$ XR_LANG=zh python -c 'from xr_syntax.i18n import tr; print(tr("parse failed", "解析失败"))'
解析失败
```

---

## 🧩 接口一览 / API

| 接口 Interface | 说明 | Description |
| --- | --- | --- |
| `CppDocument.parse()` | 解析源码，得到文档 | Parse source into a document |
| `render()`、`render_bytes()` | 输出文档的源码 | Render the document's source |
| `root`、`diagnostics` | 语法树的根节点、解析时记录的问题 | The root of the syntax tree, the problems recorded while parsing |
| `include_views()`、`class_views()`、`invocation_views()` | 查询 include、类与构造函数、宏式调用 | Query includes, classes and constructors, macro-style invocations |
| `user_regions()`、`replace_region_body()` | 查询和替换 `User Code` 区域 | Query and replace `User Code` regions |
| `code_tokens()`、`identifier_occurrences()`、`split_source_list()`、`matching_delimiter()` | 词法查询 | Lexical queries |
| `CMakeDocument.parse()`、`command_views()`、`top_level_statements()`、`user_regions()`、`replace_region_body()`、`replace_argument()`、`replace_statement()`、`insert_after()`、`remove_command()` | CMake 文档、查询与编辑 | The CMake document, its queries and its edits |
| `xr_syntax.format`：`layout_statement()`、`layout_value()`、`layout_declaration()`、`layout_call()`、`layout_macro()`、`sort_includes()`、`wrap_comment()`、`Braces` | 按 LibXR 的 clang-format 风格排版生成的代码 | Lay out generated code in the clang-format style of LibXR |
| `CppFileBuilder`、`CMakeFileBuilder` | 拼装整份生成文件，并在构建时校验它能被解析 | Assemble a whole generated file and check at build time that it parses |
| `CppDocument.user_regions()`、`replace_region_body()` | 已有 C++ 文件的 `User Code` 区域 | The `User Code` regions of an existing C++ file |
| `SyntaxTree.replace()` | 底层结构编辑 | Low-level structural edit |
| `xr_syntax.i18n`：`tr()`、`chinese()`、`localize_argparse()` | 输出语言 | Output language |

设计见 [docs/ARCHITECTURE.md](https://github.com/xrobot-org/xr-syntax/blob/master/docs/ARCHITECTURE.md)，
验证数据见 [docs/VALIDATION.md](https://github.com/xrobot-org/xr-syntax/blob/master/docs/VALIDATION.md)。

The design is described in
[docs/ARCHITECTURE.md](https://github.com/xrobot-org/xr-syntax/blob/master/docs/ARCHITECTURE.md),
the validation in
[docs/VALIDATION.md](https://github.com/xrobot-org/xr-syntax/blob/master/docs/VALIDATION.md).

---

## 🧪 测试 / Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

CI 还运行 `ruff format --check`、`ruff check`、`mypy` 和 `tools/check_bilingual_docs.py`。

CI also runs `ruff format --check`, `ruff check`, `mypy` and `tools/check_bilingual_docs.py`.

---

## 📖 更多信息 / More Information

- [GitHub Repository](https://github.com/xrobot-org/xr-syntax)
- [Issue Tracker](https://github.com/xrobot-org/xr-syntax/issues)
- [XRobot 文档 / XRobot documentation](https://xrobot.work)
