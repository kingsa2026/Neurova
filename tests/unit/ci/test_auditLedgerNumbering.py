# -*- coding: utf-8 -*-
"""台账格号唯一性守卫（§6-128 的常驻面）。

要守的东西不"行数写错"那么轻：共享工作树里多个会话同日往同一份台账追加，号次靠人脑记
`max+1` ⇒ **同号双格**是常态而非意外（本会话实测：一天之内撞了 100/102/110/114/119/125/126
七次，其中两次靠人肉让号）。同号双格的代价是"错号比没错更难查"——两个读者会各自引用
同一号却读到不同内容，而后人完全无从发现。

四条都可失败：
① 台账正文里每个 `^N. **` 形式的格号必须唯一；
② 扫描面不得收缩（标题数少于下限即红——防止"扫了个空目录所以永远绿"）；
③ 反空转：临时拼一份含重复号的台账文本，判据必须抓到；
④ 最近落下的那几格的号次必须沿文件顺序前进——唯一性只挡住"同号双格"，
   挡不住"号在别处"（PR #365 构建 `cnb-iom-1k5us8cmk-003` 分片 2 的现场）。
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


def _tailBreaks(text: str, recent: int = 20) -> list:
    """只看「最近落下的那几格」的号次顺序：它们必须按文件顺序单调前进。

    为什么不扫全卷：存量里另有 15 处早年的回退（`238 → 195`、`272 → 120` 这类，是当时
    的并入与让号留下的），把它们一起判红就是"新判据第一天全卷红"——那只会被读成判据坏了。
    本条咬的是**新落格**：本卷尾部 `recent` 格必须是一个严格递增段，且段首不得低于它前面
    那一格。谁把新号插回旧号段中间，谁当场红。
    """
    nums = [int(m.group(1)) for m in _HEADING.finditer(text)]
    tail = nums[-recent:]
    breaks = [(tail[i], tail[i + 1]) for i in range(len(tail) - 1) if tail[i + 1] <= tail[i]]
    if len(nums) > recent and tail[0] <= nums[-recent - 1]:
        breaks.insert(0, (nums[-recent - 1], tail[0]))
    return breaks


def testRecentLedgerEntryNumbersAdvanceForwardOnly():
    """最近这些格必须沿文件顺序前进：唯一只挡住"同号双格"，挡不住"号插在别处"。

    实测现场（PR #365 构建 `cnb-iom-1k5us8cmk#003` 分片 2）：分支那格原取 §6-418，与
    main 侧同号，解冲突时按「后来者让号」改记 §6-435——**只改了号，没挪位置**，于是
    435 依旧夹在 417 与 418 之间，尾部是 430…434。同号双格因此消失，而「435 在 417
    后面」这件事没有任何东西会红：唯一性判据全绿，读者按号序翻目录却找不到。
    """
    assert LEDGER.is_file(), '台账路径变了——这条守卫已经在扫不存在的文件'
    text = LEDGER.read_text(encoding='utf-8')
    total = len(_HEADING.findall(text))
    assert total >= _MIN_HEADINGS, (
        '只认出 %d 个格号（下限 %d）——扫描面变窄时"号次有序"什么都不证明'
        % (total, _MIN_HEADINGS))

    breaks = _tailBreaks(text)
    assert not breaks, (
        '台账最近落下的格号出现 %d 处回退：%s（前一号 -> 后一号）。让号要连位置一起让——'
        '只改号次而不把这格挪到尾部，新号就插进了旧号段中间' % (len(breaks), breaks))


@pytest.mark.parametrize('body, expected', [
    ('98. **甲**\n99. **乙**\n', []),
    ('98. **甲**\n105. **乙**\n99. **丙**\n', [(105, 99)]),
    ('98. **甲**\n99. **乙**\n99. **乙重复**\n', [(99, 99)]),
    ('98. **甲**\n99. **乙**\n101. **丙**\n102. **丁**\n', []),
])
def testTailBreakDetectorCountsRegressionsNotDuplicates(body, expected):
    """反空转：回退必须被点名，正常前进不被当成回退。

    重复号那格同时给出 `(99, 99)`：唯一性是另一条判据的活，这里只如实报"没有前进"，
    两条判据各咬一头，不互相冒充。
    """
    assert _tailBreaks(body) == expected
