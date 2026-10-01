"""验证输出语言的判断、消息选择和 argparse 文字的翻译。
Test how the output language is chosen, message selection and argparse text translation.
"""

from __future__ import annotations

import argparse
import sys
import textwrap

import pytest

from xr_syntax.cpp import code_tokens
from xr_syntax.i18n import _width, _wrap, chinese, localize_argparse, tr


def test_the_first_set_variable_chooses_the_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 XR_LANG 优先，其次依次是 LANGUAGE、LC_ALL、LC_MESSAGES、LANG。
    Verify XR_LANG comes first, then LANGUAGE, LC_ALL, LC_MESSAGES and LANG in turn.
    """
    for name in ("XR_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    assert chinese()
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    assert not chinese()
    monkeypatch.setenv("LANGUAGE", "zh_CN:en")
    assert chinese()
    monkeypatch.setenv("XR_LANG", "en")
    assert not chinese()
    assert tr("unclosed", "未闭合") == "unclosed"


def test_library_messages_follow_the_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 xr-syntax 的诊断信息按当前语言输出。
    Verify xr-syntax diagnostics are written in the current language.
    """
    with pytest.raises(ValueError, match="^unclosed block comment$"):
        code_tokens("/* open")
    monkeypatch.setenv("XR_LANG", "zh")
    with pytest.raises(ValueError, match="^未闭合的块注释$"):
        code_tokens("/* open")


def test_argparse_texts_are_translated_in_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证中文环境下 argparse 的 usage、标题和参数错误是中文，英文环境下不变。
    Verify argparse usage, titles and argument errors are Chinese in a Chinese environment and
    unchanged in English.
    """
    localize_argparse()
    localize_argparse()

    def parser() -> argparse.ArgumentParser:
        """一个带位置参数的 parser；标题和帮助文字在创建时取当前语言。
        A parser with one positional argument; titles and help take the current language
        when it is created.
        """
        result = argparse.ArgumentParser(
            prog="tool", formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        result.add_argument("name")
        result.add_argument("--count", default=1, help="repeat")
        return result

    help_text = parser().format_help()
    assert help_text.startswith("usage: tool [-h] [--count COUNT] name\n")
    assert "repeat (default: 1)" in help_text
    monkeypatch.setenv("XR_LANG", "zh")
    help_text = parser().format_help()
    assert help_text.startswith("用法：tool [-h] [--count COUNT] name\n")
    # Python 3.10 的 argparse 自己拼标题后的冒号和默认值说明，不经过 gettext，所以这两处在
    # 3.10 上保持英文；3.11 起都会翻译。
    # Python 3.10's argparse appends the colon after headings and the default-value note itself,
    # not through gettext, so these two stay English on 3.10; from 3.11 on both are translated.
    translated = sys.version_info >= (3, 11)
    assert ("位置参数：" if translated else "位置参数:") in help_text
    assert "显示帮助并退出" in help_text
    assert ("repeat（默认：1）" if translated else "repeat (default: 1)") in help_text
    with pytest.raises(SystemExit):
        parser().parse_args([])


def test_wide_text_wraps_by_column_width() -> None:
    """验证宽字符按 2 列计算、宽字符之间可以换行，以及避头尾。
    Verify wide characters count as 2 columns, lines may break between them, and punctuation
    stays off the wrong line ends.
    """
    assert _wrap("甲乙丙丁", 4) == ["甲乙", "丙丁"]
    assert _wrap("甲，乙", 2) == ["甲，", "乙"]
    assert _wrap("乙（甲）丙", 6) == ["乙", "（甲）", "丙"]
    assert _wrap("用 java -jar 启动", 8) == ["用 java", "-jar 启", "动"]


def test_help_holding_chinese_wraps_by_column_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证含中文的帮助不超过列宽、不拆开网址，纯英文帮助仍由 textwrap 折行。
    Verify help holding Chinese stays within the columns without splitting a URL, while
    English help is still wrapped by textwrap.
    """
    localize_argparse()
    monkeypatch.setenv("COLUMNS", "60")
    text = (
        "缺少 LibXR 时从哪里克隆：auto、github，或基础地址、仓库地址（默认：auto）；"
        ".gitmodules 始终记录 https://github.com/xrobot-org/libxr.git"
    )
    parser = argparse.ArgumentParser(prog="tool")
    parser.add_argument("--source", help=text)
    lines = parser.format_help().splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith("  --source SOURCE"))
    # 帮助的第一行与选项同行。
    # The first help line shares the line of the option.
    body = [lines[first].split("SOURCE", 1)[1], *lines[first + 1 :]]
    assert "".join(line.strip() for line in body).replace(" ", "") == text.replace(" ", "")
    assert all(_width(line) <= 58 for line in lines[first:-1])
    assert body[-1].strip() == "https://github.com/xrobot-org/libxr.git"
    assert not any(line.strip()[:1] in "，。、；：）" for line in body)

    english = "where a missing LibXR is cloned from: auto, github, or a base or repository URL"
    formatter = argparse.HelpFormatter("tool")
    assert formatter._split_lines(english, 30) == textwrap.wrap(english, 30)
