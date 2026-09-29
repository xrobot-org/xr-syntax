"""C++ 词法查询共享的内部辅助函数。
Internal helpers shared by C++ lexical-query modules.
"""

from __future__ import annotations

from .lexer import _Lexeme

# ---------------------------------------------------------------------------
# 模块实现：C++ 词法查询共享的内部辅助函数。
# ---------------------------------------------------------------------------


def _inside_preprocessor(lexemes: list[_Lexeme], index: int) -> bool:
    """判断 lexeme 是否位于预处理逻辑行，包括反斜杠续行。
    Return whether a lexeme belongs to a preprocessor logical line, including continuations.
    """
    cursor = index
    while cursor >= 0:
        item = lexemes[cursor]
        if item.trivia and ("\n" in item.text or "\r" in item.text):
            previous = cursor - 1
            while previous >= 0 and lexemes[previous].trivia:
                previous -= 1
            if previous >= 0 and lexemes[previous].text == "\\":
                cursor = previous - 1
                continue
            break
        if not item.trivia and item.kind != "comment" and item.text == "#":
            return True
        cursor -= 1
    return False
