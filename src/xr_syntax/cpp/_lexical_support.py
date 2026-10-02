"""C++ 词法查询共享的内部辅助函数。
Internal helpers shared by C++ lexical-query modules.
"""

from __future__ import annotations

from xr_syntax.cpp.lexer import Lexed


def preprocessor_mask(lexed: Lexed) -> list[bool]:
    """每个 lexeme 是否位于预处理逻辑行（从 # 开始，含反斜杠续行）。
    Whether each lexeme belongs to a preprocessor logical line (from a # on, continuation
    lines included).

    一遍前向扫描：换行前最后一个非空白 lexeme 是反斜杠时，逻辑行延续到下一行。
    One forward pass: when the last non-whitespace lexeme before a line ending is a
    backslash, the logical line continues on the next line.
    """
    texts = lexed.texts
    if "#" not in texts:
        return [False] * len(texts)
    mask = []
    directive = False
    last_text = None
    for text, info in zip(texts, lexed.infos, strict=True):
        if info[2]:
            if directive and last_text != "\\" and ("\n" in text or "\r" in text):
                directive = False
            mask.append(directive)
            continue
        if text == "#" and info[0] != "comment":
            directive = True
        mask.append(directive)
        last_text = text
    return mask
