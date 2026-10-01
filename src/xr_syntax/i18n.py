"""输出语言：中文环境输出中文，其他环境输出英文。xrobot 和 libxr 两个命令行工具共用。
Output language: Chinese in a Chinese environment, English elsewhere. Shared by the xrobot
and libxr command-line tools.

语言依次由环境变量 XR_LANG、LANGUAGE、LC_ALL、LC_MESSAGES、LANG 决定，第一个非空的值以 zh 开头时
输出中文；都没有设置时，Windows 上看系统界面语言。
The language comes from the first non-empty of the environment variables XR_LANG, LANGUAGE,
LC_ALL, LC_MESSAGES and LANG: a value starting with zh selects Chinese. When none is set,
Windows uses the system display language.
"""

from __future__ import annotations

import argparse
import functools
import os
import sys
import unicodedata

_VARIABLES = ("XR_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


def chinese() -> bool:
    """当前是否输出中文。
    Whether output is in Chinese.
    """
    return _chinese(tuple(os.environ.get(name, "") for name in _VARIABLES))


@functools.lru_cache(maxsize=8)
def _chinese(values: tuple[str, ...]) -> bool:
    """按环境变量的值判断是否输出中文；结果按这些值缓存。
    Whether the environment values select Chinese; cached per set of values.
    """
    for value in values:
        if value.strip():
            return value.strip().lower().startswith("zh")
    if sys.platform == "win32":
        import ctypes

        try:
            # LANGID 的低 10 位是主语言，0x04 为中文。
            # The low 10 bits of a LANGID are the primary language; 0x04 is Chinese.
            language = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        except (AttributeError, OSError):
            return False
        return bool(language & 0x3FF == 0x04)
    return False


def tr(english: str, chinese_text: str) -> str:
    """按当前语言选择一条消息的英文或中文。
    Choose the English or the Chinese text of a message for the current language.
    """
    return chinese_text if chinese() else english


# argparse 通过 gettext 取得的文字（Python 3.10 到 3.14）。
# The texts argparse takes through gettext (Python 3.10 to 3.14).
_ARGPARSE = {
    "usage: ": "用法：",
    "options": "选项",
    "optional arguments": "选项",
    "positional arguments": "位置参数",
    "subcommands": "命令",
    "%(heading)s:": "%(heading)s：",
    "show this help message and exit": "显示帮助并退出",
    "show program's version number and exit": "显示版本号并退出",
    " (default: %(default)s)": "（默认：%(default)s）",
    "the following arguments are required: %s": "缺少必需的参数：%s",
    "one of the arguments %s is required": "必须提供以下参数之一：%s",
    "unrecognized arguments: %s": "无法识别的参数：%s",
    "expected one argument": "需要一个参数值",
    "expected at most one argument": "最多需要一个参数值",
    "expected at least one argument": "至少需要一个参数值",
    "not allowed with argument %s": "不能与参数 %s 同时使用",
    "ignored explicit argument %r": "忽略了多余的参数值 %r",
    "unexpected option string: %s": "意外的选项：%s",
    "ambiguous option: %(option)s could match %(matches)s": (
        "有歧义的选项：%(option)s 可以匹配 %(matches)s"
    ),
    "invalid choice: %(value)r (choose from %(choices)s)": (
        "无效的选项：%(value)r（可选：%(choices)s）"
    ),
    "invalid %(type)s value: %(value)r": "无效的 %(type)s 值：%(value)r",
    "unknown parser %(parser_name)r (choices: %(choices)s)": (
        "未知的命令 %(parser_name)r（可选：%(choices)s）"
    ),
    "argument %(argument_name)s: %(message)s": "参数 %(argument_name)s：%(message)s",
    "%(prog)s: error: %(message)s\n": "%(prog)s：错误：%(message)s\n",
}


# 不放在行首的标点，和不放在行尾的标点。
# Punctuation that never starts a line, and punctuation that never ends one.
_NO_LINE_START = frozenset("，。、；：？！）」』】》,.;:?!)")
_NO_LINE_END = frozenset("（「『【《(")


def _width(text: str) -> int:
    """text 在终端中占的列数：宽字符和全角字符（如中文）占 2 列。
    The number of terminal columns text takes: wide and fullwidth characters, such as Chinese,
    take 2.
    """
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _wrap(text: str, width: int) -> list[str]:
    """按终端列宽 width 把 text 折成多行，含宽字符时供 argparse 的帮助文字使用。
    Wrap text into lines of at most width terminal columns, for argparse help text holding
    wide characters.

    连续空白算一个空格，可以在空白处和每个宽字符前后换行；_NO_LINE_START 中的标点不放在
    行首，_NO_LINE_END 中的不放在行尾。超过 width 的单词（例如网址）单独占一行，不拆开。
    textwrap 只在空白处换行，并按字符个数而不是列宽计算，中文句子因此会超出行宽。
    Runs of whitespace count as one space; a line may break at whitespace and before or after
    every wide character, but punctuation in _NO_LINE_START never starts a line and
    punctuation in _NO_LINE_END never ends one. A word wider than width, such as a URL, takes a
    line of its own and is not split. textwrap breaks only at whitespace and counts characters
    rather than columns, so Chinese sentences overflow the line.
    """
    # 每个单位是 (文字, 前面是否有空格)；窄字符连成一个单词，宽字符各自成为一个单位。
    # Each unit is (text, whether a space precedes it); narrow characters join into a word and
    # every wide character is a unit of its own.
    units: list[tuple[str, bool]] = []
    space = False
    for char in text:
        if char.isspace():
            space = bool(units)
            continue
        wide = _width(char) == 2
        if units and not space and not wide and _width(units[-1][0][-1]) == 1:
            units[-1] = (units[-1][0] + char, units[-1][1])
        else:
            units.append((char, space))
        space = False
    # 避头尾：行首禁用的标点并入前一个单位，行尾禁用的标点并入后一个单位。
    # Line-start and line-end rules: punctuation that cannot start a line joins the unit before
    # it, and punctuation that cannot end a line joins the unit after it.
    merged: list[tuple[str, bool]] = []
    for unit in units:
        if (
            merged
            and not unit[1]
            and (unit[0][0] in _NO_LINE_START or merged[-1][0][-1] in _NO_LINE_END)
        ):
            merged[-1] = (merged[-1][0] + unit[0], merged[-1][1])
        else:
            merged.append(unit)

    lines: list[str] = []
    line = ""
    for word, spaced in merged:
        separator = " " if spaced and line else ""
        if line and _width(line) + _width(separator + word) > width:
            lines.append(line)
            line = word
        else:
            line += separator + word
    if line:
        lines.append(line)
    return lines


def localize_argparse() -> None:
    """让 argparse 自带的文字（usage、选项标题、参数错误）在中文环境下输出中文，并按列宽折行。
    Make argparse's own texts (usage, section titles, argument errors) Chinese in a Chinese
    environment, and wrap help text by column width.

    argparse 在模块内用 gettext 的 _ 取这些文字；这里把那个函数换成按当前语言翻译的版本，
    表中没有的文字保持英文。含宽字符的帮助和说明文字改用 _wrap() 折行，其余文字仍由 textwrap
    处理；Raw* 格式类保持原样。重复调用没有额外效果。
    argparse takes these texts through the gettext function _ of its module; this replaces
    that function with one that translates for the current language, and texts outside the
    table stay in English. Help and description text holding wide characters is wrapped by
    _wrap(), other text still by textwrap; the Raw* formatter classes are unchanged. Calling it
    again has no further effect.
    """
    current = argparse._  # type: ignore[attr-defined]
    if getattr(current, "xr_localized", False):
        return

    def translate(message: str) -> str:
        """当前语言下 argparse 的一条文字。
        One argparse text in the current language.
        """
        if chinese() and message in _ARGPARSE:
            return _ARGPARSE[message]
        return str(current(message))

    split_lines = argparse.HelpFormatter._split_lines
    fill_text = argparse.HelpFormatter._fill_text

    def _split_lines(self: argparse.HelpFormatter, text: str, width: int) -> list[str]:
        """帮助文字含宽字符时按列宽折行。
        Wrap help text by column width when it holds wide characters.
        """
        if _width(text) == len(text):
            return split_lines(self, text, width)
        return _wrap(text, width)

    def _fill_text(self: argparse.HelpFormatter, text: str, width: int, indent: str) -> str:
        """说明文字含宽字符时按列宽折行，每行加上 indent。
        Wrap description text by column width when it holds wide characters, each line
        prefixed with indent.
        """
        if _width(text) == len(text):
            return fill_text(self, text, width, indent)
        return "\n".join(indent + line for line in _wrap(text, width - len(indent)))

    translate.xr_localized = True  # type: ignore[attr-defined]
    argparse._ = translate  # type: ignore[attr-defined]
    argparse.HelpFormatter._split_lines = _split_lines  # type: ignore[method-assign]
    argparse.HelpFormatter._fill_text = _fill_text  # type: ignore[method-assign]
