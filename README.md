# XR Syntax

`xr-syntax` 是 XRobot / LibXR Python 工具使用的**结构化源码解析、修改与代码生成基础库**。

它解决的是源码层问题：

- 读取已有 C++ / CMake；
- 保留原始空白、换行、注释和用户代码；
- 按函数、类、调用、变量、命令等结构查询；
- 对指定结构进行不可变编辑；
- 用同一套模型生成新的 C++ / CMake；
- 给 XRobot、LibXR_CppCodeGenerator 提供统一 backend。

它**不是 C++ 编译器**，不会自己做 name lookup、overload resolution、template instantiation 或 type inference。

最基本的不变量是：

```python
document = CppDocument.parse(source)
assert document.render_bytes() == source
```

即使 parser 对某段源码只能保守地表示，原始源码也不能因为解析而丢失。

---

## 安装

支持 Python 3.10–3.14，与 XRobot 和 LibXR_CppCodeGenerator 的 Python 包保持一致。

```bash
pip install xr-syntax
```

从源码安装：

```bash
git clone https://github.com/xrobot-org/xr-syntax.git
cd xr-syntax
pip install .
```

开发环境：

```bash
pip install -e ".[dev]"
```

当前基础包没有第三方 runtime dependency；C++ 与 CMake parser 都包含在包内。

---

## 包结构

```text
src/xr_syntax/
├── core/       # 通用不可变 syntax tree、span、grammar、rewrite
├── cpp/        # C++ lexer/parser/query/view/factory/builder
├── cmake/      # CMake parser/query/view/factory/builder
└── format/     # 新生成源码使用的 layout IR
```

第一轮 code review 建议先看：

```text
docs/REVIEW_GUIDE.md
```

---

# C++：读取已有源码

## 解析

```python
from xr_syntax.cpp import CppDocument

source = b"""
#include "device.hpp"

static Device device;

void app_main() {
  XR_REGISTER(device, Base);
}
""".lstrip()

document = CppDocument.parse(source)

assert document.render_bytes() == source
```

`CppDocument` 是一个不可变源码 snapshot。

---

## 查询 include

```python
includes = document.include_views()

assert includes[0].header == "device.hpp"
assert includes[0].system is False
```

对于：

```cpp
#include <vector>
```

对应：

```python
include.header == "vector"
include.system is True
```

---

## 查询函数

```python
function = document.function_views("app_main")[0]

print(function.name)
print(function.parameters)
print(function.body)
```

如果需要底层 syntax node：

```python
document.functions("app_main")
```

---

## 查询函数调用

例如：

```cpp
XR_REGISTER(device, LibXR::GPIO);
```

可以直接查询：

```python
calls = document.call_views("XR_REGISTER")

for call in calls:
    print(call.callee)
    print([argument.text for argument in call.arguments])
```

输出参数仍然保持源码层表示：

```text
device
LibXR::GPIO
```

---

## 查询变量

```python
all_variables = document.variable_views()

globals_ = document.variable_views(
    global_scope=True,
)

locals_ = document.variable_views(
    global_scope=False,
)
```

每个 variable view 可以读取：

```python
variable.name
variable.base_type
variable.storage
variable.qualifiers
variable.initializer
variable.global_scope
```

这里提供的是**源码结构信息**，不是编译器语义。

它不会判断：

- typedef 展开后的最终类型；
- 某个 constructor call 选择哪个 overload；
- template 实例化结果。

---

## 查询 class / constructor

```python
clazz = document.class_views("CameraBase")[0]

constructors = clazz.constructors(
    public_only=True,
    callable_only=True,
)

for constructor in constructors:
    print(constructor.name)
    print(constructor.parameters)
```

例如：

```cpp
CameraBase(const CameraBase&) = delete;
```

仍然会被 syntax tree 表示，但 `callable_only=True` 会把它从“可调用构造函数”列表中过滤掉。

析构函数和 `operator=` 不会被误识别成 constructor。

---

# C++：修改已有源码

`CppDocument` 不原地修改。

所有 edit 都返回新 document：

```python
from xr_syntax.cpp import CppDocument, CppFactory

document = CppDocument.parse(
    '#include "a.hpp"\n'
    'void app_main() {}\n'
)

factory = CppFactory()

changed = document.insert_after(
    document.includes()[0],
    factory.include("b.hpp"),
)

assert document.render() == (
    '#include "a.hpp"\n'
    'void app_main() {}\n'
)

assert changed.render() == (
    '#include "a.hpp"\n'
    '#include "b.hpp"\n'
    'void app_main() {}\n'
)
```

高层 edit 完成后会重新 parse，保证 field、diagnostic 和 error-recovery 结构与新源码一致。

---

# User Code / format / lint 区域

STM32 常见区域：

```cpp
/* User Code Begin 3 */
custom_code();
/* User Code End 3 */
```

不再需要自己写 regex：

```python
region = document.user_regions()[0]

print(region.name)
print(region.body_text)
```

只替换区域内部：

```python
changed = document.replace_region_body(
    region,
    "\ncustom_code();\nother_code();\n",
)
```

同样支持：

```cpp
// clang-format off
...
// clang-format on
```

以及：

```cpp
// NOLINTBEGIN
...
// NOLINTEND
```

对应：

```python
document.format_regions()
document.lint_regions()
```

---

# C++：生成源码

读取和生成使用同一个 syntax model。

## FileBuilder

```python
from xr_syntax.cpp import CppFileBuilder

builder = CppFileBuilder()

builder.include("device.hpp")
builder.raw("\nstatic Device device;\n")

document = builder.build()

print(document.render())
```

## Function / block builder

```python
builder = CppFileBuilder()

entry = builder.function(
    "void",
    "XRobotMain",
    prefix=["[[noreturn]]"],
)

entry.parameter(
    "LibXR::GPIO&",
    "led",
)

entry.body.variable(
    "BlinkLED",
    "blink",
    initializer="BlinkLED(led, 250)",
    storage=["static"],
)

entry.body.call(
    "Run",
    ["blink"],
)

document = builder.build()
```

builder 最终返回的仍然是 parser-backed `CppDocument`，不会产生第二套“生成器 AST”。

---

# CMake

CMake frontend 与 C++ 共用同一套 core：

- immutable document；
- source span；
- grammar contract；
- rewrite；
- builder；
- layout。

## 读取

```python
from xr_syntax.cmake import CMakeDocument

source = b"""
project(Demo)
add_library(foo STATIC foo.cpp)
""".lstrip()

document = CMakeDocument.parse(source)

assert document.render_bytes() == source

library = document.command_views(
    "add_library"
)[0]

assert library.name == "add_library"

assert [
    argument.text
    for argument in library.arguments
] == [
    "foo",
    "STATIC",
    "foo.cpp",
]
```

## 生成

```python
from xr_syntax.cmake import CMakeFileBuilder

builder = CMakeFileBuilder()

builder.command(
    "project",
    ["Demo", "LANGUAGES", "CXX"],
)

builder.command(
    "add_library",
    ["foo", "STATIC", "foo.cpp"],
)

document = builder.build()

print(document.render())
```

---

# Green / Red syntax tree

## Green

Green tree 只保存结构：

- kind；
- text；
- trivia；
- children；
- field。

它不保存：

- parent；
- absolute offset；
- owning document。

这样未修改 subtree 可以在多个 immutable snapshot 之间复用。

## Red

Red view 为某个具体 snapshot 增加：

- parent；
- child index；
- field；
- byte span；
- structural path。

因此：

```text
Green = 可共享的不可变结构
Red   = 某个 snapshot 中的位置视图
```

---

# 无损表示

parser 不一定会把所有字节都作为结构节点。

例如：

- 空白；
- 某些注释；
- parser 保守保留的未知片段；
- 不完整源码。

`xr-syntax` 会把无法安全细分的内容继续作为 source-preserving element 保留下来。

最终必须满足：

```python
document.render_bytes() == input_bytes
```

diagnostic 可以存在，静默丢源码不允许存在。

---

# 排版

已有源码的 `render()` 与新源码的 formatting 是两件事。

```text
render()
→ 保留已有 syntax / trivia

layout IR
→ 决定新生成源码如何缩进和折行
```

layout IR 包含：

```text
Text
Concat
Group
Indent
Line
SoftLine
HardLine
IfBreak
```

这样 XRobot / LibXR_CppCodeGenerator 不需要再在业务逻辑里写行宽判断。

---

# 明确不做什么

`xr-syntax` 负责源码结构，不负责 C++ compiler semantics。

它不会自己实现：

- name lookup；
- overload resolution；
- template instantiation；
- type inference；
- constant evaluation；
- ABI；
- XRobot Module 依赖绑定；
- `XR_REGISTER` 的业务语义。

例如：

> “某个 Module constructor 应该绑定哪个 LibXR view？”

仍然属于 XRobot 的 domain logic。

---

# Python 支持

与 XRobot、LibXR_CppCodeGenerator 保持一致：

```text
Python 3.10
Python 3.11
Python 3.12
Python 3.13
Python 3.14
```

CI 在 Linux 和 Windows 上覆盖以上版本。

---

# 注释规范

项目要求：

- 每个 Python 文件都有模块说明；
- 每个 class 都有说明；
- 每个函数 / 方法（包含私有函数）都有中文说明；
- 关键 parser / rewrite 算法使用行内注释解释“为什么”，而不是逐行复述代码。

CI 中的：

```text
tools/check_bilingual_docs.py
```

会自动检查源码、测试和工具脚本的文档覆盖。

---

# 验证

当前验证包括：

- Linux / Windows；
- Python 3.10–3.14；
- pytest；
- ruff；
- mypy strict；
- build / wheel / sdist；
- twine check；
- standalone wheel smoke；
- C++ corpus round-trip；
- CMake corpus round-trip；
- XRobot constructor parity；
- XR_REGISTER corpus probe。

详细数据见：

```text
docs/VALIDATION.md
```

---

# 开发

```bash
pip install -e ".[dev]"
```

常用检查：

```bash
python -m pytest
python tools/check_bilingual_docs.py
python -m ruff check src tests tools
python -m mypy src
python -m build
```

---

# Review

第一轮 review 请先看：

```text
docs/REVIEW_GUIDE.md
```

它会告诉你哪些文件决定整体架构，哪些 grammar/test/tool 文件可以后看。
