"""C++ 词法查询共享的内部辅助函数。
Internal helpers shared by C++ lexical-query modules.
"""

from __future__ import annotations

from collections.abc import Sequence

from .lexer import _Lexeme

# ---------------------------------------------------------------------------
# 模块实现：C++ 词法查询共享的内部辅助函数。
# ---------------------------------------------------------------------------


def _preprocessor_mask(lexemes: Sequence[_Lexeme]) -> list[bool]:
    """每个 lexeme 是否位于预处理逻辑行（从 # 开始，含反斜杠续行）。
    Whether each lexeme belongs to a preprocessor logical line (from a # on, continuation
    lines included).

    一遍前向扫描：换行前最后一个非空白 lexeme 是反斜杠时，逻辑行延续到下一行。
    One forward pass: when the last non-whitespace lexeme before a line ending is a
    backslash, the logical line continues on the next line.
    """
    mask = []
    directive = False
    last_text = None
    for item in lexemes:
        if item.trivia:
            line_end = "\n" in item.text or "\r" in item.text
            if line_end and last_text != "\\":
                directive = False
            mask.append(directive)
            continue
        if item.kind != "comment" and item.text == "#":
            directive = True
        mask.append(directive)
        last_text = item.text
    return mask
