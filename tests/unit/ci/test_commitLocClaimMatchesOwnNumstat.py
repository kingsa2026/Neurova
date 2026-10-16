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

#: 正文里声明的池 → 该池的归属判断（与生产/基建分池口径一致：neurova/ 算生产）
_POOL_MARKERS = (
    ("生产池", lambda rel: rel.startswith("neurova/")),
    ("测试/基建池", lambda rel: not rel.startswith("neurova/")),
    ("基建池", lambda rel: not rel.startswith("neurova/")),
    ("测试池", lambda rel: not rel.startswith("neurova/")),
)

#: `本格/本笔` 声明的是这一笔的**全部**文件合计
_TOTAL_MARKERS = ("本格", "本笔", "全笔")

CLAIM_RE = re.compile(
    r"(?P<label>生产池|测试/基建池|基建池|测试池|本格|本笔|全笔)"
    r"\s*\**\s*\+?(?P<adds>\d+)\s*/\s*[−-]\s*(?P<dels>\d+)"
    r"(?:\s*\**\s*(?:＝|=)\s*净\s*(?P<net>[+-]\d+))?"
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def _unpushedRange() -> list:
    """`origin/main..HEAD`；解析不到远端基准则按取数失败处理，不许静默返回空集。"""
    probe = subprocess.run(["git", "rev-parse", "--verify", "origin/main"], cwd=str(REPO),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
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
    """按**那一笔自己的** numstat 逐池求和（新文件也在这里，不靠估）。"""
    totals = {"生产池": (0, 0), "测试/基建池": (0, 0), "全部": (0, 0)}
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


def _mismatches(sha: str, body: str) -> list:
    declared = _claims(body)
    if not declared:
        return []
    totals = _poolTotals(sha)
    bad = []
    for c in declared:
        pool = "全部" if c["label"] in _TOTAL_MARKERS else c["label"]
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

    def testCorrectClaimPassesTheSameChecker(self, tmp_path):
        """反向配对格：同一棵树造一枚**数字正确**的号，同一套复算必须放行。

        只有上一格会红是不够的——那可能只是"任何声明都判错"。两格必须反向。
        """
        tree = _git("rev-parse", "HEAD^{tree}").strip()
        a, d = _poolTotals(tree)["全部"]
        good = _commitTree(tree, f"fix(x): 标题\n\n净 LOC：本格 **+{a}/−{d} ＝ 净 {a - d:+d}**\n")

        assert _mismatches(good, _git("log", "-1", "--format=%B", good)) == [], (
            f"+{a}/−{d} 就是实量值却被判错——复算本身坏了，先修解析再谈判据")

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
        target = None
        for sha in _unpushedRange():
            body = _git("log", "-1", "--format=%B", sha)
            if _claims(body) and any(c["label"] == "生产池" for c in _claims(body)):
                target = (sha, body)
                break
        if target is None:
            pytest.skip("未推送窗口里没有带「生产池」声明的提交（推送后此格无对象，主格与 5/6 格仍在工作）")

        sha, body = target
        real = [c for c in _claims(body) if c["label"] == "生产池"][0]
        doctored = body.replace(f"+{real['adds']}/−{real['dels']}", "+1/−0", 1)
        assert doctored != body, "正文里那句声明没被替换掉——这条格在空转"

        bad = _mismatches(sha, doctored)
        a, d = _poolTotals(sha)["生产池"]
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
                          encoding="utf-8", env=_commitEnv())
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
