# -*- coding: utf-8 -*-
"""unpushed 窗口逐笔过修复教义提交判据——防 `--no-verify` 绕过本地钩子。

## 为什么要有它

commit-msg / pre-commit 是**客户端钩子**，git 设计上允许 `git commit --no-verify`
整段跳过——本地门对"存心绕"的人只是提示器。本档把**同一份判据**
（`scripts/githooks/commit_msg_check.py` 的 `check()`，单一事实源，不另写第二份）
搬到跑测面：绕过钩子的提交在本地跑测与 CI 的 unit-tests 腿照样红，而跑测门禁
不受 `--no-verify` 影响。

## 窗口口径（与 numstat 复算守卫同源）

只取 `origin/main..HEAD`（未推送窗口）：
① 这是唯一还能就地修正的窗口（推送后的号不许改写）；
② CI 上推送完成后窗口为空——本档不许因窗口空而误红，也不许静默空转：
  另配坏对象反证格（`git commit-tree` 造一笔"绕过钩子"的提交，不碰分支），
  判据必须当场点名缺什么。
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_HOOK_DIR = PROJECT_ROOT / "scripts" / "githooks"
if str(_HOOK_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOK_DIR))

commit_msg_check = importlib.import_module("commit_msg_check")

#: 本档每次 git 调用的墙钟（仓库内毫秒级查询，给满载机器留余量）。
_GIT_WALL_S = 20


def _git(*args: str, check: bool = True) -> str:
    """仓库内 git 查询取数口。失败按 check 语义处理，不静默吞错（教义第 2 条）。"""
    proc = subprocess.run(["git", *args], cwd=str(PROJECT_ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=_GIT_WALL_S)
    if check and proc.returncode != 0:
        raise AssertionError(
            f"`git {' '.join(args)}` 退出码 {proc.returncode}："
            f"{(proc.stderr or proc.stdout).strip()[-300:]}")
    return proc.stdout


def unpushedCommits() -> list:
    """`origin/main..HEAD` 的提交号。基线解析不到就 loud fail，不等于"无判据"。"""
    probe = subprocess.run(["git", "rev-parse", "--verify", "origin/main"],
                           cwd=str(PROJECT_ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=_GIT_WALL_S)
    if probe.returncode != 0:
        pytest.fail("origin/main 解析不到——窗口取不到基线就等于「无判据」，本档不许据此判绿")
    return [sha for sha in _git("rev-list", "origin/main..HEAD").split() if sha.strip()]


def scanCommit(sha: str) -> list:
    """单笔提交过提交门：正文 + 该笔 numstat 的生产池净增，喂给**同一把**判据。"""
    message = _git("log", "-1", "--format=%B", sha)
    numstat = _git("show", sha, "--numstat", "--format=").splitlines()
    net = commit_msg_check.productionNetFromNumstat(numstat)
    return commit_msg_check.check(message, productionNet=net)


def scanRange(shas: list) -> dict:
    return {sha: scanCommit(sha) for sha in shas}


#: 判据文件在仓内的单点路径——它出现在哪笔的树里，规则就从哪笔起生效。
DOCTRINE_FILE = "scripts/githooks/commit_msg_check.py"


def treeHasDoctrine(sha: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{sha}:{DOCTRINE_FILE}"],
                          cwd=str(PROJECT_ROOT), capture_output=True,
                          timeout=_GIT_WALL_S).returncode == 0


def enforceableCommits(shas: list) -> list:
    """规则生效口径：**法不溯及既往，但生效后不许绕**。

    - 基线（origin/main）已带判据文件 ⇒ 规则全面生效：窗口**全部**受检
      （含删掉判据文件的笔——它的祖先基线带着规则，删不掉义务）；
    - 基线还没带（判据刚落地、尚未推送的过渡期）⇒ 只受检树里带判据文件的笔：
      钩子诞生前的存量笔不追溯（判据不存在时无法要求作者按它写正文，
      硬拉进来只会造出一串无法处置的常驻红——numstat 复算守卫的同款教训）。
    """
    if not shas:
        return []
    baseline = "origin/main"
    if treeHasDoctrine(baseline):
        return list(shas)
    return [sha for sha in shas if treeHasDoctrine(sha)]


class TestUnpushedWindow:
    def testEveryUnpushedCommitCarriesDoctrineEvidence(self):
        """规则生效后的未推送提交，每一笔都要过提交门——被 --no-verify 绕过的笔在这里现形。"""
        bad = {sha: violations
               for sha, violations in scanRange(enforceableCommits(unpushedCommits())).items()
               if violations}
        assert not bad, (
            "未推送窗口里有提交没过修复教义（AGENTS.md §1）——像是绕过了本地钩子：\n"
            + "\n".join(f"  {sha[:10]}: {v}" for sha, vs in bad.items() for v in vs))

    def testEmptyWindowPassesWithoutNoise(self):
        """CI 上推送完成后窗口为空：放行，但不许靠'永远当窗口是空的'蒙过下面反证格。"""
        assert scanRange(enforceableCommits([])) == {}

    def testPreDoctrineCommitsAreNotRetroJudged(self):
        """追溯边界：过渡期里，钩子诞生前的存量笔不进受检集（树里没有判据文件的笔）。"""
        shas = unpushedCommits()
        if treeHasDoctrine("origin/main"):
            pytest.skip("基线已带判据文件，全面生效期无追溯边界可验")
        enforced = enforceableCommits(shas)
        assert all(treeHasDoctrine(sha) for sha in enforced), (
            "受检集混入了判据诞生前的存量笔——那会造出无法处置的常驻红")
        assert any(not treeHasDoctrine(sha) for sha in shas), (
            "窗口里全是生效后提交，本格退化为快照（当前窗口应有存量笔做对照）")


class TestBypassIsCaught:
    """反空转：合成一笔"绕过钩子"的提交（commit-tree，不碰分支），判据必须当场抓。"""

    def testNoVerifyStyleCommitIsNamed(self):
        bad = _git("commit-tree", _git("rev-parse", "HEAD^{tree}").strip(),
                   "-m", "fix(x): 绕过本地钩子的坏提交（无红绿证据）").strip()
        violations = scanCommit(bad)
        assert any("红灯" in v for v in violations), (
            f"绕过钩子的 fix 提交没被抓——守卫空转：{violations}")

    def testExemptShapesStillPass(self):
        mergeish = _git("commit-tree", _git("rev-parse", "HEAD^{tree}").strip(),
                        "-m", "Merge branch 'anything'").strip()
        assert scanCommit(mergeish) == [], "Merge 形态被误伤"
