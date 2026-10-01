# 架构 / Architecture

## 语法树 / Syntax Tree

底层使用不可变 green tree 保存源码内容。`GreenNode` 保存 children，`GreenToken` 保存语法 token，`GreenTrivia` 保存空白和未分类源码。green 元素不保存 parent 和绝对位置。  
The immutable green tree stores source content. `GreenNode` owns children, `GreenToken` stores syntax tokens, and `GreenTrivia` keeps whitespace and unclassified source. Green elements do not store parents or absolute positions.

red view 在具体 `SyntaxTree` 快照上补充 parent、child index、field、byte offset 和 span。  
Red views add parent, child index, field, byte offset, and span for one `SyntaxTree` snapshot.

## 无损解析 / Lossless Parsing

C++ 和 CMake 都要求：  
Both C++ and CMake keep this invariant:

```python
tree = parser.parse(source)
assert tree.render_bytes() == source
```

parser 可以识别部分结构，也可以把暂时未细分的内容保存在 token/trivia 中；无论是否产生诊断，源码字节都必须保留。  
A parser may classify only part of a file and leave other text in tokens or trivia. Diagnostics do not change the byte-preservation rule.

## 编辑 / Editing

`SyntaxTree.replace/remove/insert_*` 只重建目标到根之间的 green 节点，其余子树继续复用。  
`SyntaxTree.replace/remove/insert_*` rebuilds only the green nodes between the edited element and the root; untouched subtrees are reused.

`CppDocument` 和 `CMakeDocument` 的高层编辑会重新解析修改后的源码，让 field 和 diagnostics 与新快照保持一致。  
High-level `CppDocument` and `CMakeDocument` edits reparse the modified source so fields and diagnostics match the new snapshot.

## C++ parser

C++ frontend 由 lexer、结构 parser 和 grammar contract 组成。lexer 保留换行、注释、literal、预处理内容和标点；结构 parser 在这些 lexeme 上建立 declaration、function、class、call、expression 等节点。  
The C++ frontend consists of a lexer, structural parser, and grammar contract. The lexer preserves line endings, comments, literals, preprocessor text, and punctuation; the structural parser builds declaration, function, class, call, expression, and related nodes over those lexemes.

lexer 用一次正则 `findall` 切出整个文件的 lexeme，结果以文本、kind 和字节位置的并列数组保存；文本相同的 green 叶子在多次解析之间共享。结构 parser 在有效 lexeme（非空白、非注释）的位置数组上扫描，已配对的括号组整组跳过。同一优先级的一串运算符用循环建树，左结合。  
The lexer splits a whole file into lexemes with one regular-expression `findall` call and keeps them as parallel arrays of text, kind, and byte position; green leaves with the same text are shared across parses. The structural parser scans the position array of significant lexemes (not whitespace, not comments) and skips paired delimiter groups as a whole. A run of operators of one precedence is built in a loop, left-associatively.

作用域和表达式的嵌套层数有上限：按调用时可用的 Python 递归深度计算，最多 100 层，实际源码最深约 22 层。更深的部分保留为未结构化源码并给出诊断，解析始终在 Python 递归上限之内完成。  
Scope and expression nesting has a limit computed from the Python recursion depth available at the call, at most 100 levels; real source nests about 22 levels at most. Deeper source stays unstructured with a diagnostic, so parsing always stays within the Python recursion limit.

## CMake parser

CMake frontend 直接解析 command、argument、comment 和成对 block，例如 `if()/endif()`、`function()/endfunction()`。它与 C++ frontend 一样包含在基础包中。  
The CMake frontend directly parses commands, arguments, comments, and paired blocks such as `if()/endif()` and `function()/endfunction()`. It ships in the base package together with the C++ frontend.

## Grammar contract

`LanguageGrammar` 保存 node kind、field、children 和 subtype 关系。C++ 使用项目内维护的 native contract；CMake 使用固定版本的 grammar metadata 生成同一种结构描述。  
`LanguageGrammar` stores node kinds, fields, child rules, and subtype relationships. C++ uses a native contract maintained in this project; CMake maps pinned grammar metadata into the same representation.

## Factory、Builder 与 formatter / Factory, Builder and Formatter

Factory 返回已经经过 parser 的 `SyntaxFragment`，用于独立片段校验和文档编辑。Builder 使用 `SourceDraft` 累积生成源码，在 `build()` 边界统一 parse 一次。  
Factories return parser-backed `SyntaxFragment` objects for standalone validation and document edits. Builders accumulate generated `SourceDraft` text and parse once at the `build()` boundary.

Builder 也可以接收同语言 `SyntaxFragment`。最终文档始终来自完整源码的 parser 结果，因此生成和读取使用同一套语法表示。  
Builders can also accept same-language `SyntaxFragment` objects. The final document always comes from parsing the complete generated source, so generation and parsing converge on the same syntax model.

`build(require_clean=True)` 会在最终 parser 产生 diagnostics 时拒绝结果；默认模式返回文档并保留 diagnostics。  
`build(require_clean=True)` rejects generated source with parser diagnostics; the default mode returns the document with those diagnostics attached.

layout IR 决定新生成文本的换行和缩进。已有源码的 `render()` 直接还原语法树保存的内容。  
The layout IR controls wrapping and indentation for generated text. `render()` reproduces the source stored by an existing syntax tree.

## 语义接口 / Semantic Integration

需要名称解析、类型信息或重载结果时，可以在 syntax tree 之上接编译器或项目自己的 semantic provider。  
Name resolution, type information, and overload results can be supplied by a compiler or project-specific semantic provider layered above the syntax tree.

## 编辑与快照契约 / Edit and Snapshot Contract

低层 `SyntaxTree` 编辑只接受当前语言的 `SyntaxElement` 或带语言归属的 `SyntaxFragment`。同语言 fragment 可以来自其他快照；跨语言 fragment 会被拒绝，裸 `GreenElement` 不属于公共编辑接口。  
Low-level `SyntaxTree` edits accept `SyntaxElement` or language-tagged `SyntaxFragment` values for the same language. Same-language fragments may come from another snapshot; cross-language fragments are rejected, and bare `GreenElement` values are not part of the public edit API.

低层编辑后 `diagnostics` 为 `None`，`diagnostic_state` 为 `unknown`。`CppDocument`/`CMakeDocument` 高层编辑会重新解析，因此返回文档的 diagnostics 再次可信。  
After a low-level edit, `diagnostics` is `None` and `diagnostic_state` is `unknown`. High-level `CppDocument` and `CMakeDocument` edits reparse the result, restoring authoritative diagnostics.

red view 绑定创建它的 immutable snapshot。编辑不会修改旧 view；旧 view 仍可读取，但不能作为新 snapshot 的 target。  
A red view belongs to the immutable snapshot that created it. Edits do not mutate old views; they remain readable but cannot be used as targets in a newer snapshot.

`CppParser` 和 `CMakeParser` 只保存不可变 schema；每次 `parse()` 使用局部解析状态，因此同一 parser 实例可并发复用。  
`CppParser` and `CMakeParser` keep only immutable schema state; each `parse()` call uses local parsing state, so one parser instance may be shared across concurrent parse calls.

C++ typed views 返回 syntax fields 推导出的源码级文本。类型绑定、重载结果等语义信息由上层 semantic provider 提供。  
C++ typed views expose source-level text derived from syntax fields. Type binding, overload results, and other semantic information belong to a higher-level semantic provider.
