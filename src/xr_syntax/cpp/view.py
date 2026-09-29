"""提供 include、变量、参数、函数、调用和类等 C++ 结构的便捷只读视图。
Convenience views for common C++ source constructs without replacing the full syntax tree.
"""

from __future__ import annotations

from dataclasses import dataclass

from xr_syntax.core import SyntaxElement, SyntaxNode

from .syntax_utils import (
    declaration_name,
    declaration_type_text,
    declarator_name,
    field_text,
    find_function_declarator,
)

# ---------------------------------------------------------------------------
# 完整 C++ 语法树之上的类型化便捷视图
# Typed convenience views over the complete C++ syntax tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CppIncludeView:
    """提供 include 指令的路径、头文件名和 system/local 属性访问。
    Convenience view of one C++ preprocessor include directive.
    """

    node: SyntaxNode

    @property
    def path(self) -> str | None:
        """返回 include 指令 path field 对应的语法元素。
        Return the source spelling of the include path field.
        """
        value = self.node.child_by_field("path")
        return None if value is None else value.text

    @property
    def header(self) -> str | None:
        """返回去掉引号或尖括号后的头文件路径文本。
        Return the include header name without delimiters.
        """
        path = self.path
        if path is None:
            return None
        if len(path) >= 2 and (path[0], path[-1]) in {('"', '"'), ("<", ">")}:
            return path[1:-1]
        return path

    @property
    def system(self) -> bool:
        """判断该 include 是否使用 <...> system header 形式。
        Report whether this include uses angle-bracket system syntax.
        """
        path = self.path
        return bool(path and path.startswith("<") and path.endswith(">"))


@dataclass(frozen=True)
class CppVariableView:
    """提供变量声明的名称、基础类型、修饰符、初始化器和作用域信息。
    Source-structural view of one declarator inside a C++ declaration.
    """

    node: SyntaxNode
    declarator: SyntaxElement

    @property
    def name(self) -> str | None:
        """返回变量 declarator 的源码级名称。
        Return the source-level name when available.
        """
        return declarator_name(self.declarator)

    @property
    def base_type(self) -> str | None:
        """返回变量声明的基础类型源码文本。
        Return parser type-field text before declarator wrappers.
        """
        return field_text(self.node, "type")

    @property
    def storage(self) -> tuple[str, ...]:
        """返回 static、extern 等 storage class 修饰符。
        Return source storage-class specifiers.
        """
        return tuple(
            child.text.strip()
            for child in self.node.syntax_children
            if child.kind == "storage_class_specifier"
        )

    @property
    def qualifiers(self) -> tuple[str, ...]:
        """返回 const、volatile 等类型限定符。
        Return source type qualifiers.
        """
        return tuple(
            child.text.strip()
            for child in self.node.syntax_children
            if child.kind == "type_qualifier"
        )

    @property
    def initializer(self) -> str | None:
        """返回初始化器源码文本；没有初始化器时返回 None。
        Return initializer source text when present.
        """
        if not isinstance(self.declarator, SyntaxNode):
            return None
        value = self.declarator.child_by_field("value")
        return None if value is None else value.text.strip()

    @property
    def global_scope(self) -> bool:
        """判断该变量声明是否位于 translation unit 顶层。
        Report whether this declaration is outside every compound statement.
        """
        parent = self.node.parent
        while parent is not None:
            if parent.kind == "compound_statement":
                return False
            if parent.kind == "translation_unit":
                return True
            parent = parent.parent
        return False


@dataclass(frozen=True)
class CppParameterView:
    """提供函数参数的原文、名称、类型和默认值访问。
    Convenience view exposing a function parameter's source name/type/default text.
    """

    node: SyntaxNode

    @property
    def text(self) -> str:
        """返回该函数参数的完整源码文本。
        Return the complete source text of this function parameter.
        """
        return self.node.text

    @property
    def name(self) -> str | None:
        """返回函数参数名称；匿名参数返回 None。
        Return the source-level name when available.
        """
        return declaration_name(self.node)

    @property
    def type(self) -> str | None:
        """返回去除名称和默认值后的参数类型源码文本。
        Return reconstructed source-level type text.
        """
        return declaration_type_text(self.node)

    @property
    def default(self) -> str | None:
        """返回参数默认值源码文本；没有默认值时返回 None。
        Return default source text when present.
        """
        value = self.node.child_by_field("default_value")
        if value is None:
            value = self.node.child_by_field("value")
        return None if value is None else value.text.strip()


@dataclass(frozen=True)
class CppTemplateParameterView:
    """提供模板参数的原文、名称、类型和默认值访问。
    Convenience view exposing a template parameter's source components.
    """

    node: SyntaxNode

    @property
    def text(self) -> str:
        """返回该模板参数的完整源码文本。
        Return the complete source text of this template parameter.
        """
        return self.node.text

    @property
    def name(self) -> str | None:
        """返回模板参数名称；匿名参数返回 None。
        Return the source-level name when available.
        """
        return declaration_name(self.node)

    @property
    def type(self) -> str | None:
        """返回模板参数的类型/类别描述源码文本。
        Return reconstructed source-level type text.
        """
        return declaration_type_text(self.node)

    @property
    def default(self) -> str | None:
        """返回模板参数默认值源码文本；没有时返回 None。
        Return default source text when present.
        """
        value = self.node.child_by_field("default_value")
        if value is None:
            value = self.node.child_by_field("default_type")
        return None if value is None else value.text.strip()


@dataclass(frozen=True)
class CppFunctionView:
    """提供函数或方法的名称、declarator、参数、函数体和特殊成员状态。
    Source-structural function/method view with parameter and special-member helpers.
    """

    node: SyntaxNode
    access: str | None = None

    @property
    def name(self) -> str | None:
        """返回函数或方法的源码级名称。
        Return the source-level name when available.
        """
        return declaration_name(self.node)

    @property
    def declarator(self) -> SyntaxNode | None:
        """返回携带参数和限定符的 function_declarator 节点。
        Return the function declarator carrying parameters and qualifiers.
        """
        return find_function_declarator(self.node)

    @property
    def parameters(self) -> tuple[CppParameterView, ...]:
        """按声明顺序返回类型化参数视图。
        Return typed views of declared parameters.
        """
        declarator = self.declarator
        if declarator is None:
            return ()
        parameters = declarator.child_by_field("parameters")
        if not isinstance(parameters, SyntaxNode):
            return ()
        return tuple(
            CppParameterView(child)
            for child in parameters.named_children
            if child.kind in {"parameter_declaration", "optional_parameter_declaration"}
        )

    @property
    def body(self) -> SyntaxElement | None:
        """返回解析得到的函数体元素；只有声明时返回 None。
        Return the parsed body element when present.
        """
        return self.node.child_by_field("body")

    @property
    def deleted(self) -> bool:
        """判断特殊成员是否在语法上声明为 = delete。
        Report whether this member is syntactically declared '= delete'.
        """
        return self.node.first_descendant("delete_method_clause") is not None

    @property
    def defaulted(self) -> bool:
        """判断特殊成员是否在语法上声明为 = default。
        Report whether this member is syntactically declared '= default'.
        """
        return self.node.first_descendant("default_method_clause") is not None


@dataclass(frozen=True)
class CppCallView:
    """提供调用表达式的被调表达式文本和实参列表访问。
    Convenience view of a call expression and its argument syntax elements.
    """

    node: SyntaxNode

    @property
    def callee(self) -> str | None:
        """返回被调用表达式的精确源码文本。
        Return exact source text for the called expression.
        """
        return field_text(self.node, "function")

    @property
    def arguments(self) -> tuple[SyntaxElement, ...]:
        """按源码顺序返回调用实参语法元素。
        Return argument syntax elements in source order.
        """
        arguments = self.node.child_by_field("arguments")
        if not isinstance(arguments, SyntaxNode):
            return ()
        return arguments.named_syntax_children


# class/member 便捷视图只解释源码结构，不解析继承构造、重载可行性
# 或编译器类型转换。
# Class/member convenience helpers stop at source structure. They do not resolve
# inherited constructors, overload viability, or compiler type conversions.
@dataclass(frozen=True)
class CppClassView:
    """扫描 class/struct 成员并跟踪有效访问控制的便捷视图。
    Convenience class/struct view that tracks C++ access sections while scanning members.
    """

    node: SyntaxNode

    @property
    def name(self) -> str | None:
        """返回 class/struct 的源码级名称。
        Return the source-level name when available.
        """
        return field_text(self.node, "name")

    @property
    def default_access(self) -> str:
        """根据 class 或 struct 返回默认成员访问级别。
        Return the C++ default member access for class versus struct.
        """
        return "public" if self.node.kind == "struct_specifier" else "private"

    @property
    def body(self) -> SyntaxNode | None:
        """返回类定义的 field_declaration_list；只有前置声明时返回 None。
        Return the parsed body element when present.
        """
        body = self.node.child_by_field("body")
        return body if isinstance(body, SyntaxNode) else None

    def functions(self) -> tuple[CppFunctionView, ...]:
        """扫描成员函数并为每个函数附上当时有效的访问级别。
        Return syntactically declared member functions with effective access labels.
        """
        body = self.body
        if body is None:
            return ()
        access = self.default_access
        result: list[CppFunctionView] = []
        for child in body.named_children:
            if child.kind == "access_specifier":
                access = child.text.strip().rstrip(":")
                continue
            if find_function_declarator(child) is not None:
                result.append(CppFunctionView(child, access))
        return tuple(result)

    @property
    def template_parameters(self) -> tuple[CppTemplateParameterView, ...]:
        """当类直接位于 template 声明中时返回其模板参数。
        Return parameters when the class is directly wrapped by a template declaration.
        """
        parent = self.node.parent
        if parent is None or parent.kind != "template_declaration":
            return ()
        parameters = parent.child_by_field("parameters")
        if not isinstance(parameters, SyntaxNode):
            return ()
        return tuple(
            CppTemplateParameterView(child)
            for child in parameters.named_children
            if child.kind
            in {
                "type_parameter_declaration",
                "optional_type_parameter_declaration",
                "parameter_declaration",
                "optional_parameter_declaration",
                "variadic_parameter_declaration",
            }
        )

    def constructors(
        self,
        *,
        public_only: bool = False,
        callable_only: bool = False,
    ) -> tuple[CppFunctionView, ...]:
        """返回当前类的构造函数声明，并支持访问级别和可调用性过滤。
        Return constructor declarations for this class.
        """
        name = self.name
        result = tuple(function for function in self.functions() if function.name == name)
        if public_only:
            result = tuple(function for function in result if function.access == "public")
        if callable_only:
            result = tuple(function for function in result if not function.deleted)
        return result
