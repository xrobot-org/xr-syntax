"""提供 C++ 文件、函数和代码块的批量源码构建器。
Batch C++ file, function, and block builders that parse once at the document boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from xr_syntax.core import SourceDraft, SyntaxFragment
from xr_syntax.format import Group, Indent, concat, hardline, join, render, softline, verbatim

from .document import CppDocument
from .factory import CppFactory

# ---------------------------------------------------------------------------
# 模块实现：提供 C++ 文件、函数和代码块的批量源码构建器。
# ---------------------------------------------------------------------------


# BlockBuilder 只累积 draft/fragment，不为每一条语句单独 parse；完整函数或文件
# 在 build() 边界统一解析一次，避免生成大量小 parser 调用。
@dataclass
class CppBlockBuilder:
    """按顺序累积尚未解析的函数体源码。
    Accumulate function-body source without parsing each statement separately.
    """

    factory: CppFactory
    items: list[SourceDraft | SyntaxFragment] = field(default_factory=list)

    def add(self, item: SourceDraft | SyntaxFragment) -> SourceDraft | SyntaxFragment:
        """追加同语言 draft 或已验证 fragment。
        Append a same-language draft or validated fragment.
        """
        self.factory._source_of(item)
        self.items.append(item)
        return item

    def statement(self, source: str) -> SourceDraft:
        """追加一条尚未解析的 C++ 语句。
        Append one unparsed C++ statement draft.
        """
        draft = self.factory._statement_draft(source)
        self.add(draft)
        return draft

    def call(self, callee: str, arguments: Iterable[str] = ()) -> SourceDraft:
        """追加一条尚未解析的函数调用语句。
        Append one unparsed function-call draft.
        """
        draft = self.factory._call_statement_draft(callee, arguments)
        self.add(draft)
        return draft

    def variable(
        self,
        cpp_type: str,
        name: str,
        *,
        initializer: str | None = None,
        storage: Iterable[str] = (),
    ) -> SourceDraft:
        """追加一条尚未解析的变量声明。
        Append one unparsed variable-declaration draft.
        """
        draft = self.factory._variable_draft(
            cpp_type,
            name,
            initializer=initializer,
            storage=storage,
        )
        self.add(draft)
        return draft

    def user_region(
        self,
        name: str,
        body: Iterable[SourceDraft | SyntaxFragment] = (),
    ) -> SourceDraft:
        """追加 User Code Begin/End 区域。
        Append one unparsed User Code region.
        """
        draft = self.factory._region_draft(
            f"/* User Code Begin {name} */",
            f"/* User Code End {name} */",
            body,
        )
        self.add(draft)
        return draft

    def format_disabled(
        self,
        body: Iterable[SourceDraft | SyntaxFragment],
    ) -> SourceDraft:
        """追加 clang-format off/on 区域。
        Append one unparsed clang-format disabled region.
        """
        draft = self.factory._region_draft(
            "// clang-format off",
            "// clang-format on",
            body,
        )
        self.add(draft)
        return draft

    def lint_disabled(
        self,
        body: Iterable[SourceDraft | SyntaxFragment],
    ) -> SourceDraft:
        """追加 NOLINTBEGIN/NOLINTEND 区域。
        Append one unparsed NOLINT disabled region.
        """
        draft = self.factory._region_draft(
            "// NOLINTBEGIN",
            "// NOLINTEND",
            body,
        )
        self.add(draft)
        return draft

    def raw(self, source: str) -> SourceDraft:
        """追加一段尚未解析的原始 C++ 源码。
        Append unparsed raw C++ source for final document validation.
        """
        draft = SourceDraft(self.factory.language, source)
        self.add(draft)
        return draft


@dataclass
class CppFunctionBuilder:
    """收集函数签名和 body，在需要时生成 draft 或独立 fragment。
    Collect a function signature and body before producing a draft or standalone fragment.
    """

    factory: CppFactory
    return_type: str
    name: str
    parameters: list[tuple[str, str]] = field(default_factory=list)
    prefix: list[str] = field(default_factory=list)
    body: CppBlockBuilder = field(init=False)

    def __post_init__(self) -> None:
        """创建函数体累积器。
        Create the function-body accumulator.
        """
        self.body = CppBlockBuilder(self.factory)

    def parameter(self, cpp_type: str, name: str) -> CppFunctionBuilder:
        """按源码顺序追加一个函数参数。
        Append one function parameter in source order.
        """
        self.parameters.append((cpp_type, name))
        return self

    # 函数签名先通过 layout IR 决定折行，body 中已有 fragment 则直接复用源码；
    # 这里只生成 SourceDraft，是否单独 parse 由调用者决定。
    def draft(self) -> SourceDraft:
        """渲染函数源码但不单独解析。
        Render the function source without parsing it separately.
        """
        params = [concat(cpp_type, " ", name) for cpp_type, name in self.parameters]
        signature = concat(
            " ".join((*self.prefix, self.return_type)).strip(),
            " ",
            self.name,
            Group(
                concat(
                    "(",
                    Indent(concat(softline, join(concat(",", hardline), params))),
                    softline,
                    ")",
                )
            ),
        )
        body = join(
            hardline,
            (verbatim(self.factory._source_of(item).rstrip("\r\n")) for item in self.body.items),
        )
        if self.body.items:
            document = concat(
                signature,
                " {",
                Indent(concat(hardline, body)),
                hardline,
                "}",
            )
        else:
            document = concat(signature, " {}")
        return SourceDraft(
            self.factory.language,
            render(document, width=self.factory.width),
        )

    def build(self) -> SyntaxFragment:
        """把当前函数单独解析为可插入 fragment。
        Parse this function as a standalone insertable fragment.
        """
        return self.factory.declaration(self.draft().source)


# FileBuilder 维护顶层源码顺序；函数 builder 在最终 build() 时才渲染，
# 从而让 include/raw/function/region 统一经过一次完整文档验证。
@dataclass
class CppFileBuilder:
    """累积 C++ source draft，并在 build() 时只解析完整文件一次。
    Accumulate C++ source drafts and parse the complete file once in build().
    """

    factory: CppFactory = field(default_factory=CppFactory)
    header: bool = False
    items: list[SourceDraft | SyntaxFragment | CppFunctionBuilder] = field(default_factory=list)

    def __post_init__(self) -> None:
        """在头文件模式下加入 pragma once draft。
        Add a pragma-once draft when building a header.
        """
        if self.header:
            self.items.append(self.factory._directive_draft("#pragma once"))

    def add(self, item: SourceDraft | SyntaxFragment) -> SourceDraft | SyntaxFragment:
        """追加同语言 draft 或已验证 fragment。
        Append a same-language draft or validated fragment.
        """
        self.factory._source_of(item)
        self.items.append(item)
        return item

    def include(self, header: str, *, system: bool = False) -> SourceDraft:
        """追加 include draft。
        Append one include draft.
        """
        draft = self.factory._include_draft(header, system=system)
        self.add(draft)
        return draft

    def comment(self, text: str, *, block: bool = False) -> SourceDraft:
        """追加注释 draft。
        Append one comment draft.
        """
        draft = self.factory._comment_draft(text, block=block)
        self.add(draft)
        return draft

    def raw(self, source: str) -> SourceDraft:
        """追加原始 source draft，并留到最终 parse 统一验证。
        Append raw source for validation by the final document parse.
        """
        draft = SourceDraft(self.factory.language, source)
        self.add(draft)
        return draft

    def format_disabled(
        self,
        body: Iterable[SourceDraft | SyntaxFragment],
    ) -> SourceDraft:
        """追加 clang-format 禁用区域 draft。
        Append one clang-format disabled region draft.
        """
        draft = self.factory._region_draft(
            "// clang-format off",
            "// clang-format on",
            body,
        )
        self.add(draft)
        return draft

    def lint_disabled(
        self,
        body: Iterable[SourceDraft | SyntaxFragment],
    ) -> SourceDraft:
        """追加 NOLINT 禁用区域 draft。
        Append one NOLINT disabled region draft.
        """
        draft = self.factory._region_draft(
            "// NOLINTBEGIN",
            "// NOLINTEND",
            body,
        )
        self.add(draft)
        return draft

    def declaration(self, source: str) -> SourceDraft:
        """追加顶层声明 draft。
        Append one top-level declaration draft.
        """
        draft = self.factory._declaration_draft(source)
        self.add(draft)
        return draft

    def variable(
        self,
        cpp_type: str,
        name: str,
        *,
        initializer: str | None = None,
        storage: Iterable[str] = (),
    ) -> SourceDraft:
        """追加顶层变量声明 draft。
        Append one top-level variable-declaration draft.
        """
        draft = self.factory._variable_draft(
            cpp_type,
            name,
            initializer=initializer,
            storage=storage,
        )
        self.add(draft)
        return draft

    def function(
        self,
        return_type: str,
        name: str,
        *,
        parameters: Iterable[tuple[str, str]] = (),
        prefix: Iterable[str] = (),
    ) -> CppFunctionBuilder:
        """创建函数 builder，并挂到当前文件的源码顺序中。
        Create a function builder in this file's source order.
        """
        function = CppFunctionBuilder(
            self.factory,
            return_type,
            name,
            list(parameters),
            list(prefix),
        )
        self.items.append(function)
        return function

    def user_region(
        self,
        name: str,
        body: Iterable[SourceDraft | SyntaxFragment] = (),
    ) -> SourceDraft:
        """追加 User Code 区域 draft。
        Append one User Code region draft.
        """
        draft = self.factory._region_draft(
            f"/* User Code Begin {name} */",
            f"/* User Code End {name} */",
            body,
        )
        self.add(draft)
        return draft

    def build(self, *, require_clean: bool = False) -> CppDocument:
        """渲染全部源码并只 parse 一次；可要求生成结果没有 diagnostics。
        Parse the complete generated file once and optionally require a clean result.
        """
        rendered: list[str] = []
        for item in self.items:
            if isinstance(item, CppFunctionBuilder):
                source = item.draft().source
            else:
                source = self.factory._source_of(item)
            rendered.append(source.rstrip("\r\n"))
        source = "\n".join(rendered)
        if source and not source.endswith("\n"):
            source += "\n"
        # 生成结束后只在这里做一次完整 parse，确保 builder 输出和读取已有源码
        # 使用完全相同的 CppDocument/SyntaxTree 模型。
        document = CppDocument.parse(source, parser=self.factory.parser)
        if require_clean and document.diagnostics:
            messages = "; ".join(item.message for item in document.diagnostics)
            raise ValueError(f"generated C++ source has parser diagnostics: {messages}")
        return document
