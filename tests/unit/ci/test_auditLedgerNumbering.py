# -*- coding: utf-8 -*-
"""台账格号唯一性守卫（§6-128 的常驻面）。

要守的东西不"行数写错"那么轻：共享工作树里多个会话同日往同一份台账追加，号次靠人脑记
`max+1` ⇒ **同号双格**是常态而非意外（本会话实测：一天之内撞了 100/102/110/114/119/125/126
七次，其中两次靠人肉让号）。同号双格的代价是"错号比没错更难查"——两个读者会各自引用
同一号却读到不同内容，而后人完全无从发现。

三条都可失败：
① 台账正文里每个 `^N. **` 形式的格号必须唯一；
② 扫描面不得收缩（标题数少于下限即红——防止"扫了个空目录所以永远绿"）；
③ 反空转：临时拼一份含重复号的台账文本，判据必须抓到。
"""

from __future__ import annotations

import re

import pytest

LEDGER = (
    __import__('pathlib').Path(__file__).resolve().parents[3]
    / 'audit-reports' / 'simplification-audit-2026-10-05.md'
)

_HEADING = re.compile(r'^(\d{2,3})\. \*\*', re.MULTILINE)

# 本卷已写到 120+ 格；低于这个下限只可能是扫描面出问题，不是"变短了"。
_MIN_HEADINGS = 100


def _duplicateNumbers(text: str) -> dict:
    counts: dict = {}
    for match in _HEADING.finditer(text):
        counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    return {num: c for num, c in counts.items() if c > 1}


def testLedgerEntryNumbersAreUnique():
    assert LEDGER.is_file(), '台账路径变了——这条守卫已经在扫不存在的文件'
    text = LEDGER.read_text(encoding='utf-8')
    numbers = _HEADING.findall(text)
    assert len(numbers) >= _MIN_HEADINGS, (
        '只认出 %d 个格号（下限 %d）——标题形态或扫描面变了，'
        '这时"没有重复"不代表任何事' % (len(numbers), _MIN_HEADINGS))

    dup = _duplicateNumbers(text)
    assert not dup, (
        '台账里出现同号双格：%s。多会话同日追加时号次必须现取现用（`grep -oE "^1[0-9]{2}\\. " | sort -n | tail`），'
        '撞号后由**后来者让号**并在格内写号次说明——不许两边都留着同号' % dup)


@pytest.mark.parametrize('body, expected', [
    ('98. **甲**\n\n99. **乙**\n', {}),
    ('98. **甲**\n\n98. **甲重复**\n', {'98': 2}),
    ('12. **a**\n12. **b**\n13. **c**\n13. **d**\n', {'12': 2, '13': 2}),
])
def testDetectorCountsDuplicatesNotHeadings(body, expected):
    """反空转：重复必须被点名，正常文本不许误报。

    样本一律用两位以上号——本卷的格号形态就是 `^N. **` 且早已过百，
    一位数样本会测到"正则根本不认一位号"这件事上，那是另一回事。
    """
    assert _duplicateNumbers(body) == expected
