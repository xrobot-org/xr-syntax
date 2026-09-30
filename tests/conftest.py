"""测试统一使用英文输出，与运行机器的语言无关。
Tests use English output whatever the language of the machine running them.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def english_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """把输出语言固定为英文；需要中文的测试自己改 XR_LANG。
    Fix the output language to English; a test that needs Chinese sets XR_LANG itself.
    """
    monkeypatch.setenv("XR_LANG", "en")
