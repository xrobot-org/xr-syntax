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
