"""提供源码 bytes 与 Python str 的无损转换，并用 surrogateescape 保留非 UTF-8 字节。
Lossless conversion between source bytes and Python text using surrogate escapes.
"""

from __future__ import annotations


def decode_source(data: bytes) -> str:
    """使用 surrogateescape 解码源码字节，使不可解码字节仍可无损还原。
    Decode source bytes with surrogateescape so undecodable bytes can round-trip unchanged.
    """
    return data.decode("utf-8", errors="surrogateescape")


def encode_source(text: str) -> bytes:
    """使用 surrogateescape 编码源码文本，与 decode_source 互为逆操作。
    Encode source text with surrogateescape, reversing decode_source for preserved bytes.
    """
    return text.encode("utf-8", errors="surrogateescape")
