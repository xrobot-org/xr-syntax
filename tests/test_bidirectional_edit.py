"""验证 C++ 结构化编辑会重新解析，同时保持未修改源码和保护区域不变。
Test that structured C++ edits reparse correctly while preserving unrelated source and protected regions.
"""

from xr_syntax.cpp import CppDocument, CppFactory

SOURCE = """#include "a.hpp"

void f() {
  foo(1);
  /* User Code Begin body */
  keep_me();
  /* User Code End body */
}
"""


def test_structured_edit_reparses_and_preserves_unrelated_source() -> None:
    """验证结构化编辑会重新解析文档，同时完整保留无关源码。
    Verify that structured edits reparse the document while preserving unrelated source exactly.
    """
    factory = CppFactory()
    document = CppDocument.parse(SOURCE)

    include = document.includes()[0]
    document = document.insert_after(include, factory.include("b.hpp"))

    call = document.calls("foo")[0]
    document = document.replace(call, factory.expression("bar(2)"))

    assert document.render().startswith('#include "a.hpp"\n#include "b.hpp"\n')
    assert "  bar(2);" in document.render()
    assert "keep_me();" in document.render()
    assert len(document.calls("foo")) == 0
    assert len(document.calls("bar")) == 1


def test_user_region_body_can_be_replaced_without_touching_markers() -> None:
    """验证替换 User Code body 时不会修改成对区域标记。
    Verify that replacing a User Code body does not modify its paired region markers.
    """
    document = CppDocument.parse(SOURCE)
    region = document.user_regions()[0]
    changed = document.replace_region_body(
        region,
        "\n  generated();\n  ",
    )

    assert "/* User Code Begin body */" in changed.render()
    assert "/* User Code End body */" in changed.render()
    assert "keep_me();" not in changed.render()
    assert "generated();" in changed.render()
    assert len(changed.user_regions()) == 1
    assert len(changed.calls("generated")) == 1
