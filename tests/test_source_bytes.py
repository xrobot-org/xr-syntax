"""验证包含非 UTF-8 字节的源码仍能无损解析和还原。
Test lossless parsing and rendering of source containing non-UTF-8 bytes.
"""

from xr_syntax.cpp import CppDocument


def test_non_utf8_bytes_still_roundtrip_losslessly() -> None:
    """验证包含非 UTF-8 字节的源码仍可通过 surrogateescape 无损 round-trip。
    Verify that source containing non-UTF-8 bytes remains lossless through surrogateescape.
    """
    source = b"int value; // byte: \xff\n"
    document = CppDocument.parse(source)
    assert document.render_bytes() == source


def test_surrogateescaped_text_input_roundtrips_losslessly() -> None:
    """验证 surrogateescape 解码后的 str 也能无损重新编码。
    Verify that surrogateescaped str input is re-encoded losslessly.
    """
    source = b"int value; // byte: \xff\n"
    text = source.decode("utf-8", errors="surrogateescape")
    document = CppDocument.parse(text)
    assert document.render_bytes() == source
