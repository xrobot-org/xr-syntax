"""加载并校验固定版本的 CMake grammar 元数据。
Load and validate pinned CMake grammar metadata.
"""

from __future__ import annotations

import hashlib
import json
import pkgutil
from typing import Any

from xr_syntax.core import LanguageGrammar

GRAMMAR_VERSION = "0.7.4"
GRAMMAR_REVISION = "ca627bb5828616b6246aafdc3c3222789e728e37"
NODE_TYPES_SHA256 = "e696c1156c9916d1d26f2e4643b6d32794dd079b0c8640aa1dabf2f33a3f5cdf"


def _load() -> LanguageGrammar:
    """读取、校验 CMake grammar 元数据并构造 LanguageGrammar。
    Load and validate CMake grammar metadata and build a LanguageGrammar.
    """
    payload = pkgutil.get_data(__package__, "node-types.json")
    if payload is None:
        raise RuntimeError("packaged CMake grammar schema is missing")

    # Windows checkout 可能使用 CRLF，校验前统一为 LF。
    # Windows checkouts may use CRLF, so normalize to LF before hashing.
    text = payload.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    normalized = text.encode("utf-8")
    digest = hashlib.sha256(normalized).hexdigest()
    if digest != NODE_TYPES_SHA256:
        raise RuntimeError(
            f"packaged CMake grammar schema checksum mismatch: {digest} != {NODE_TYPES_SHA256}"
        )

    decoded: Any = json.loads(text)
    if not isinstance(decoded, list) or not all(isinstance(item, dict) for item in decoded):
        raise RuntimeError("packaged CMake node-types schema has an invalid root")

    return LanguageGrammar.from_node_types(
        language="cmake",
        version=GRAMMAR_VERSION,
        source_revision=GRAMMAR_REVISION,
        source_sha256=NODE_TYPES_SHA256,
        data=decoded,
    )


CMAKE_GRAMMAR = _load()


__all__ = [
    "CMAKE_GRAMMAR",
    "GRAMMAR_REVISION",
    "GRAMMAR_VERSION",
    "NODE_TYPES_SHA256",
]
