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

#: 预存红：**已推送或已入库、正文按平台纪律不许改写**的那几笔（短号 → 当时写错的声明）。
#: 值只用于反证"这条豁免还该在"（`testBaselineEntriesStillPointAtRealMismatches`），
#: 不参与报告生成。
_KNOWN_BAD_COMMITS = {
    "e87ce9b9": "生产池 +26/-5 ＝ 净 +21",
}

#: 本档三枚 subprocess 落点（rev-parse / rev-list / commit-tree）都是仓库内 git 查询，
#: 毫秒级；20s 是给满载机器留的余量。取**低于全局 30s** 的这一形，是为了不去给整档抬父墙——
#: 子进程先到点时报的是诚实的 TimeoutExpired，而不是"整场跑测没了"（§6-402 批 K 口径）。
_GIT_WALL_S = 20

#: 长名排在前面，免得备选被短名截走（`测试/基建池` 必须先于 `基建池` 试）
CLAIM_RE = re.compile(
    r"(?P<label>" + "|".join(sorted({*_POOL_ALIASES, *_TOTAL_MARKERS}, key=len, reverse=True)) + r")"
    r"\s*\**\s*\+?(?P<adds>\d+)\s*/\s*[−-]\s*(?P<dels>\d+)"
    r"(?:\s*\**\s*(?:＝|=)\s*净\s*(?P<net>[+-]\d+))?"
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=_GIT_WALL_S).stdout


def _unpushedRange() -> list:
    """`origin/main..HEAD`；解析不到远端基准则按取数失败处理，不许静默返回空集。"""
    probe = subprocess.run(["git", "rev-parse", "--verify", "origin/main"], cwd=str(REPO),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=_GIT_WALL_S)
    if probe.returncode != 0:
        pytest.fail("origin/main 解析不到——区间取不到基线就等于「无声明」，本格不许据此判绿")
    return [c for c in _git("rev-list", "origin/main..HEAD").split() if c.strip()]


def _claims(body: str) -> list:
    out = []
    for m in CLAIM_RE.finditer(body or ""):
        out.append({"label": m.group("label"), "adds": int(m.group("adds")),
                    "dels": int(m.group("dels")),
                    "net": int(m.group("net")) if m.group("net") else None})
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


def _quotedSpans(body: str) -> list:
    """正文里成对引号圈起来的那几段（`『』` `“”` `\"\"` `‘’`）的区间。

    为什么需要：本仓的提交正文会**引用别人写过的话**（复述上一笔的错误声明、贴工单原文）。
    那几段里的数字不属于本笔，按本笔复算就是拿别人的账判自己的账。实测两次：
    `68eb3bdc` 复述 `58d9d5aa` 的错误声明、`58d9d5aa` 复述 `e87ce9b9` 的原始声明，
    两次都被主格点名成"本笔写错"。豁免按**形状**给（成对引号内），不按提交号或关键词给。
    """
    spans = []
    for left, right in (("『", "』"), ("“", "”"), ("\"", "\""), ("‘", "’")):
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


def _mismatches(sha: str, body: str) -> list:
    declared = _claims(body)
    if not declared:
        return []
    totals = _poolTotals(sha)
    bad = []
    quoted = _quotedSpans(body or "")
    for c in declared:
        span = _claimsRawSpan(body or "", c)
        if any(lo <= span.start and span.stop <= hi for lo, hi in quoted):
            continue
        pool = "全部" if c["label"] in _TOTAL_MARKERS else _POOL_ALIASES[c["label"]]
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
        """
        stale = []
        for short, declared in _KNOWN_BAD_COMMITS.items():
            body = _git("log", "-1", "--format=%B", short)
            if not body.strip():
                stale.append(f"{short} 在区间里找不到（豁免指向一枚不存在的提交）")
                continue
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
        }
        for body, expected in samples.items():
            got = [(c["label"], c["adds"], c["dels"], c["net"]) for c in _claims(body)]
            assert got == [tuple(e) for e in expected], (
                f"解析结果与写法不符：{body[:34]!r} → {got}，期望 {expected}")

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
            quoted = _quotedSpans(body)
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
        # 替换串按**原文那一段**取，不按解析值重拼：真实写法里的池名与数字之间常夹着
        # `**`（`生产池 **+26/-5**`），按 `+{adds}/−{dels}` 重拼会一个字节都匹配不上，
        # 于是这格在"替换失败"上判红——报的是"判据抓不住"，真因却是本格自己没替换到。
        # 2026-10-27 实读：48 笔未推送里恰有这样一个提交，本格因此红了整整一轮。
        raw = body[_claimsRawSpan(body, real)]
        # 改坏的是**数字那一段**，池名保留：整段换成裸的 `+1/−0` 会让正则失去池名，
        # 声明直接消失（实测 `生产池 +26/-5` 整段替换后 `_claims` 返回空）——那样的红是
        # "没声明"，不是"声明错了"，测不到本格要测的东西。
        # 数字那一段的两种斜杠写法都按原文换，池名与 `**` 一个字节都不动。
        doctored = body
        for digits in (f"+{real['adds']}/-{real['dels']}", f"+{real['adds']}/−{real['dels']}"):
            if digits in raw:
                doctored = body.replace(raw, raw.replace(digits, "+1/−0"), 1)
                break
        assert doctored != body, (
            f"正文里那句声明没被替换掉（取到的原文片段 {raw!r}）——这条格在空转")

        bad = _mismatches(sha, doctored)
        assert bad and any("+1/−0" in m and f"+{a}/−{d}" in m for m in bad), (
            f"把真实声明改成 +1/−0 仍没被点名（实得 {bad}）——判据抓不住我实际写错的那种句子")

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
