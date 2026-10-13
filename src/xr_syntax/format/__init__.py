"""按 LibXR 的 clang-format 风格排版生成的 C++。
Layout of generated C++ in the clang-format style of LibXR.
"""

from xr_syntax.format.layout import (
    COLUMN_LIMIT,
    INDENT,
    Braces,
    layout_call,
    layout_declaration,
    layout_macro,
    layout_statement,
    layout_value,
    sort_includes,
    wrap_comment,
)

__all__ = [
    "COLUMN_LIMIT",
    "INDENT",
    "Braces",
    "layout_call",
    "layout_declaration",
    "layout_macro",
    "layout_statement",
    "layout_value",
    "sort_includes",
    "wrap_comment",
]
