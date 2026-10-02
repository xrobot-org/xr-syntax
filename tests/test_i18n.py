"""验证输出语言的判断、消息选择和 argparse 文字的翻译。
Test how the output language is chosen, message selection and argparse text translation.
"""

from __future__ import annotations

import argparse
import sys
import textwrap

import pytest

from xr_syntax.cpp import code_tokens
from xr_syntax.i18n import chinese, localize_argparse, tr


def _help_lines(text: str, columns: int, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """帮助文字 text 在终端宽 columns 列时折成的各行，去掉缩进。
    The lines help text takes at a terminal width of columns, without indentation.
    """
    localize_argparse()
    monkeypatch.setenv("COLUMNS", str(columns))
    parser = argparse.ArgumentParser(prog="tool", add_help=False)
    parser.add_argument("name", help=text)
    block = parser.format_help().split("\n  name", 1)[1].splitlines()
    return [line.strip() for line in block if line.strip()]


def test_the_first_set_variable_chooses_the_language(monkeypatch: pytest.MonkeyPatch) -> None:
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
    with pytest.raises(ValueError, match="^unclosed block comment$"):
        code_tokens("/* open")
    monkeypatch.setenv("XR_LANG", "zh")
    with pytest.raises(ValueError, match="^未闭合的块注释$"):
        code_tokens("/* open")


def test_argparse_texts_are_translated_in_chinese(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
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
    assert capsys.readouterr().err == (
        "用法：tool [-h] [--count COUNT] name\ntool：错误：缺少必需的参数：name\n"
    )


# 终端宽 17 列时帮助文字有 11 列。
# At a terminal width of 17 columns, help text has 11 columns.
@pytest.mark.parametrize(
    ("text", "lines"),
    [
        pytest.param("甲乙丙丁戊己庚辛", ["甲乙丙丁戊", "己庚辛"], id="wide-characters"),
        pytest.param("甲乙丙丁戊，己", ["甲乙丙丁", "戊，己"], id="no-comma-at-line-start"),
        pytest.param("甲乙丙丁（戊己）庚", ["甲乙丙丁", "（戊己）庚"], id="no-bracket-at-line-end"),
        pytest.param("用 java -jar 启动程序", ["用 java", "-jar 启动程", "序"], id="whole-words"),
        pytest.param("abcdefghij甲乙", ["abcdefghij", "甲乙"], id="break-before-a-wide-character"),
        pytest.param(
            "甲 https://a.example/xyz 乙",
            ["甲", "https://a.example/xyz", "乙"],
            id="overlong-word-on-its-own-line",
        ),
    ],
)
def test_wide_help_text_wraps_by_column_width(
    text: str, lines: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _help_lines(text, 17, monkeypatch) == lines


def test_english_help_text_wraps_as_argparse_wraps_it(monkeypatch: pytest.MonkeyPatch) -> None:
    english = "where a missing LibXR is cloned from: auto, github, or a base or repository URL"
    # 终端宽 40 列时帮助文字有 30 列。
    # At a terminal width of 40 columns, help text has 30 columns.
    assert _help_lines(english, 40, monkeypatch) == textwrap.wrap(english, 30)
