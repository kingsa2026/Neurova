# -*- coding: utf-8 -*-
"""表格分隔行判定的线性化守卫（CodeQL py/polynomial-redos 处置）。

旧正则 ``^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$`` 的嵌套量词在恶意行
（大量管道/冒号但无连续双横线）上会多项式回溯。新实现为单遍线性扫描。
本测试钉两件事：①与旧正则在常规/边界行上判定等价；②对抗性行上线性完成。
"""
import re
import time

from neurova.knowledge.splitter import _isTableSeparator

_OLD_SEP = re.compile(r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$")

_CORPUS = [
    "| --- | --- |",
    "|:---|---:|",
    " :--- | :---: ",
    "---",
    "- - -",
    "|-|",
    "|| --- ||",
    "| | --- | |",
    "| abc | def |",
    "not a separator",
    "",
    "   ",
    "||||||",
    "| : | : |",
    "-----",
    "|--|--|",
]


def test_equivalent_to_old_regex_on_corpus():
    for line in _CORPUS:
        assert _isTableSeparator(line) == bool(_OLD_SEP.match(line)), line


def test_adversarial_line_completes_linearly():
    """旧正则在此形态上会多项式回溯；新实现必须线性完成（1s 内）。"""
    evil = (":|" * 50000) + "x"  # ~100KB，无连续双横线 → 必然不匹配
    started = time.monotonic()
    result = _isTableSeparator(evil)
    elapsed = time.monotonic() - started
    assert result is False
    assert elapsed < 1.0, f"对抗性行判定耗时 {elapsed:.2f}s——必须线性"


def test_adversarial_with_dashes_still_matches():
    evil = ("|:|" * 40000) + "--|"  # 大量干扰 + 结尾连续双横线
    started = time.monotonic()
    assert _isTableSeparator(evil) is True
    assert time.monotonic() - started < 1.0
