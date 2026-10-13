# 架构 / Architecture

## 语法树 / Syntax Tree

语法树分两层。green 层保存源码内容：`GreenNode` 保存带字段名的子元素，`GreenToken` 保存记号，`GreenTrivia`
保存空白和换行。green 元素只有类型、文字和字节宽度，不含父节点和位置，文字相同的叶子在多次解析之间共享。

The syntax tree has two layers. The green layer stores the source content: `GreenNode` holds child
elements with field names, `GreenToken` holds tokens and `GreenTrivia` holds whitespace and line
breaks. Green elements have only a kind, text and byte width, without parent or position, and
leaves with the same text are shared across parses.

red 层是某个 `SyntaxTree` 快照上的视图：`SyntaxNode`、`SyntaxToken`、`SyntaxTrivia` 在 green 元素之上
补充父节点、序号、字段名和字节范围，并提供 `child_by_field()` 和按类型筛选的 `descendants()`。

The red layer is a view on one `SyntaxTree` snapshot: `SyntaxNode`, `SyntaxToken` and
`SyntaxTrivia` add the parent, index, field name and byte span to the green elements, and provide
`child_by_field()` and `descendants()` filtered by kind.

## 无损解析 / Lossless Parsing

每次解析结束时，`CppParser` 检查语法树输出的字节与输入相同，不同时抛出 `AssertionError`。解析器只对能识别的
部分建立结构，其余源码作为记号和空白留在所在节点中；不完整的源码同样如此，问题记录为诊断。文字输入按 UTF-8
编码，无法解码的字节用 surrogateescape 保留。

At the end of every parse, `CppParser` checks that the bytes the syntax tree renders equal the
input and raises `AssertionError` otherwise. The parser builds structure only where it recognizes
it; the rest of the source stays in its node as tokens and whitespace. Incomplete source is handled
the same way, with the problems recorded as diagnostics. Text input is encoded as UTF-8, and bytes
that do not decode are kept through surrogateescape.

## 词法 / Lexing

词法器对整个文件调用一次正则 `findall` 切出全部 lexeme，结果是文字、类型和字节位置的并列数组。原始字符串的
结束符取决于分隔符，在 Python 里扫描，之后重新切分到与原结果对齐为止。lexeme 的类型、是否有效和 green 叶子
按文字缓存（不超过 64 个字符的文字）；缓存超过 10 万项时，在下一次扫描开始前清空。

The lexer splits the whole file into lexemes with one regular-expression `findall` call; the result
is parallel arrays of text, kind and byte position. A raw string ends at a delimiter-dependent
sequence, so it is scanned in Python, and lexing restarts after it until it lines up with the
original result again. The kind, significance and green leaf of a lexeme are cached by text (texts
of at most 64 characters); a cache past 100,000 entries is emptied before the next pass.

未闭合的块注释和原始字符串延伸到文件末尾并给出诊断；未闭合的引号只到行尾，`#error` 和 `#if 0` 中不成对的
撇号因此不影响后面的代码。`template <typename T = A<int>>` 末尾的 `>>` 拆成两个 `>`，分别结束默认值和参数
列表。

An unclosed block comment or raw string runs to the end of the file with a diagnostic; an unclosed
quote runs only to the end of its line, so an unpaired apostrophe in `#error` or `#if 0` leaves the
code after it alone. The `>>` at the end of `template <typename T = A<int>>` is split into two `>`,
one ending the default and one ending the parameter list.

## 结构解析 / Structural Parsing

结构解析在有效 lexeme（不是空白和注释）的位置数组上进行，已配对的括号组整组跳过。一个作用域内依次识别预处理
行、模板、类、命名空间、`extern "C"` 块和访问标签，其余部分按顶层的 `;` 或语句块切成单元，再把单元分为控制
语句、`case` 标签、函数、声明和表达式语句。

Structural parsing works on the position array of significant lexemes (neither whitespace nor
comments) and skips paired delimiter groups as a whole. Within a scope it recognizes preprocessor
lines, templates, classes, namespaces, `extern "C"` blocks and access labels in turn, cuts the rest
into units at top-level `;` or blocks, and sorts the units into control statements, `case` labels,
functions, declarations and expression statements.

分类只看记号本身，不做名字查找。C++ 需要名字查找才能确定的写法按以下规则处理：在命名空间和类中，括号里像
参数声明时 `Foo f(Bar);` 是函数声明；在函数体内，`a * b;` 这样的语句只有开头的名字以大写字母开头、带 `::`
或以 `_t` 结尾时才算声明。

Classification looks at the tokens alone, without name lookup. Forms that C++ resolves by name
lookup follow these rules: in a namespace or class, `Foo f(Bar);` is a function declaration when
the parentheses look like parameter declarations; in a function body, a statement such as
`a * b;` counts as a declaration only when its leading name starts with an upper-case letter,
holds `::` or ends in `_t`.

作用域和表达式的嵌套层数有上限，按调用时剩余的 Python 递归深度计算，最多 100 层；实际源码最深约 22 层
（CMSIS DSP）。更深的部分保持为未结构化的源码并给出诊断。`else if` 链和不带花括号的嵌套语句用循环处理，
长度不受这个上限影响。

Scope and expression nesting has a limit computed from the Python recursion depth left at the
call, at most 100 levels; real source nests about 22 levels at most (CMSIS DSP). Deeper source stays
unstructured with a diagnostic. `else if` chains and nested statements without braces are handled
in a loop, so their length is not bound by this limit.

## 查询 / Queries

视图从语法树的字段读取结构：include 的路径，类的名字、成员、访问级别和外层模板的参数，函数参数的名字、类型
和默认值。`invocation_views()` 和词法查询在 lexeme 上工作，`XR_REGISTER(...)` 这类宏式调用因此不必是合法的
C++ 表达式。`user_regions()` 按成对的注释标记找到区域；`replace_region_body()` 替换区域内的字节后用同一个解析器
重新解析，返回新的文档。

The views read structure from the fields of the syntax tree: the path of an include; the name,
members, access levels and enclosing template parameters of a class; the names, types and defaults
of function parameters. `invocation_views()` and the lexical queries work on lexemes, so a
macro-style invocation such as `XR_REGISTER(...)` need not be a valid C++ expression.
`user_regions()` finds regions by their paired comment markers; `replace_region_body()` replaces
the bytes inside a region, reparses with the same parser and returns a new document.

## 并发 / Concurrency

`CppParser` 不保存状态，每次解析使用自己的结构解析器，同一个 `CppParser` 可以被多个线程同时使用。文档和语法树
不可变。

`CppParser` keeps no state and every parse uses its own structural parser, so threads can share
one `CppParser`. Documents and syntax trees are immutable.

## CMake 前端 / CMake Frontend

CMake 前端（`xr_syntax.cmake`）与 C++ 前端共用同一个不可变语法模型、同一套结构化编辑和同一套区域规则。
`CMakeParser` 分两阶段解析：第一阶段把文件线性切成命令、注释和 trivia；第二阶段把成对的块命令
（`if`/`foreach`/`while`/`function`/`macro`）与其结束命令递归组合成 `if_condition`、`foreach_loop`、
`while_loop`、`function_def`、`macro_def` 节点。参数按写法分成 `quoted_argument`、`bracket_argument` 和
`unquoted_argument`；行注释在行末换行之前结束，CRLF 的 `\r` 属于换行而不是注释，因此区域的 body span 落在整行
之后。解析同样断言渲染出的字节与输入相同。

`CMakeDocument` 提供命令视图（`command_views()`，块内的命令也在内）、顶层语句（`top_level_statements()`，
带紧邻上方的注释范围）、注释、User Code 区域和语句/参数编辑。块命令被组合成 `if_condition` 等节点，随语法树
遍历即可取到。`CMakeFileBuilder` 把生成的 CMake 拼成整份文件，在 `build()` 时只解析一次。

The CMake frontend (`xr_syntax.cmake`) shares one immutable syntax model, one structural editing model
and one region rule set with the C++ frontend. `CMakeParser` parses in two stages: the first cuts the
file into commands, comments and trivia linearly; the second groups paired block commands
(`if`/`foreach`/`while`/`function`/`macro`) with their end command into `if_condition`,
`foreach_loop`, `while_loop`, `function_def` and `macro_def` nodes. Arguments are split into
`quoted_argument`, `bracket_argument` and `unquoted_argument` by their spelling; a line comment ends
before the line ending, and the `\r` of a CRLF belongs to the line ending rather than the comment, so
a region's body span starts after the whole line. The parse asserts the same lossless round-trip as
C++.

`CMakeDocument` offers command views (`command_views()`, commands inside blocks included), top-level
statements (`top_level_statements()`, with the span of the comments directly above), comments, User
Code regions, and statement and argument edits. Block commands are grouped into nodes such as
`if_condition`, which walking the syntax tree finds. `CMakeFileBuilder` assembles generated CMake into
a whole file and parses it once in `build()`.

## 区域 / Regions

两种语言共用 `core.document.SyntaxDocument` 里的配对与校验规则，只在注释语法和标记正则上不同。配对按栈进行：
`Begin A / End B / End A` 仍得到区域 A（名字不匹配的 End 既不弹栈也不产生区域），嵌套按源码顺序配对，同名嵌套
按栈配对，未配对的 Begin 与孤立的 End 不产生区域，区域按 begin 的位置排序。

`replace_region_body()` 校验区域属于当前快照、body span 与两条标记一致且不越界，然后只替换 body 的字节并用同一
个解析器重新解析；CRLF 与非 UTF-8 字节（surrogateescape）原样保留。C++ 的标记是
`/* User Code Begin <name> */`，CMake 的是 `# User Code Begin <name>`，两者都区分大小写。

Both languages share the pairing and validation rules in `core.document.SyntaxDocument` and differ only
in comment syntax and marker patterns. Pairing uses a stack: `Begin A / End B / End A` still yields
region A (an End with another name neither pops nor produces a region), nesting pairs in source order,
a nested duplicate name pairs through the stack, an unpaired Begin and a lone End produce no region,
and regions sort by the position of their begin.

`replace_region_body()` verifies that the region belongs to the current snapshot, that its body span
matches the two markers and that it stays inside the source, then replaces only the body bytes and
reparses with the same parser; CRLF and bytes that are not UTF-8 (surrogateescape) are kept as they
are. The C++ marker is `/* User Code Begin <name> */` and the CMake one is `# User Code Begin <name>`;
both are case-sensitive.

## 片段与编辑 / Fragments and Edits

green 元素不带位置、不可变，因此可以跨快照复用；它也不带语言，跨语言拼接无法从元素本身发现。`SyntaxFragment`
与 `SourceDraft` 因此各带一个语言标识：`SyntaxTree.replace()` 只接受本快照的
元素，或语言匹配的片段；同语言、另一份快照的元素允许（green 无位置，拼接安全），
跨语言一律拒绝，裸 green 元素也拒绝并要求调用方用 `SyntaxFragment` 显式标注语言。

底层编辑只沿目标的结构路径重建祖先链，路径之外的 green 子树继续复用原对象；它不重新解析，因此新快照的诊断是
"未验证"。`diagnostic_state` 区分三种情况：`clean`、`diagnosed` 和 `unknown`；`diagnostics` 为空元组本身不区分
"没有问题"和"未验证"。解析得到的快照，以及 `replace_region_body()`、CMake 按行的 `insert_after()` 与 `remove_command()`
编辑后的快照（它们改源码后重新解析）总是可信的。

Green elements carry no position and are immutable, so they can be reused across snapshots; they also
carry no language, so a cross-language splice cannot be detected from the element itself.
`SyntaxFragment` and `SourceDraft` therefore carry a language tag: `SyntaxTree.replace()` accepts only elements of this snapshot or fragments whose language matches; an element of the same language from another snapshot is allowed (green carries no
position, so the splice is safe), a different language is always refused, and a bare green element is
refused too, asking the caller to state the language through a `SyntaxFragment`.

A low-level edit rebuilds only the ancestor chain of the target path and keeps reusing the green
subtrees outside it; it does not reparse, so the new snapshot's diagnostics are "unverified".
`diagnostic_state` tells `clean`, `diagnosed` and `unknown` apart; an empty `diagnostics` alone does
not tell "no problem" from "not verified". A snapshot from a parse, and one from
`replace_region_body()` or from the line-based CMake `insert_after()` and `remove_command()`, which edit
the source and parse it again, are always trustworthy.

## 排版与生成 / Layout and Generation

`xr_syntax.format` 是 clang-format 的模拟，不是通用格式化器：它按 LibXR 的 `.clang-format`（Google、列宽 90、
Allman）排版生成器写出的语句形式。`layout_statement()` 接受一条 `头部(参数, ...);` 语句，参数是不可拆分的文本
或嵌套的花括号列表，取断行代价最小的排版；`layout_value()`、`layout_declaration()`、`layout_call()`、
`layout_macro()`、`sort_includes()` 和 `wrap_comment()` 先把值文本拆成花括号列表、调用和指定初始化项，再按
clang-format 的填行、对齐、列对齐（Regroup 与 ReflowComments）规则排版。运行时不调用 clang-format：版本不同
输出就可能不同，测试因此用固定版本核对。

`CppFileBuilder` 与 `CMakeFileBuilder` 累积 draft，在 `build()` 时把整份源码解析一次；`require_clean=True`
要求生成结果没有解析诊断。文件含用户手写代码（User Code 区域）时不用 `require_clean`：那里的内容不受生成器
控制，它自身的诊断不该让生成失败。

`xr_syntax.format` emulates clang-format rather than formatting in general: it lays out the statement
forms the generators write, in LibXR's `.clang-format` (Google based, column limit 90, Allman).
`layout_statement()` takes one ``head(argument, ...);`` statement whose arguments are unbreakable text
or nested brace lists and picks the cheapest set of breaks; `layout_value()`, `layout_declaration()`,
`layout_call()`, `layout_macro()`, `sort_includes()` and `wrap_comment()` first split value text into
brace lists, calls and designated entries and then follow clang-format's fill, alignment and column
rules (Regroup and ReflowComments). clang-format is not called at run time, because another version
may format differently, so the tests check against a pinned version.

`CppFileBuilder` and `CMakeFileBuilder` accumulate drafts and parse the whole source once in
`build()`; `require_clean=True` requires the result to have no parse diagnostics. A file holding
hand-written user code (a User Code region) does not use `require_clean`: that content is outside the
generator's control and its own diagnostics must not fail a generation.
