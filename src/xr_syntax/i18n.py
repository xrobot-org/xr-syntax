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


def localize_argparse() -> None:
    """让 argparse 自带的文字（usage、选项标题、参数错误）在中文环境下输出中文。
    Make argparse's own texts (usage, section titles, argument errors) Chinese in a Chinese
    environment.

    argparse 在模块内用 gettext 的 _ 取这些文字；这里把那个函数换成按当前语言翻译的版本，
    表中没有的文字保持英文。重复调用没有额外效果。
    argparse takes these texts through the gettext function _ of its module; this replaces
    that function with one that translates for the current language, and texts outside the
    table stay in English. Calling it again has no further effect.
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

    translate.xr_localized = True  # type: ignore[attr-defined]
    argparse._ = translate  # type: ignore[attr-defined]
