"""验证 C++ 保护区域的归属、配对和字节边界行为。
Test C++ protected-region ownership, pairing, and byte-boundary behavior.
"""

from __future__ import annotations

import pytest

from xr_syntax.core import SourceSpan
from xr_syntax.cpp import CppDocument, CppRegion


def _source(newline: str = "\n") -> str:
    """生成一个带命名 User Code 区域的测试源码。
    Build test source containing one named User Code region.
    """
    return newline.join(
        (
            "void f() {",
            "  /* User Code Begin body */",
            "  keep_me();",
            "  /* User Code End body */",
            "}",
            "",
        )
    )


def test_region_from_another_document_is_rejected() -> None:
    """region 只能用于产生它的文档快照。
    A region can only be edited through the document snapshot that produced it.
    """
    first = CppDocument.parse(_source())
    second = CppDocument.parse(_source())
    region = first.user_regions()[0]

    with pytest.raises(ValueError, match="different immutable syntax snapshot"):
        second.replace_region_body(region, "\n  generated();\n  ")


def test_region_becomes_stale_after_document_edit() -> None:
    """文档编辑后的新快照拒绝旧 snapshot 的 region。
    A new document snapshot rejects a region retained from the old snapshot.
    """
    document = CppDocument.parse(_source())
    region = document.user_regions()[0]
    changed = document.replace_region_body(region, "\n  first();\n  ")

    with pytest.raises(ValueError, match="different immutable syntax snapshot"):
        changed.replace_region_body(region, "\n  second();\n  ")


def test_region_body_span_must_match_markers() -> None:
    """即使 marker 属于当前 tree，伪造的 body span 也会被拒绝。
    Reject a forged body span even when both markers belong to the current tree.
    """
    document = CppDocument.parse(_source())
    region = document.user_regions()[0]
    forged = CppRegion(
        region.kind,
        region.name,
        region.begin,
        region.end,
        SourceSpan(region.body_span.start, region.body_span.start),
        "",
    )

    with pytest.raises(ValueError, match="body span"):
        document.replace_region_body(forged, "replacement")


def test_mismatched_end_does_not_discard_open_region() -> None:
    """名字不匹配的 End 不会把栈顶 Begin 弹掉。
    A mismatched End marker does not discard the open Begin marker.
    """
    source = (
        "/* User Code Begin A */\n"
        "first();\n"
        "/* User Code End B */\n"
        "second();\n"
        "/* User Code End A */\n"
    )
    document = CppDocument.parse(source)
    regions = document.user_regions()

    assert len(regions) == 1
    assert regions[0].name == "A"
    assert "User Code End B" in regions[0].body_text
    assert "second();" in regions[0].body_text


def test_nested_regions_pair_in_source_order() -> None:
    """嵌套区域按栈规则配对，并按 Begin 的源码顺序返回。
    Nested regions pair by stack discipline and are returned in Begin-source order.
    """
    source = (
        "/* User Code Begin A */\n"
        "/* User Code Begin B */\n"
        "inner();\n"
        "/* User Code End B */\n"
        "outer();\n"
        "/* User Code End A */\n"
    )
    regions = CppDocument.parse(source).user_regions()

    assert [region.name for region in regions] == ["A", "B"]
    assert "inner();" in regions[1].body_text
    assert "outer();" in regions[0].body_text


def test_duplicate_nested_names_pair_without_ambiguity() -> None:
    """重复名称的嵌套区域按 LIFO 规则正确配对。
    Nested regions with duplicate names pair correctly using LIFO order.
    """
    source = (
        "/* User Code Begin A */\n"
        "/* User Code Begin A */\n"
        "inner();\n"
        "/* User Code End A */\n"
        "outer();\n"
        "/* User Code End A */\n"
    )
    regions = CppDocument.parse(source).user_regions()

    assert len(regions) == 2
    assert [region.name for region in regions] == ["A", "A"]
    assert "outer();" in regions[0].body_text
    assert "inner();" in regions[1].body_text


def test_unmatched_markers_do_not_create_regions() -> None:
    """单独 Begin 或 End 不产生伪 region。
    Unmatched Begin or End markers do not produce synthetic regions.
    """
    source = "/* User Code End orphan */\n/* User Code Begin open */\nwork();\n"
    assert CppDocument.parse(source).user_regions() == ()


def test_region_replacement_preserves_crlf() -> None:
    """替换 CRLF 文件中的 region 时保留 marker 外的换行字节。
    Region replacement preserves CRLF bytes outside the edited body.
    """
    source = _source("\r\n").encode()
    document = CppDocument.parse(source)
    region = document.user_regions()[0]
    changed = document.replace_region_body(region, "\r\n  generated();\r\n  ")

    rendered = changed.render_bytes()
    assert b"\r\n" in rendered
    assert rendered.startswith(b"void f() {\r\n")
    assert b"generated();" in rendered


def test_region_roundtrip_preserves_non_utf8_body_bytes() -> None:
    """surrogateescape body_text 可原样写回非 UTF-8 字节。
    A surrogate-escaped body can be written back without changing non-UTF-8 bytes.
    """
    source = b"/* User Code Begin raw */\n\xff\xfe\n/* User Code End raw */\n"
    document = CppDocument.parse(source)
    region = document.user_regions()[0]
    changed = document.replace_region_body(region, region.body_text)

    assert changed.render_bytes() == source
