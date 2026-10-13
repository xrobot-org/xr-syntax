"""CMake 前端：解析器、文档、命令视图、User Code 区域和文件构建器。
CMake frontend: the parser, documents, command views, User Code regions and the file builder.

它与 C++ 前端共享同一套不可变语法树、结构化编辑、成对注释区域和布局基础设施。
It shares one immutable syntax model, structural editing, paired comment regions and layout
infrastructure with the C++ frontend.
"""

from xr_syntax.cmake.builder import CMakeFileBuilder
from xr_syntax.cmake.document import CMakeDocument, CMakeStatementView
from xr_syntax.cmake.parser import CMakeParser
from xr_syntax.cmake.view import CMakeArgumentView, CMakeCommandView

__all__ = [
    "CMakeArgumentView",
    "CMakeCommandView",
    "CMakeDocument",
    "CMakeFileBuilder",
    "CMakeParser",
    "CMakeStatementView",
]
