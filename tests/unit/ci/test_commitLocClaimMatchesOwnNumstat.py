# -*- coding: utf-8 -*-
r"""提交正文里写过的「净 LOC」数字，必须与那一笔自己的 numstat 逐池相等（只降不升的口径：错了就红）。

为什么要有它（不是"下次注意"）：同一处错在本会话连着第五遭——批 59 的 `287fe183` 正文里就写着
「第一次成文写的是 +16，是没等 `--cached --numstat` 读数就成文」的勘误，本批又复现两遭
（生产池写成 −2 实为 +1、docs 笔写成 +50 实为 +20）。**每次都是靠事后发现＋趁未推送 amend 补救**，
说明缺的不是自觉，是"成文之后自动复算一遍"的通道。教义第 1 条的判据在这里就是：把这条纪律
落成会红的格子。

范围只取 `origin/main..HEAD`（未推送窗口），不是全历史——两个理由，都写在下面的格子里：
① 这是唯一还能就地修的窗口（推送后的号不许改写，211/230 那一族）；
② 老批次的写法是**跨笔合计**（如「判据笔 +394/−285（净 +109）＝新档 128…」），单笔复算套不上，
   把它们拉进来只会造出一堆无法处置的常驻红。

正因为窗口可能为空（CI 里推送完成后就是空集），本档不许只跑那条格——另配三格有对象的：
一条**造出来的坏号**（`git commit-tree`，不碰分支）、一条**同样造出来的好号**做控制、
一条**取数口径对账**（防止正则哪天匹配不上，"0 条"被读成"全对"）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

#: 正文声明的池名 → 复算时用的池键。**这一份是词汇的唯一出处**：`CLAIM_RE` 的备选、
#: `_poolTotals` 的键、`_mismatches` 的取键都由它生成。
#:
#: 缺陷形态（本批实测）：同一份词汇曾散在三处——一张无人引用的「池名→归属谓词」表、
#: 一条手写的正则备选（七个名字）、一个只备了两个池键的求和表。于是正文写「基建池 +3/−0」
#: 时门禁抛 `KeyError: '基建池'`：正则认它，复算表里没有它。崩在自家词表上的判据等于没判据，
#: 而报错还长得像"你的数字写错了"。
_POOL_ALIASES = {
    "生产池": "生产池",
    "测试/基建池": "测试/基建池",
    "基建池": "测试/基建池",
    "测试池": "测试/基建池",
}

#: `本格/本笔` 声明的是这一笔的**全部**文件合计
_TOTAL_MARKERS = ("本格", "本笔", "全笔")

#: 括号定界的一小段（夹注）。夹注放的是"这一块按哪一池算"的**口径说明**，不是本笔行数；
#: 与引号、反引号同属"引用/说明"位置，故并进同一份区间集合。
#: 它只豁免自己圈住的那一段——夹注写在声明**之后**时，声明本身仍是本笔的账。
_ASIDE_RE = re.compile(r"（[^（）]*）|\([^()]*\)")

#: 预存红：**已推送或已入库、正文按平台纪律不许改写**的那几笔（短号 → 当时写错的声明）。
#: 值只用于反证"这条豁免还该在"（`testBaselineEntriesStillPointAtRealMismatches`），
#: 不参与报告生成。
_KNOWN_BAD_COMMITS: dict = {
    # 空表不是"这条判据没在用"：豁免机制本身由 `testBaselineEntriesStillPointAtRealMismatches`
    # 逐条反证，表里留一个已经修好或已经不在仓里的条目，就是下一次真错的隐身衣。
    # 唯一那条 `e87ce9b9` 已在它自己那笔的正文改正后退役（该提交同时被换链重写，
    # 仓里已不存在这一枚），故整条删掉而不是把 sha 改指新提交——豁免要挡的是
    # "写错的正文被放过"，正文已经改对，就没有再挡的对象。
}

#: 本档三枚 subprocess 落点（rev-parse / rev-list / commit-tree）都是仓库内 git 查询，
#: 毫秒级；20s 是给满载机器留的余量。取**低于全局 30s** 的这一形，是为了不去给整档抬父墙——
#: 子进程先到点时报的是诚实的 TimeoutExpired，而不是"整场跑测没了"（§6-402 批 K 口径）。
_GIT_WALL_S = 20

#: 长名排在前面，免得备选被短名截走（`测试/基建池` 必须先于 `基建池` 试）
CLAIM_RE = re.compile(
    r"(?P<label>" + "|".join(sorted({*_POOL_ALIASES, *_TOTAL_MARKERS}, key=len, reverse=True)) + r")"
    r"\s*(?:\*\*\s*)?\+?(?P<adds>\d+)\s*/\s*[−-]\s*(?P<dels>\d+)"
    r"(?:\s*\*\*\s*)?(?:\s*(?:＝|=)\s*净\s*(?P<net>[+-]\d+)\s*(?:\*\*\s*)?)?"
)

#: 声明所处的后缀词 → 复算用的池键。**这一份也是词汇的唯一出处**，与 `_POOL_ALIASES`
#: 并列而不相叠：前者管「我改坏了什么」（production / tests），后者管「我量的是哪一块」。
#: 池名的前缀（`生产`/`测试`/`基建`）从这里派生，别处不再手抄第二份。
_SUFFIX_ALIASES = {"生产": "生产池", "测试": "测试/基建池", "基建": "测试/基建池"}

#: 声明的**前缀**池名：`生产池 **+13/−5` 这类把池名写在数字前面的写法。
#: 正则原本只认"名字紧贴数字"，故 `生产池 **+57/−56`（`**` 夹在中间）整条漏判——
#: 漏判比误判更坏，它让主格在"没声明"上判绿。
_LEADING_POOL_RE = re.compile(
    r"(?P<lead>" + "|".join(sorted((f"{p}池" for p in _SUFFIX_ALIASES), key=len, reverse=True)) + r")"
    r"\s*\**\s*$"
)

_FILES_HEADING_RE = re.compile(r"净 LOC")
#: 池名声明（不带数字的定位用）：`生产池`/`测试/基建池`/`基建池`/`测试池` 出现在句中哪一处
_POOL_NAME_RE = re.compile(
    r"(?P<pool>" + "|".join(sorted(_POOL_ALIASES, key=len, reverse=True)) + r")")

#: 声明之后到**下一处数字声明**之前的那一段：后缀词、数量词都只在这段里认
_DECLTAIL_RE = re.compile(r"(?:(?!\+?\d+\s*/\s*[−-]\s*\d).)*", re.S)

#: 紧跟声明的数量后缀：`+2/-0` 个文件 / `+3/-0` 格——量的是笔数格数，不是行数池
_COUNT_SUFFIX_RE = re.compile(r"[ \t]*(?:\*\*[ \t]*)?(?:个文件|格|条|笔|处)")
_BULLET_RE = re.compile(r"^\s*[-*]\s+")


def _git(*args: str, check: bool = True) -> str:
    """读仓取数口：失败**不许**静默变成空串（`check=False` 是给"先探一下再决定"的调用点）。

    缺陷形态（构建 `cnb-i46-1k5upb7f5#003` 走查）：这里只取 stdout，git 的退出码与 stderr
    一起被丢掉。于是"对象取不到"与"读出来就是空的"在返回值上完全一样，下游把前者解释成
    了后者——报错说的是数据有问题，真因却是取数口没把它读上来（教义第 2 条点名禁止的那一形）。
    """
    proc = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=_GIT_WALL_S)
    if check and proc.returncode != 0:
        raise AssertionError(
            f"`git {' '.join(args)}` 退出码 {proc.returncode}："
            f"{(proc.stderr or proc.stdout).strip()[-300:]}")
    return proc.stdout


def _unpushedRange() -> list:
    """`origin/main..HEAD`；解析不到远端基准则按取数失败处理，不许静默返回空集。"""
    probe = subprocess.run(["git", "rev-parse", "--verify", "origin/main"], cwd=str(REPO),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=_GIT_WALL_S)
    if probe.returncode != 0:
        pytest.fail("origin/main 解析不到——区间取不到基线就等于「无声明」，本格不许据此判绿")
    return [c for c in _git("rev-list", "origin/main..HEAD").split() if c.strip()]


class _ClaimContext:
    """一条声明所在行上的判断依据：后缀词、是不是列表项、行前有没有「净 LOC」标题。

    三个都只读**本行与前几行**的原文，不猜。后缀词取行尾那一枚（`+26/−5 ＝ 净 +21，全落在`
    这类行由此判 `生产`，`+65/−5（含测试档）` 判 `测试`）；行里一个后缀词都没有时，
    才看「净 LOC」标题下的列表项——那是「分池说明」的版式，不是跨池合计。
    """

    def __init__(self, body: str, start: int, end: int) -> None:
        line_start = body.rfind("\n", 0, start) + 1
        self.line = body[line_start:end]
        self.before = body[:line_start]
        self.after = body[end:]
        self.leading = self._leadingPool()
        self.suffix = self._tailSuffix()
        self.listed = bool(_BULLET_RE.match(self.line))
        self.underFiles = self._hasFilesHeading()
        self.count = self._countSuffix()
        self.headingPool = self._headingPool() if (self.listed or self.underFiles) else None

    def _leadingPool(self):
        """紧贴声明前、只隔 `**` 的池名；没有就 `None`。"""
        m = _LEADING_POOL_RE.search(self.line)
        return m.group("lead") if m else None

    def _headingPool(self):
        """这份小计属于哪一池：先看本行里第一处池名，再看标题行里的第一处池名。

        这里只认池名、**不再走 `_claims`**：`_claims` 建 `_ClaimContext`、后者又要
        `headingPool`，递归回来就是死循环（本批实测 `RecursionError`）。一份词汇、
        两处取法：池名声明的位置只有一个判据（`_POOL_NAME_RE`），其余全从它派生。
        """
        rows = [self.line]
        for row in reversed(self.before.splitlines()):
            if row.strip():
                rows.append(row)
                break
        for row in rows:
            m = _POOL_NAME_RE.search(row)
            if m:
                return _POOL_ALIASES[m.group("pool")]
        return None

    def _countSuffix(self):
        """紧跟声明（数字、可选 `**`）的那个数量词；不是数量词就是 `None`。"""
        m = _COUNT_SUFFIX_RE.match(self.after)
        return m.group(0).strip(" *") if m else None

    #: `+2 个文件`、`+3 起`、`+1 号臂`、`+5 %` 里的中文紧跟在数字后面，若被当成池后缀，
    #: `生产`/`测试`/`基建` 就会被这些词隔开而误判。这一份是"哪种中文不算池后缀"的唯一出处。
    _SUFFIX_BREAKS = ("个", "条", "处", "格", "笔", "份", "起", "到", "至", "~", "～",
                      "±", "#", "号", "%", "％", "行", "列", "次", "张")

    def _tailSuffix(self):
        """声明**之后**、下一处数字之前的第一枚后缀词。

        取行尾那一枚是错的：`生产池 +0/-0，测试/基建池 +65/-5` 会把第一枚读成 `测试`——
        判据于是替作者改写了他的话，把生产池的声明拿测试池去复算。后缀只认"领到下一处
        声明为止"的那一段（`+65/-5（含测试档）` 仍是测试）；这一段里没有后缀词就没有。
        """
        segment = _DECLTAIL_RE.match(self.after)
        span = segment.group(0) if segment else self.after
        hits = [(span.find(word), key) for word, key in _SUFFIX_ALIASES.items() if word in span]
        if not hits:
            return None
        at, key = min(hits)
        if span[:at].rstrip().endswith(self._SUFFIX_BREAKS):
            return None
        return key

    def _hasFilesHeading(self) -> bool:
        """「净 LOC」标题行非空且**之前已经出现过带池名的声明**，这一段才算分池说明。

        只认标题不够：单文件笔也常写 `净 LOC：本格 **+21/−0**（清单…）：4 处 1 行`——
        那是标题行与正文同行的**整笔**声明。分池说明的形态是"标题行先给出各池，再逐项说
        钱花在哪"，故要求前文出现过池名。两条一起才成立时，`本格` 才读作"本池"。
        """
        lines = self.before.splitlines()
        for idx in range(len(lines) - 1, -1, -1):
            if not lines[idx].strip():
                continue
            # 标题行自带池名声明（`净 LOC：生产池 +0/-0，测试/基建池 +65/-5`）时，
            # 正文就在这一行里，不必再往前找——本格的小计指的就是它给的第一池
            if not _FILES_HEADING_RE.search(lines[idx]):
                return False
            if _POOL_NAME_RE.search(lines[idx]):
                return True
            return any(name in "\n".join(lines[:idx]) for name in _POOL_ALIASES)
        return False


def _claims(body: str) -> list:
    out = []
    for m in CLAIM_RE.finditer(body or ""):
        ctx = _ClaimContext(body or "", m.start(), m.end())
        out.append({"label": m.group("label"), "adds": int(m.group("adds")),
                    "dels": int(m.group("dels")),
                    "net": int(m.group("net")) if m.group("net") else None,
                    "suffix": ctx.suffix, "listed": ctx.listed, "underFiles": ctx.underFiles,
                    "count": ctx.count, "leading": ctx.leading,
                    "headingPool": ctx.headingPool})
    return out


def _poolTotals(sha: str):
    """按**那一笔自己的** numstat 逐池求和（新文件也在这里，不靠估）。

    键由 `_POOL_ALIASES` 的值域生成——词表加一个别名不必改这里；加错才会被
    `testDeclaredPoolAliasesBothWaysReconcile` 当场点名。
    """
    totals = {key: (0, 0) for key in {*_POOL_ALIASES.values(), "全部"}}
    for line in _git("show", "--numstat", "--format=", sha).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        adds, dels, rel = parts
        if adds == "-" or dels == "-":          # 二进制：不参与行级复算
            continue
        a, d = int(adds), int(dels)
        key = "生产池" if rel.startswith("neurova/") else "测试/基建池"
        totals[key] = (totals[key][0] + a, totals[key][1] + d)
        totals["全部"] = (totals["全部"][0] + a, totals["全部"][1] + d)
    return totals


def _claimsRawSpan(body: str, claim: dict) -> slice:
    """按解析出来的那一格，反查它在正文里的**原始区间**（数字连写的写法一个字节不动）。

    用途只有一处：`testRealBodyWithOneWrongDigitIsCaught` 要把真实那一段改坏，
    而"改坏"必须落在原文的同一段上——用 `+{adds}/−{dels}` 重拼只在正文纯 ASCII、
    无 `**`、半角斜杠时才对得上，而这三点在本仓的正文里都不成立。
    """
    for m in CLAIM_RE.finditer(body or ""):
        if (m.group("label") == claim["label"] and int(m.group("adds")) == claim["adds"]
                and int(m.group("dels")) == claim["dels"]):
            return slice(m.start(), m.end())
    raise AssertionError(f"正文里找不到这一段声明：{claim!r}")


def _asideSpans(body: str) -> list:
    """正文里括号夹注（`（…）` / `(…)`）的区间。"""
    return [(m.start(), m.end()) for m in _ASIDE_RE.finditer(body or "")]


def _somebodyElsesSpans(body: str) -> list:
    """正文里**不属于本笔**的那几段区间：成对引号内、反引号内、括号夹注内。

    三种形状同一件事——那是"引用/说明"的位置，不是声明本笔行数的位置。
    取法只此一处，免得同一条词汇散在"判豁免"与"筛靶子"两处。
    """
    return _quotedSpans(body or "") + _backtickSpans(body or "") + _asideSpans(body or "")


def _backtickSpans(body: str) -> list:
    """正文里成对反引号圈起来的那几段（行内代码）的区间。

    与 `_quotedSpans` 同一条纪律、同一类形状：反引号里的数字是**引文**，不是本笔的账。
    实测那一遭（`10020069`）：它写「那条豁免挡的是 `e87ce9b9` 正文里写错的「生产池 +26/−5」」，
    复述的是**别人的**声明，却被按本笔复算成"本笔声称 +26/−5"。
    按提交号或关键词豁免都不对——下一个人写同样的话照样红；故只按形状给。
    """
    spans, start = [], 0
    while True:
        i = body.find("`", start)
        if i < 0:
            break
        j = body.find("`", i + 1)
        if j < 0:
            break
        spans.append((i, j + 1))
        start = j + 1
    return spans


def _quotedSpans(body: str) -> list:
    """正文里成对引号圈起来的那几段（`『』` `“”` `「」` `\"\"` `‘’`）的区间。

    为什么需要：本仓的提交正文会**引用别人写过的话**（复述上一笔的错误声明、贴工单原文）。
    那几段里的数字不属于本笔，按本笔复算就是拿别人的账判自己的账。实测两次：
    `68eb3bdc` 复述 `58d9d5aa` 的错误声明、`58d9d5aa` 复述 `e87ce9b9` 的原始声明，
    两次都被主格点名成"本笔写错"。豁免按**形状**给（成对引号内），不按提交号或关键词给。

    `「」` 是第三种实测形态：`10020069` 复述上一条豁免的错写法时就用的这一对，
    而它此前不在表里——同一条纪律只认了两种引号，等于把"复述"读成了"本笔声称"。
    """
    spans = []
    for left, right in (("『", "』"), ("“", "”"), ("「", "」"), ("\"", "\""), ("‘", "’")):
        start = 0
        while True:
            i = body.find(left, start)
            if i < 0:
                break
            j = body.find(right, i + len(left))
            if j < 0:
                break
            spans.append((i, j + len(right)))
            start = j + len(right)
    return spans


def _resolvePool(claim: dict, totals: dict):
    """一枚声明该拿哪一池去复算。**声明语义优先于字面块标记**：

    主机上真出现过的两种错写法，靠记号（`**`）区分不了——`生产池 **+57/−56`（`**` 只包数字）
    和 `本格 **+21/−0**（清单…）：4 处 1 行，池内实为…`（`**` 包住整句、`本格` 只是修饰语）。
    故顺序是：池名声明（`生产池`/`测试池`/测试/基建池/`基建池`）→ 数量后缀（`+2/-0` 后面跟
    `个文件`/`格`，量的是笔数不是行数，不参与复算）→ 行内后缀词（`测试`/`生产`/`基建`）→
    列表项或「净 LOC」标题下的分池说明（`本格` 在这里指**本池**，不是整笔）→ 才回落到
    `本笔`/`全笔`/`本格` 的整笔口径（真·单文件笔：行里没有后缀词、也没有分池上下文）。
    """
    if claim["label"] not in _TOTAL_MARKERS:
        return _POOL_ALIASES[claim["label"]], None
    if claim["suffix"] in _POOL_ALIASES:
        return _POOL_ALIASES[claim["suffix"]], None
    if claim["count"]:
        return None, (f"这不量行数——`+{claim['adds']}/−{claim['dels']}` 后面跟的是"
                      f"条数/格数（`{claim['count']}`），要声明行数请写池名，别拿数量词顶池名")
    if claim["suffix"]:
        return _SUFFIX_ALIASES[claim["suffix"]], None
    if claim["listed"] or claim["underFiles"]:
        # `本格` 在分池说明里指**本池**：标题行第一处带池名的声明就是这份小计的池
        return claim["headingPool"] or "全部", None
    return "全部", None


def _mismatches(sha: str, body: str) -> list:
    declared = _claims(body)
    if not declared:
        return []
    totals = _poolTotals(sha)
    bad = []
    quoted = _somebodyElsesSpans(body)
    for c in declared:
        # 引用块（成对引号内）里的数字是**别人的账**：复述上一笔的错误声明、贴工单原文，
        # 都不属于本笔。豁免按形状给，不按提交号或关键词给。
        span = _claimsRawSpan(body or "", c)
        if any(lo <= span.start and span.stop <= hi for lo, hi in quoted):
            continue
        # 同一句话里被两处取数口重复抓到时（前缀池名格 + 数字处格），以带前缀池名的那条为准
        if c["leading"] and any(o is not c and o["adds"] == c["adds"] and o["dels"] == c["dels"]
                                and o["leading"] for o in declared if o is not c):
            continue
        pool, why = _resolvePool(c, totals)
        if pool is None:
            bad.append(f"{c['label']} 声明 +{c['adds']}/−{c['dels']}：{why}")
            continue
        a, d = totals[pool]
        if (c["adds"], c["dels"]) != (a, d):
            bad.append(f"{c['label']} 声明 +{c['adds']}/−{c['dels']}，那一笔的 numstat 实为 +{a}/−{d}")
        if c["net"] is not None and c["net"] != a - d:
            bad.append(f"{c['label']} 声明净 {c['net']:+d}，实为 {a - d:+d}")
    return bad


class TestEveryClaimedNumberIsReal:
    def testUnpushedCommitsClaimsAllReconcile(self):
        """主格：未推送窗口里每一笔，正文写过的净 LOC 数字都必须等于它自己的 numstat。"""
        commits = _unpushedRange()
        report = []
        for sha in commits:
            body = _git("log", "-1", "--format=%B", sha)
            bad = _mismatches(sha, body)
            if bad:
                title = body.splitlines()[0][:58] if body else sha[:8]
                report.append(f"{sha[:8]} {title}\n    " + "\n    ".join(bad))
        # 预存红基线：入库且**不许改写正文**的那几笔显式豁免，让本格对"这一轮新写的正文"
        # 仍然会红。两条纪律都要：判据不该因为历史写错就整体失效（那正是"降级断言"），
        # 也不该因为一条不许动的历史就长期全红（那会被读成"本档坏了"）。
        # 基线表本身要被反证（`testBaselineEntriesStillPointAtRealMismatches`）——
        # 一条已经修好的豁免留在表里，就是下次真错的隐身衣。
        report = [r for r in report if r.split("\n")[0][:8] not in _KNOWN_BAD_COMMITS]
        assert not report, (
            f"{len(commits)} 笔未推送提交里有 {len(report)} 笔的正文数字与自己的 numstat 不符"
            "（这一类错在本会话已第五遭，见本档头部）——趁还没推送改正文，不是改基线：\n  "
            + "\n  ".join(report))

    def testGuardIsNotVacuousWhenWindowIsEmpty(self, tmp_path):
        """窗口为空不许等于判据成立：造一枚**坏号**（commit-tree，不碰分支）让它当场红。

        这里刻意不复用工作树里的真提交：CI 上推送完成后区间就是空集，若只有主格，
        这档会在 CI 里恒绿——"没声明"与"声明都对"是两件事，后者才是要钉的东西。
        """
        tree = _git("rev-parse", "HEAD^{tree}").strip()
        bad = _commitTree(tree, "fix(x): 标题\n\n净 LOC：生产池 **+1/−0 ＝ 净 +1**（故意写错的探针）\n")

        mismatches = _mismatches(bad, _git("log", "-1", "--format=%B", bad))

        assert mismatches, "正文里的 +1/−0 与真实 numstat 不符，判据却说没问题——口径失效"
        assert any("生产池" in m for m in mismatches), mismatches

    def testBaselineEntriesStillPointAtRealMismatches(self):
        """豁免表不是免死金牌：表里每一条，今天仍然必须真的与自己的 numstat 不符。

        留在表里但已经修好的条目，就是下一次真错的隐身衣——它会静默吞掉同一笔的正文错误。
        本格按"这一条现在还该被豁免吗"复算，答否即红，要求在表里删掉它。

        **已推出去的豁免不按 `origin/main..HEAD` 判**：推送完那条区间就空了，而豁免指向的
        正是推送走的那一笔——按区间判会把"豁免仍然成立"读成"指向不存在的提交"。
        故这里只问"这一笔在仓里还在不在、它还对不对"，与它是否仍在未推送窗口无关。
        （CI 实读：本格第一版在区间判定上红过一次，红形正是那句"找不到"。）
        """
        stale = []
        for short, declared in _KNOWN_BAD_COMMITS.items():
            probe = subprocess.run(["git", "cat-file", "-e", f"{short}^{{commit}}"],
                                   cwd=str(REPO), capture_output=True, timeout=_GIT_WALL_S)
            if probe.returncode != 0:
                stale.append(f"{short} 在仓里找不到（豁免指向一枚不存在的提交）")
                continue
            body = _git("log", "-1", "--format=%B", short)
            if not _mismatches(short, body):
                stale.append(f"{short} 今天已经对得上 numstat，不再需要豁免（当时声明：{declared}）")
        assert not stale, "这些豁免该删了：" + "；".join(stale)

    def testCorrectClaimPassesTheSameChecker(self, tmp_path):
        """反向配对格：同一棵树造一枚**数字正确**的号，同一套复算必须放行。

        只有上一格会红是不够的——那可能只是"任何声明都判错"。两格必须反向。
        """
        tree = _git("rev-parse", "HEAD^{tree}").strip()
        a, d = _poolTotals(tree)["全部"]
        good = _commitTree(tree, f"fix(x): 标题\n\n净 LOC：本格 **+{a}/−{d} ＝ 净 {a - d:+d}**\n")

        assert _mismatches(good, _git("log", "-1", "--format=%B", good)) == [], (
            f"+{a}/−{d} 就是实量值却被判错——复算本身坏了，先修解析再谈判据")

    def testDeclaredPoolAliasesBothWaysReconcile(self):
        """词表同源：正文允许的**每一个**池名，复算都要能放行实量值、并点名改坏的值。

        本批实测的坏形态：正文写「基建池 +3/−0 ＝ 净 +3」时门禁抛 `KeyError: '基建池'`——
        正则把这个名字当合法声明收下，求和表里却没有对应的键。判据崩在自家词表上时，
        报错看着像"我的数字写错了"，真因是同一份词汇被写成三处：一张无人引用的谓词表、
        一条手写的正则备选、一个只备了三个键的求和表。
        """
        tree = _git("rev-parse", "HEAD^{tree}").strip()
        totals = _poolTotals(tree)
        for alias, poolKey in _POOL_ALIASES.items():
            a, d = totals[poolKey]
            good = _commitTree(tree, f"chore(x): 标题\n\n净 LOC：{alias} **+{a}/−{d} ＝ 净 {a - d:+d}**\n")
            assert _mismatches(good, _git("log", "-1", "--format=%B", good)) == [], (
                f"{alias}（→ {poolKey}）声明了实量值却被判错——这个名字的复算路径不通")

            bad = _commitTree(tree, f"chore(x): 标题\n\n净 LOC：{alias} **+{a + 1}/−{d} ＝ 净 {a - d + 1:+d}**\n")
            mismatches = _mismatches(bad, _git("log", "-1", "--format=%B", bad))
            assert any(alias in m for m in mismatches), (
                f"{alias} 的数字被 +1 改坏却没被点名：{mismatches}")

    def testParserActuallyMatchesTheHouseForms(self):
        """取数口径对账：正文里那几种写法必须**都被解析到**，漏一种＝那一类声明永不复算。

        这一格是把"正则匹配不到"本身做成读数：匹配不上的声明静默跳过，主格就会在
        "0 条声明"上判绿（211 的"没产出汇总行不等于全绿"同族）。
        """
        samples = {
            "净 LOC：生产池 **+57/−56 ＝ 净 +1**——其余略": [("生产池", 57, 56, 1)],
            "测试/基建池 +435/−11（新判据档 260": [("测试/基建池", 435, 11, None)],
            "净 LOC：本格 **+20/−0**（现读": [("本格", 20, 0, None)],
            "生产池 **+55/−57 ＝ 净 -2**": [("生产池", 55, 57, -2)],
            # 别名与"全部"标记各跑一遍：备选表现在由词表生成，名字掉了就不会红只会静默漏判
            "测试池 **+6/−5 ＝ 净 +1**": [("测试池", 6, 5, 1)],
            "本笔 **+3/−0**": [("本笔", 3, 0, None)],
            "全笔 **+1/−2 ＝ 净 -1**": [("全笔", 1, 2, -1)],
            # 主机上真出现过的四种写法，前三种**老正则整条漏判**（漏判＝那一类声明永不复算）
            "净 LOC（测试不计入）：生产池 +26/-5 ＝ **净 +21**，全落在": [("生产池", 26, 5, None)],
            "钉死的字面量换成按锁内版本取，生产池 +21/-0（这一个文件就是生产池全部改动）": [
                ("生产池", 21, 0, None)],
            "净 LOC：生产池 +13/-5 ＝ 净 +8，其余十一处各自带池名的声明同形": [("生产池", 13, 5, 8)],
            # 分池说明里的小计：`本格` 在标题行之后读作"本池"，不是整笔
            "净 LOC：生产池 +0/-0，测试/基建池 +65/-5\n本格 **+21/-0**（清单…）：4 处 1 行":
                [("生产池", 0, 0, None), ("测试/基建池", 65, 5, None), ("本格", 21, 0, None)],
        }
        for body, expected in samples.items():
            got = [(c["label"], c["adds"], c["dels"], c["net"]) for c in _claims(body)]
            assert got == [tuple(e) for e in expected], (
                f"解析结果与写法不符：{body[:34]!r} → {got}，期望 {expected}")

    def testSilentFormsResolveToThePoolTheirContextNames(self):
        """静默漏判的四种写法，复算必须落到**行文自己指的那个池**——落错池比漏判更坏。

        `+26/-5` 后面跟着「＝ 净 +21，全落在」：这是**生产池**的声明，老正则连数字都抓不到；
        `+65/-5（含测试档）` 是测试池；标题行下的列表项 `本格` 是分池说明里的**本池**小计。
        同一套判据在三种上下文里要给出三种池，靠的就是行内后缀词与标题上下文，不是猜。
        """
        totals = {"生产池": (10, 1), "测试/基建池": (65, 5), "全部": (75, 6)}
        cases = {
            "净 LOC（测试不计入）：生产池 +26/-5 ＝ **净 +21**，全落在": "生产池",
            "钉死的字面量换成按锁内版本取，生产池 +21/-0（这一个文件就是全部改动）": "生产池",
            # 分池说明里的小计：语法上是 `本格`，语义上是本标题段第一池
            "净 LOC：生产池 +0/-0，测试/基建池 +65/-5\n本格 **+21/-0**（清单…）：4 处 1 行": "生产池",
        }
        # 一行两个池名、各带自己的小计，逐条按本行算——两种池并存，靠的就是这段后缀边界
        twoPools = "净 LOC：生产池 +0/-0 ＝ 净 0，测试/基建池 +65/-5"
        got = [_resolvePool(c, totals)[0] for c in _claims(twoPools)]
        assert got == ["生产池", "测试/基建池"], (
            f"{twoPools[:28]!r} 逐条落到了 {got}——判据在替作者改写了他的话")

        for body, expected in cases.items():
            first = _claims(body)[0]                     # 每一条只断**它自己那条**声明的落池
            got = {_resolvePool(first, totals)[0]}
            assert got == {expected}, (
                f"{body[:28]!r} 的第一条声明落到了 {got}，行文指的是 {expected}"
                "——判据在替作者改写了他的话")

    def testAsideDigitsAreSomebodyElsesAccountAndOnlyThatSpan(self):
        """括号夹注里的数字不是本笔的账；**夹注之外**的仍然是。

        夹注放的是"这一块按哪一池算"的口径说明——复述旧声明时那串数字就落在这里。
        实测形态（`10020069` 一类补正笔）：一边声明本笔 +0/-0，一边在夹注里点出旧声明的数字，
        主格按本笔复算就说"本笔写错了"。

        反向半边同样要钉：夹注只豁免它圈住的那一段。夹注写在声明**之后**时
        （`生产池 +26/-5（说明）`），声明本身仍在正文里，照旧报红——否则下一次真写错、
        顺手在旁边加个括号就能安静通过。
        """
        totals = {"生产池": (0, 0), "测试/基建池": (0, 0), "全部": (0, 0)}
        forms = {
            "（生产池 +26/-5）": True,        # 整枚声明在夹注内
            "生产池 +26/-5（说明）": False,   # 夹注在声明之后，声明本身仍是本笔的账
        }
        for fragment, exempt in forms.items():
            body = f"净 LOC：{fragment}，其余略"
            span = _claimsRawSpan(body, _claims(body)[0])
            hit = any(lo <= span.start and span.stop <= hi for lo, hi in _somebodyElsesSpans(body))
            assert hit is exempt, (
                f"{fragment!r} 的豁免判定为 {hit}，应为 {exempt}"
                "——夹注只圈它自己那一段，不能顺手把整行豁免掉")
            assert (_mismatches("HEAD", body) == []) is exempt, (
                f"{fragment!r} 在复算面上的结论与豁免判定不一致")

    def testRealBodyWithOneWrongDigitIsCaught(self):
        """把本会话真犯过的那次错**照原样**塞回真实正文，判据必须点名并且给出实量值。

        造出来的样本能红，不代表我那种写法能红——这条拿未推送窗口里真实带「生产池」声明的那笔，
        只把它的数字改坏（形状、池名、括号一个字不动），要求复算把错抓出来、并把真值写在报错里。
        """
        # 目标只认**本笔自书**的那一处：引用块（成对引号内）不参与，否则测的就是别人的句子。
        # 窗口里同时可能有别的批预存的错声明（实测有一笔），先后无关紧要——真值跟着目标走。
        target = None
        for sha in _unpushedRange():
            body = _git("log", "-1", "--format=%B", sha)
            quoted = _somebodyElsesSpans(body)
            own = [c for c in _claims(body) if c["label"] == "生产池"
                   and _claimsRawSpan(body, c) is not None
                   and not any(lo <= _claimsRawSpan(body, c).start
                               and _claimsRawSpan(body, c).stop <= hi for lo, hi in quoted)]
            if own:
                a, d = _poolTotals(sha)["生产池"]
                target = (sha, body, own[0], a, d)
                break
        if target is None:
            pytest.skip("未推送窗口里没有自书的「生产池」声明（推送后此格无对象，主格与 5/6 格仍在工作）")

        sha, body, real, a, d = target
        # 取**第一处**且数量非零的那条声明：补正笔常把错数与真值写在同一段里
        # （`声明 +26/−5，实为 +0/−0`），挑到真值那条就等于没换，本格会静默空转。
        # 换数字落在**原文区间**上、不按解析值重拼：真写法里池名与数字之间常夹着 `**`，
        # 而那些字节在重拼串里根本不存在（实测本档因此红过一轮，真因却是本格没替换到）。
        # 只换数字那一段、池名保留——整段换成裸的 `+1/−0` 会让正则失去池名，声明整个消失，
        # 那样的红是"没声明"，不是"声明错了"，测不到本格要测的东西。
        nonzero = [c for c in _claims(body) if c["label"] == "生产池" and (c["adds"], c["dels"]) != (0, 0)]
        if not nonzero:
            pytest.skip("这一笔的生产池声明全是 +0/−0（补正笔），换数字无从下手"
                        "——主格与其余 5 格仍在工作")
        real = next((c for c in nonzero if (c["adds"], c["dels"]) != (a, d)), nonzero[0])
        raw = body[_claimsRawSpan(body, real)]
        doctored = body
        for slash in ("−", "-"):
            digits = f"+{real['adds']}/{slash}{real['dels']}"
            if digits in raw:
                doctored = body.replace(raw, raw.replace(digits, "+1/−0"), 1)
                break
        assert doctored != body, (
            f"正文里的 +{real['adds']}/−{real['dels']}（两种斜杠都试过）没被替换掉——这条格在空转")

        # 靶子必须先证**真落在复算面上**：本档按形状给豁免（成对引号内是别人的账），
        # 而窗口里真正书的那处如果恰好被人引过（`10020069` 就写了「…写错的「生产池 +26/−5」」），
        # 拿它改出来的坏串天然属于"引用块"，不点名是对的。这不是放宽，是把"没测到"与
        # "判据抓不住"分开：换下一处自书且未被引用的声明；窗口里全是引用块才 skip 并点名。
        doctored, own = body, None
        for candidate in nonzero:
            raw = body[_claimsRawSpan(body, candidate)]
            for slash in ("−", "-"):
                digits = f"+{candidate['adds']}/{slash}{candidate['dels']}"
                if digits not in raw:
                    continue
                changed = body.replace(raw, raw.replace(digits, "+1/−0"), 1)
                quoteIn = any(lo <= _claimsRawSpan(changed, c).start
                              and _claimsRawSpan(changed, c).stop <= hi
                              for c in _claims(changed) if (c["adds"], c["dels"]) == (1, 0)
                              for lo, hi in _quotedSpans(changed))
                if not quoteIn:
                    doctored, own = changed, candidate
                    break
            if own:
                break
        if own is None:
            pytest.skip("窗口里自书的「生产池」声明全在引用块内——没有可改坏的自书目标"
                        "（主格与其余 5 格仍在工作）")
        assert doctored != body, (
            f"正文里的 +{own['adds']}/−{own['dels']}（两种斜杠都试过）没被替换掉——这条格在空转")

        bad = _mismatches(sha, doctored)
        assert bad and any("+1/−0" in m and f"+{a}/−{d}" in m for m in bad), (
            f"把真实声明改成 +1/−0 仍没被点名（实得 {bad}）——判据抓不住我实际写错的那种句子")

    def testGitReadFailureIsLoudInsteadOfAnEmptyString(self):
        """读仓失败不许变成空串：`_git` 现在的契约是"要么给 stdout，要么响亮失败"。

        平台的读数（构建 `cnb-i46-1k5upb7f5#003`）里，反证格把"读不到"报成了
        `…在区间里找不到（豁免指向一枚不存在的提交）`——读的人据此会去删一条仍该在的豁免。
        真因在取数口：只取 stdout、退出码与 stderr 一并丢掉，"读不到"与"读出来是空的"
        在返回值上完全一样。这里用一条必然失败的命令把那条契约钉住，并带正检
        （成功命令必须照常给 stdout，否则"响亮失败"可能只是把所有读取都弄红了）。
        """
        with pytest.raises(AssertionError) as caught:
            _git("rev-parse", "--verify", "refs/heads/__no_such_branch__")
        assert "退出码" in str(caught.value), (
            f"读不到时必须点名退出码，不能只留一句像「你的数据错了」的话：{caught.value}")

        assert _git("rev-parse", "HEAD").strip(), "成功命令读不出 stdout——上面那个红不算数"
        assert _git("rev-parse", "--verify", "-q", "refs/heads/__no_such_branch__", check=False) == "", (
            "`check=False` 的探查语义变了：它应当把失败读成空串交给调用方自己判")

    def testBinaryAndEmptyCommitsAreNotSilentlyMiscounted(self):
        """numstat 里 `-\t-` 是二进制：不许把它当 0 参与复算，也不许让它把池求和算崩。"""
        body = "净 LOC：本格 **+1/−1 ＝ 净 0**"
        assert _claims(body), "写法解析不到，后面这条没有对象"

        totals = _poolTotals(_git("rev-parse", "HEAD").strip())
        assert isinstance(totals["全部"], tuple) and len(totals["全部"]) == 2


def _commitTree(tree: str, message: str) -> str:
    """只造对象、不动任何分支/工作树的临时提交（新判据自证用，先例见 `a31851e2`）。"""
    proc = subprocess.run(["git", "commit-tree", tree, "-p", _git("rev-parse", "HEAD").strip()],
                          cwd=str(REPO), input=message, capture_output=True, text=True,
                          encoding="utf-8", env=_commitEnv(), timeout=_GIT_WALL_S)
    assert proc.returncode == 0, proc.stderr[-300:]
    return proc.stdout.strip()


def _commitEnv() -> dict:
    """继承进程环境再叠身份变量——空的 `PATH` 会让 `git` 本身解析不到（本机实测过这种写法脆）。"""
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "guard", "GIT_AUTHOR_EMAIL": "guard@local",
                "GIT_COMMITTER_NAME": "guard", "GIT_COMMITTER_EMAIL": "guard@local",
                "PYTHONIOENCODING": "utf-8"})
    return env


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
