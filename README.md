# xr-syntax

C++ 源码的无损解析与结构查询 / Lossless parsing and structural queries of C++ source

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/xr-syntax)](https://pypi.org/project/xr-syntax/)
[![GitHub Repo](https://img.shields.io/github/stars/xrobot-org/xr-syntax?style=social)](https://github.com/xrobot-org/xr-syntax)
[![GitHub Issues](https://img.shields.io/github/issues/xrobot-org/xr-syntax)](https://github.com/xrobot-org/xr-syntax/issues)
[![test](https://github.com/xrobot-org/xr-syntax/actions/workflows/test.yml/badge.svg)](https://github.com/xrobot-org/xr-syntax/actions/workflows/test.yml)

xr-syntax 是 [XRobot](https://github.com/xrobot-org/XRobot) 和
[LibXR_CppCodeGenerator](https://github.com/xrobot-org/LibXR_CppCodeGenerator) 读取 C++ 源码时使用的
Python 库。它把源码解析为语法树，提供 include、类与构造函数、宏式调用、`User Code` 区域等结构查询；
语法树逐字节保留源码，输出与输入完全相同。两个工具共用的输出语言设置也在这里。

xr-syntax is the Python library [XRobot](https://github.com/xrobot-org/XRobot) and
[LibXR_CppCodeGenerator](https://github.com/xrobot-org/LibXR_CppCodeGenerator) use to read C++
source. It parses source into a syntax tree and answers structural queries: includes, classes and
their constructors, macro-style invocations and `User Code` regions. The syntax tree keeps every
byte, so its output equals its input. The output-language setting both tools share lives here too.

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

不完整的源码同样得到语法树，问题记录在 `diagnostics` 中，行号和列号从 0 开始：

Incomplete source gets a syntax tree too; the problems are recorded in `diagnostics`, with rows and
columns counted from 0:

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

## 🌐 输出语言 / Output Language

`xrobot` 和 `libxr` 两个命令行工具用 `xr_syntax.i18n` 选择输出语言：环境变量 `XR_LANG`、`LANGUAGE`、
`LC_ALL`、`LC_MESSAGES`、`LANG` 中第一个非空的值以 `zh` 开头时输出中文，否则输出英文。
`localize_argparse()` 让 argparse 自带的用法、标题和错误信息随之切换，含中文的帮助文字按终端列宽折行。

The `xrobot` and `libxr` command-line tools choose their output language with `xr_syntax.i18n`:
when the first non-empty of the environment variables `XR_LANG`, `LANGUAGE`, `LC_ALL`,
`LC_MESSAGES` and `LANG` starts with `zh`, the output is Chinese, otherwise English.
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
| `xr_syntax.i18n`：`tr()`、`chinese()`、`localize_argparse()` | 输出语言 | Output language |

设计见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，验证数据见 [docs/VALIDATION.md](docs/VALIDATION.md)。

The design is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), the validation in
[docs/VALIDATION.md](docs/VALIDATION.md).

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
