"""提供常见 C++ 源码片段的 parser-backed 工厂。
Factories for parser-backed C++ source fragments.
"""

from __future__ import annotations

from collections.abc import Iterable

from xr_syntax.core import (
    GreenChild,
    GreenNode,
    GreenToken,
    GreenTrivia,
    SourceDraft,
    SyntaxElement,
    SyntaxFragment,
    SyntaxNode,
)
from xr_syntax.format import Group, Indent, concat, join, line, render, softline

from .document import CppDocument
from .parser import CppParser

# ---------------------------------------------------------------------------
# 模块实现：提供常见 C++ 源码片段的 parser-backed 工厂。
# ---------------------------------------------------------------------------


# Factory 同时提供两类能力：公开方法返回已解析、可安全插入的 SyntaxFragment；
# 私有 *_draft 方法只负责低成本地产生源码文本，供 Builder 批量拼装后统一 parse。
class CppFactory:
    """创建带 C++ 语言归属的 parser-backed 片段。
    Create parser-backed fragments carrying explicit C++ language provenance.
    """

    language = "cpp"

    def __init__(self, parser: CppParser | None = None, *, width: int = 100) -> None:
        """初始化片段工厂并保存布局宽度。
        Initialize the fragment factory and store its layout width.
        """
        self.parser = parser or CppParser()
        self.width = width

    # -----------------------------------------------------------------------
    # 对外 fragment API：这些方法返回带 C++ 语言归属的 parser-backed 片段。
    # -----------------------------------------------------------------------
    def include(self, header: str, *, system: bool = False) -> SyntaxFragment:
        """创建 include 指令片段。
        Create one include-directive fragment.
        """
        draft = self._include_draft(header, system=system)
        return self._fragment(self._first_node(draft.source, "preproc_include"))

    def comment(self, text: str, *, block: bool = False) -> SyntaxFragment:
        """创建行注释或块注释片段。
        Create one line-comment or block-comment fragment.
        """
        draft = self._comment_draft(text, block=block)
        return self._fragment(self._first_element(draft.source, "comment"))

    def directive(self, source: str) -> SyntaxFragment:
        """创建预处理指令片段。
        Create and validate one preprocessor-directive fragment.
        """
        draft = self._directive_draft(source)
        document = CppDocument.parse(draft.source, parser=self.parser)
        for child in document.root.syntax_children:
            return self._fragment(child)
        raise ValueError("directive did not produce syntax")

    def raw(self, source: str) -> SyntaxFragment:
        """创建显式 opaque 的原始 C++ 片段。
        Create an explicit opaque C++ source fragment.
        """
        return SyntaxFragment(
            self.language,
            GreenToken("raw", source, named=True),
            opaque=True,
        )

    def user_region(
        self,
        name: str,
        body: Iterable[SyntaxFragment] = (),
    ) -> SyntaxFragment:
        """创建 User Code Begin/End 区域。
        Create a paired User Code region.
        """
        return self._region(
            "xr_user_region",
            f"/* User Code Begin {name} */",
            f"/* User Code End {name} */",
            body,
        )

    def format_region(self, body: Iterable[SyntaxFragment]) -> SyntaxFragment:
        """创建 clang-format off/on 区域。
        Create a paired clang-format off/on region.
        """
        return self._region(
            "xr_format_region",
            "// clang-format off",
            "// clang-format on",
            body,
        )

    def lint_region(self, body: Iterable[SyntaxFragment]) -> SyntaxFragment:
        """创建 NOLINTBEGIN/NOLINTEND 区域。
        Create a paired NOLINTBEGIN/NOLINTEND region.
        """
        return self._region(
            "xr_lint_region",
            "// NOLINTBEGIN",
            "// NOLINTEND",
            body,
        )

    def expression(self, text: str) -> SyntaxFragment:
        """解析一个表达式片段。
        Parse one expression fragment in a temporary function context.
        """
        document = CppDocument.parse(
            f"auto __xr_expr() -> decltype(auto) {{ return {text}; }}",
            parser=self.parser,
        )
        statement = document.nodes("return_statement")[0]
        for child in statement.named_children:
            return self._fragment(child)
        raise ValueError("expression did not produce syntax")

    def statement(self, text: str) -> SyntaxFragment:
        """解析一个语句片段。
        Parse one statement fragment in a temporary function body.
        """
        draft = self._statement_draft(text)
        document = CppDocument.parse(
            f"void __xr_stmt() {{ {draft.source} }}",
            parser=self.parser,
        )
        body = document.nodes("compound_statement")[0]
        for child in body.named_children:
            return self._fragment(child)
        raise ValueError("statement did not produce syntax")

    def declaration(self, text: str) -> SyntaxFragment:
        """解析一个顶层声明片段。
        Parse one top-level declaration fragment.
        """
        draft = self._declaration_draft(text)
        document = CppDocument.parse(draft.source, parser=self.parser)
        for child in document.root.named_children:
            return self._fragment(child)
        raise ValueError("declaration did not produce syntax")

    def call_statement(
        self,
        callee: str,
        arguments: Iterable[str],
    ) -> SyntaxFragment:
        """通过布局 IR 创建函数调用语句。
        Build a function-call statement through the shared layout IR.
        """
        return self.statement(self._call_statement_draft(callee, arguments).source)

    def variable(
        self,
        cpp_type: str,
        name: str,
        *,
        initializer: str | None = None,
        storage: Iterable[str] = (),
    ) -> SyntaxFragment:
        """由常用字段创建变量声明片段。
        Build a variable-declaration fragment from common structured fields.
        """
        return self.declaration(
            self._variable_draft(
                cpp_type,
                name,
                initializer=initializer,
                storage=storage,
            ).source
        )

    def function(
        self,
        return_type: str,
        name: str,
        *,
        parameters: Iterable[tuple[str, str]] = (),
        body: Iterable[str] = (),
        prefix: Iterable[str] = (),
    ) -> SyntaxFragment:
        """由签名和 body 创建函数定义片段。
        Build a function-definition fragment from a signature and body statements.
        """
        draft = self._function_draft(
            return_type,
            name,
            parameters=parameters,
            body=body,
            prefix=prefix,
        )
        return self._fragment(self._first_node(draft.source, "function_definition"))

    # -----------------------------------------------------------------------
    # Builder 内部 draft API：只生成源码，不在每个小片段上重复启动 parser。
    # -----------------------------------------------------------------------
    def _include_draft(self, header: str, *, system: bool = False) -> SourceDraft:
        """生成尚未解析的 include 源码。
        Build unparsed source for one include directive.
        """
        delimiters = ("<", ">") if system else ('"', '"')
        return SourceDraft(
            self.language,
            f"#include {delimiters[0]}{header}{delimiters[1]}\n",
        )

    def _comment_draft(self, text: str, *, block: bool = False) -> SourceDraft:
        """生成尚未解析的注释源码。
        Build unparsed source for one comment.
        """
        source = f"/* {text} */" if block else f"// {text}"
        return SourceDraft(self.language, source)

    def _directive_draft(self, source: str) -> SourceDraft:
        """生成规范化为单行的预处理指令源码。
        Build source for one preprocessor directive.
        """
        return SourceDraft(self.language, source.rstrip() + "\n")

    def _statement_draft(self, text: str) -> SourceDraft:
        """生成尚未解析的语句源码。
        Build unparsed source for one statement.
        """
        source = text if text.rstrip().endswith((";", "}")) else text + ";"
        return SourceDraft(self.language, source)

    def _declaration_draft(self, text: str) -> SourceDraft:
        """生成尚未解析的声明源码。
        Build unparsed source for one top-level declaration.
        """
        source = text if text.rstrip().endswith((";", "}")) else text + ";"
        return SourceDraft(self.language, source)

    def _call_statement_draft(
        self,
        callee: str,
        arguments: Iterable[str],
    ) -> SourceDraft:
        """通过布局 IR 生成尚未解析的调用语句源码。
        Render an unparsed call statement through the layout IR.
        """
        document = Group(
            concat(
                callee,
                "(",
                Indent(
                    concat(
                        softline,
                        join(concat(",", line), tuple(arguments)),
                    )
                ),
                softline,
                ");",
            )
        )
        return SourceDraft(self.language, render(document, width=self.width))

    def _variable_draft(
        self,
        cpp_type: str,
        name: str,
        *,
        initializer: str | None = None,
        storage: Iterable[str] = (),
    ) -> SourceDraft:
        """生成尚未解析的变量声明源码。
        Build unparsed source for one variable declaration.
        """
        prefix = " ".join((*storage, cpp_type, name))
        if initializer is not None:
            prefix += f" = {initializer}"
        return self._declaration_draft(prefix)

    def _function_draft(
        self,
        return_type: str,
        name: str,
        *,
        parameters: Iterable[tuple[str, str]] = (),
        body: Iterable[str] = (),
        prefix: Iterable[str] = (),
    ) -> SourceDraft:
        """生成尚未解析的完整函数定义源码。
        Build unparsed source for one complete function definition.
        """
        params = ", ".join(f"{typ} {param}" for typ, param in parameters)
        lines = list(body)
        start = " ".join((*prefix, return_type, f"{name}({params})")).strip()
        if lines:
            body_text = "\n".join("  " + statement for statement in lines)
            source = f"{start} {{\n{body_text}\n}}"
        else:
            source = f"{start} {{}}"
        return SourceDraft(self.language, source)

    def _region_draft(
        self,
        begin: str,
        end: str,
        body: Iterable[SourceDraft | SyntaxFragment],
    ) -> SourceDraft:
        """生成尚未解析的保护区域源码。
        Build unparsed source for a protected region.
        """
        rendered = [begin]
        rendered.extend(self._source_of(item).rstrip("\r\n") for item in body)
        rendered.append(end)
        return SourceDraft(self.language, "\n".join(rendered))

    def _region(
        self,
        kind: str,
        begin: str,
        end: str,
        body: Iterable[SyntaxFragment],
    ) -> SyntaxFragment:
        """按 begin/end 标记构造可插入保护区域。
        Construct an insertable protected region from begin/end markers and body fragments.
        """
        # Region 标记本身是普通 comment token；区域语义由显式 xr_*_region
        # 节点提供，避免修改底层 C++ grammar。
        children: list[GreenChild] = [
            GreenChild(GreenToken("comment", begin, named=True)),
            GreenChild(GreenTrivia("newline", "\n")),
        ]
        for fragment in body:
            children.append(GreenChild(fragment.green_for(self.language)))
            children.append(GreenChild(GreenTrivia("newline", "\n")))
        children.append(GreenChild(GreenToken("comment", end, named=True)))
        return SyntaxFragment(
            self.language,
            GreenNode(kind, tuple(children), named=True),
        )

    def _source_of(self, item: SourceDraft | SyntaxFragment) -> str:
        """返回同语言 draft/fragment 的源码文本。
        Return source text from a same-language draft or syntax fragment.
        """
        if isinstance(item, SourceDraft):
            return item.source_for(self.language)
        item.green_for(self.language)
        return item.render()

    def _fragment(self, element: SyntaxElement) -> SyntaxFragment:
        """把解析得到的元素包装成 C++ fragment。
        Wrap one parsed syntax element as a C++ fragment.
        """
        return SyntaxFragment(self.language, element.green)

    def _first_element(self, source: str, kind: str) -> SyntaxElement:
        """返回临时解析结果中指定 kind 的第一个元素。
        Return the first parsed syntax element of the requested kind.
        """
        document = CppDocument.parse(source, parser=self.parser)
        elements = document.elements(kind)
        if not elements:
            raise ValueError(f"generated fragment did not contain {kind}")
        return elements[0]

    def _first_node(self, source: str, kind: str) -> SyntaxNode:
        """返回临时解析结果中指定 kind 的第一个节点。
        Return the first parsed node of the requested kind.
        """
        document = CppDocument.parse(source, parser=self.parser)
        nodes = document.nodes(kind)
        if not nodes:
            raise ValueError(f"generated fragment did not contain {kind}")
        return nodes[0]
