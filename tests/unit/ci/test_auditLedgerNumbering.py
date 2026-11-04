# -*- coding: utf-8 -*-
"""台账格号唯一性守卫（§6-128 的常驻面）。

要守的东西不"行数写错"那么轻：共享工作树里多个会话同日往同一份台账追加，号次靠人脑记
`max+1` ⇒ **同号双格**是常态而非意外（本会话实测：一天之内撞了 100/102/110/114/119/125/126
七次，其中两次靠人肉让号）。同号双格的代价是"错号比没错更难查"——两个读者会各自引用
同一号却读到不同内容，而后人完全无从发现。

五条都可失败：
① 台账正文里每个 `^N. **` 形式的格号必须唯一；
② 扫描面不得收缩（标题数少于下限即红——防止"扫了个空目录所以永远绿"）；
③ 反空转：临时拼一份含重复号的台账文本，判据必须抓到；
④ 最近落下的那几格的号次必须沿文件顺序前进——唯一性只挡住"同号双格"，
   挡不住"号在别处"（PR #365 构建 `cnb-iom-1k5us8cmk-003` 分片 2 的现场）；
⑤ **被正文引用的格号必须能在本卷定位到那一格**（§6-472 新增）。前两把尺都只看条目行，
   引用面从来没人核：并发让号或分支重写把某格抹掉之后，正文里那些 `§6-N` 就指向了不存在的格，
   而读者按号翻目录只会以为是自己找不到。
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


#: 引用面的取数口：正文里 `§6-N` 形式的号。`§6-4[0-9][0-9]` 这类正则字面量不会被匹配到。
_CITE = re.compile(r"§6-(\d{2,3})")

#: 记账句词汇：这类句子里出现的号是"下一个空号"的指针或让号叙述，**不是对某一格的引用**。
#: 这张表不是豁免名单，是把口径定准——§6-471 就是没辨这两类，把 8 处「下一枚空号现查 §6-N」
#: 和「条目行最大 458 ⇒ 后继从 §6-459 起」正常形态当成"悬空引用/后继写反"登进了账。
_POINTER_WORDS = re.compile(
    r"(下一枚空号现查|下批从|后继批次从|后继从|空号至|现算最大|以现算为准|写前必须现场重取"
    r"|若并发会话先落格|让号|撞号|改取|改记|原拟|本应落|号位说明|被并发会话"
    # 声明"这个号不在本卷"的句子本身就是悬空登记，不是又一次悬空引用
    r"|从未建档|没有条目行|定位不到|悬空)"
)

#: 转述形态：号被引号包着 ⇒ 那句在说"某人某文写过这个号"，不是在指向本卷某一格。
#: 不分开就会把 §6-221 那种"提交正文里写的是 §6-221，后来让号了"的自纠记成悬空引用。
_QUOTED_SPANS = (re.compile(r"「[^」]*」"), re.compile(r'"[^"]*"'), re.compile(r"“[^”]*”"))


def _isQuoted(line: str, at: int) -> bool:
    for span in _QUOTED_SPANS:
        for m in span.finditer(line):
            if m.start() <= at < m.end():
                return True
    return False


def _entryAnchors(text: str) -> set:
    """本卷能定位到的格号：主格 `^N. **` 与续格 `^N. (续` 都算。

    续格算定位点：引用者对着 `121. (续)` 同样读得到内容。把它判成悬空会逼人再去并续格，
    那不是本条要咬的事；而"宽正则把续格误判成重号"那一坑由 `_HEADING` 单口径挡住。
    """
    anchors = set()
    for pattern in (r"^(\d{2,3})\. \*\*", r"^(\d{2,3})\. \(续"):
        anchors |= {int(m.group(1)) for m in re.finditer(pattern, text, re.M)}
    return anchors


def _sentenceOf(line: str, at: int) -> str:
    """取出包含该命中的那一句（按 。／；断句）——判"这是引用还是记账句"只看这一句。"""
    start = max(line.rfind("。", 0, at), line.rfind("；", 0, at)) + 1
    end = line.find("。", at)
    return line[start:] if end < 0 else line[start:end + 1]


def _danglingCitations(text: str) -> list:
    """返回 [(号, 行号)]：正文以 `§6-N` 引用了本卷定位不到的格号。"""
    anchors = _entryAnchors(text)
    out = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in _CITE.finditer(line):
            num = int(match.group(1))
            if num in anchors:
                continue
            if _POINTER_WORDS.search(_sentenceOf(line, match.start())) or _isQuoted(line, match.start()):
                continue
            out.append((num, lineno))
    return out


def testCitedCellNumbersHaveEntryLines():
    """被引用的号必须查得到格：号在并发让号或分支重写里消失时，正文得跟着改指向。

    这一条是 §6-472 现场立起来的：`§6-420` 那一格在两次撞号的让号过程中没有留下条目行，
    而正文有两处按号引用它（一处说"与 §6-420 同族同现场"，一处说"与 §6-420 在 console 修掉
    的是同一个洞"）——两个读者按号翻目录，一个也读不到。
    """
    assert LEDGER.is_file(), "台账路径变了——这条守卫已经在扫不存在的文件"
    text = LEDGER.read_text(encoding="utf-8")
    anchors = _entryAnchors(text)
    assert len(anchors) >= _MIN_HEADINGS, (
        "只认出 %d 个格号（下限 %d）——定位面收缩时「引用都查得到格」什么都不证明"
        % (len(anchors), _MIN_HEADINGS))

    dangling = _danglingCitations(text)
    assert not dangling, (
        "正文引用了本卷定位不到的格号（读者按号找不到格）：\n"
        + "\n".join("  §6-%d 在行 %d" % (n, ln) for n, ln in dangling)
        + "\n修法：把它改指向仍在的格（先核内容同不同族，别拿近似号糊过去），"
          "或如实写明「那一格的条目行已在让号/重写中丢失」——不许臆造补写内容。"
    )


@pytest.mark.parametrize('body, expected', [
    # 记账句里的号不是引用：那号本来就是留给下一批的
    ('120. **甲**\n    - **下一枚空号现查 §6-121。**\n', []),
    ('120. **甲**\n    - 条目行最大 **122**、引用面最大 **118** ⇒ 后继从 **§6-123** 起。\n', []),
    # 让号叙述同理：号是被让出去/撞掉的那一个
    ('120. **甲**\n    - 本条原拟 §6-119，与并发会话撞号后改取 120。\n', []),
    # 续格算定位点：引用得到，就不算悬空
    ('120. **甲**\n121. (续) **乙**\n正文引用 §6-121\n', []),
    # 转述不算引用：那句说的是"别人写过这个号"
    ('120. **甲**\n    - 提交正文里写的是"台账 §6-121 随下一笔"，后来让号了。\n', []),
    ('120. **甲**\n    - 三处以「E 批 §6-121」为引用落点。\n', []),
    # 声明该号缺失的句子本身就是登记，不是又一次悬空
    ('120. **甲**\n    - §6-121 从未建档，属悬空引用。\n', []),
    # 但"引用了却查不到"必须点名——上面三种排除口径不许把真悬空一起放掉
    ('120. **甲**\n    - 形态与 §6-121 第四格同源。\n', [(121, 2)]),
    # 真正文引用而本卷无格 ⇒ 必须点名
    ('120. **甲**\n正文引用 §6-121\n', [(121, 2)]),
    # 引用面不被"号存在于别处"糊弄：主格在就不报
    ('120. **甲**\n121. **乙**\n正文引用 §6-121\n', []),
])
def testDanglingCitationDetectorSeparatesRecordsFromCitations(body, expected):
    """反空转：记账句与续格不得误报，真正悬空必须点名——两者都要有样本。"""
    assert _danglingCitations(body) == expected


def _droppedCells(headText, workText):
    """HEAD 里有、工作树副本查不到的条目号。

    并发会话把更早的整份缓冲区写回磁盘时，盘上副本会比 HEAD 少格——三把尺都看不见这件事：
    尾号那条尺读的是盘上副本（少一格照样单调前进），引用面那条读的是别的号（盘上仍在）。
    """
    def nums(t):
        return {m.group(1) for m in re.finditer(r'(?m)^(\d{2,3})\. ', t)}
    return sorted(nums(headText) - nums(workText), key=int)


def testWorktreeCopyKeepsEveryCommittedCell():
    """工作树副本不得比 HEAD 少格（2026-11-04 实测两次被并发撤格，三把尺全静默）。"""
    import subprocess

    assert LEDGER.is_file(), "台账路径变了——这条守卫已经在扫不存在的文件"
    root = LEDGER.parents[1]
    rel = LEDGER.relative_to(root).as_posix()
    shown = subprocess.run(['git', 'show', 'HEAD:' + rel], capture_output=True, cwd=str(root))
    if shown.returncode != 0:
        pytest.skip('拿不到 HEAD 版台账（浅克隆或无 git），本格不适用')
    headText = shown.stdout.decode('utf-8', 'replace')
    dropped = _droppedCells(headText, LEDGER.read_text(encoding='utf-8'))
    assert dropped == [], (
        '这些台账格在 HEAD 里有、在工作树副本里查不到：%s。多半是并发会话把更早的整份缓冲区'
        '写回了磁盘。处置只有一件事：按盘上行尾把那一格**原文**接回去，'
        '不要整份改写别人在途的字节。' % dropped)


def testDroppedCellDetectorNamesOnlyHeadOnlyCells():
    """反证格：探测器只点「HEAD 有、盘上没有」；同号不报，盘上多出的格也不报。"""
    NL = chr(10)
    head = '110. **甲**' + NL + '111. **乙**' + NL
    assert _droppedCells(head, head) == []
    assert _droppedCells(head, '110. **甲**' + NL) == ['111']
    assert _droppedCells('110. **甲**' + NL, head) == [], '盘上多出的格不该被报成撤账'

