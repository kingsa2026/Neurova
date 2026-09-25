# -*- coding: utf-8 -*-
"""NPC 分支归档清理守卫（AGENTS.md §0 的常驻判据）。

## 本守卫钉住什么

AGENTS.md §0 把「NPC 分支合并/废弃后**立即删除该远端分支**」写成硬动作，理由是
构建配置**随分支走**：分支改过 `.cnb.yml`，该分支每次产生构建都会重新加载它自己
那一份，于是过期配置会永久留在那里复现同一场失败——**与任务内容、与主线代码都无关**。

此前没有任何机器判据会发现这条纪律被违反：悬空扫描只认文档路径、CI 门禁只跑代码
与配置，远端分支列表不在任何一处的覆盖面内。本守卫把它变成可复核的读数。

## 为什么不在守卫里连远端

判据若依赖网络，CI 会因远端不可达而红——那是「判据随环境漂红」，不是契约。
故分工明确：

- **取数**（碰网络的那一次）落在 `scripts/ci/npc_branch_cleanup.py` 的 `main()`；
- **判定逻辑**（`parseRemoteHeads` / `classifyBranches` / `staleBranches`）是纯函数，
  本守卫喂合成输入做正向与反向控制；
- **仓内事实**与判定口径的一致性，由 `docs/06-bugfix/npc分支归档台账.md` 承接
  （见下一条 class），人不核对时台账就是唯一可读的结论面。
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

cleanup = pytest.importorskip("scripts.ci.npc_branch_cleanup")

LEDGER = PROJECT_ROOT / "docs" / "06-bugfix" / "npc分支归档台账.md"


def _criterion_section(text: str) -> str:
    """从台账正文里切出「判定口径」那一节（到下一个同级标题为止）。

    只在这一节里断言口径，是为了让判据有**区分力**：散在处置记录里的同名词
    不该让口径节的断言变绿（见 `test_ledger_declares_the_rule_and_the_probe`）。
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and "判定口径" in line:
            start = i + 1
            break
    assert start is not None, "台账缺「判定口径」节（## 级标题）"
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def _criterion_items(section: str) -> str:
    """从「判定口径」节里只取**编号条目**（`1. ` / `2. ` …）的正文。

    **为什么必须只取条目**：整节里"第二父"这个词在解释段与反例段也会出现，
    对整节搜关键词没有区分力 —— 本轮实测：把编号条目 1 整条替换回旧的
    「分支名以 `auto/` 开头」，整节仍含"第二父"，断言照样绿。口径的**判据**
    就是这两个条目，故断言只钉在这两条上。
    """
    items = [ln for ln in section.splitlines() if re.match(r"^\d+\.\s", ln.strip())]
    assert items, "「判定口径」节没有编号条目（口径没有写成可复核的条件）"
    return "\n".join(items)


class TestBranchVerdictLogic:
    """判定口径：两个 git 事实同时成立才算已归档（见 `classifyBranches`）。

    1. 分支头是主线某个 merge commit 的第二父（＝某个已合并请求的源分支头）；
    2. 该头是 `main` 的祖先（＝提交已在主线里，删掉不丢成果）。

    成员资格由**事实**给出，不由分支名字给出 —— 见
    `TestCriterionIsMergeFactNotBranchName` 里本轮实测的漏判。
    """

    def test_merged_source_branch_is_stale(self):
        """已合并请求的源分支且头已在主线 ⇒ stale（待删）。"""
        heads = {"auto/done-xyz": "abc123"}
        verdicts = cleanup.classifyBranches(
            heads, {"abc123"}, ancestorOfMain={"auto/done-xyz": True}
        )
        assert cleanup.staleBranches(verdicts) == ["auto/done-xyz"]

    def test_unmerged_source_branch_is_kept(self):
        """源分支头已是主线祖先、但头不在合并记录里 ⇒ keep。"""
        heads = {"auto/inflight-xyz": "abc123"}
        verdicts = cleanup.classifyBranches(
            heads, {"deadbeef"}, ancestorOfMain={"auto/inflight-xyz": False}
        )
        assert cleanup.staleBranches(verdicts) == []

    @pytest.mark.parametrize("branch", ["main", "docs/context-chain-reverify-0923", "feature/x"])
    def test_branch_outside_the_merge_record_is_out_of_scope(self, branch):
        """头不在主线合并记录里的分支不由本判据裁决。

        反向控制：这条也是判据的区分力证明——把所有已合并分支都判 stale 的实现
        会在这里红（`main` 自己就是"已合并"）。
        """
        heads = {branch: "abc123"}
        verdicts = cleanup.classifyBranches(
            heads, {"deadbeef"}, ancestorOfMain={branch: True}
        )
        assert cleanup.staleBranches(verdicts) == []
        assert "不是任何已合并请求的源分支头" in str(verdicts[0]["reason"])

    def test_non_candidate_never_triggers_ancestor_lookup(self, monkeypatch):
        """非归档候选不得触发祖先判定——否则判据在"不存在的东西"上依赖环境。

        实测回归（本守卫首版发现）：判定对 `main` 自己也跑一次 `merge-base`，
        在只拿到远端头的检出里 `origin/main` 可能还没建，于是判据在环境前置条件上
        报错。修法是判据只对「头落在主线合并记录里」的分支说话（那才是它裁决的对象）。
        """
        def _boom(*args, **kwargs):  # pragma: no cover - 被调用即失败
            raise AssertionError("非归档候选触发了祖先判定（判据越界到环境前置条件）")

        monkeypatch.setattr(cleanup, "isMergedIntoMain", _boom)
        verdicts = cleanup.classifyBranches({"main": "abc", "docs/x": "def"}, set())
        assert cleanup.staleBranches(verdicts) == []


class TestCriterionIsMergeFactNotBranchName:
    """成员资格由「经 PR 合并进主线」这一**事实**给出，不由分支名字给出。

    ## 根因（本轮实测，2026-09-25）

    现口径把「是不是 NPC 工作分支」等同于「名字是否以 `auto/` 开头」。而**名字不是事实**：
    平台按 PR 的 `head.ref` 决定分支名，NPC 会话既可以建 `auto/*`，也可以建
    `fix/*` / `fix-*`。于是同一件事（一个已合并的归档分支还留在远端）在一种命名下被
    判 `stale`，在另一种命名下被判 `keep`。

    实测三条读数（`git ls-remote --heads origin` × `git merge-base --is-ancestor`）：

    | 远端分支 | 是 `origin/main` 的祖先 | PR 的 head | 现判据 | 应当 |
    |---------|----------------------|-----------|--------|------|
    | `fix-caliber-generated` | 是（`bdda0ba1`） | #217（作者是 NPC） | `keep` | `stale` |
    | `auto/code-exec-sandbox-555c` | 是（`b1d2057e`） | #212（作者是 NPC） | `stale` | `stale` |

    两行是同一形态，只差名字 —— 判据的区分力挂在了名字上，而不是挂在事实上。

    ## 口径：两个 git 事实同时成立

    1. 该分支头**出现在主线某个 merge commit 的第二父位**（＝它正是某个 PR 的源分支头，
       即「经 PR 合并进主线」这件事本身）；
    2. 该分支头**是 `origin/main` 的祖先**（＝它的提交已在主线里，删掉不丢成果）。

    第 1 条取代原先的 `auto/` 前缀判定，同时天然排除 `main` 自身：仓库默认分支的头
    不会是任何 merge commit 的第二父（它是那些 merge commit 的**后代**）。
    第 2 条不放宽 —— 头不是祖先（合并后又推了新提交）仍是 `keep`，删掉就是丢成果。
    """

    def testMergedSourceBranchIsStaleRegardlessOfName(self):
        """已合并进主线的 PR 源分支 ⇒ stale，与它叫什么名字无关。"""
        heads = {"fix-caliber-generated": "bdda0ba1"}
        verdicts = cleanup.classifyBranches(
            heads,
            ancestorOfMain={"fix-caliber-generated": True},
            mergedSourceTips={"bdda0ba1"},
        )
        assert cleanup.staleBranches(verdicts) == ["fix-caliber-generated"], (
            "已合并的 PR 源分支只因不叫 auto/* 就被放行 —— 判据挂在了名字上，"
            "而名字不是事实（实测：fix-caliber-generated 是 #217 的 head，"
            "已是 main 的祖先，现判据给 keep）"
        )

    def testAutoPrefixedMergedBranchStaysStale(self):
        """反向：`auto/*` 且已合并 ⇒ 仍须 stale（新口径不得把老覆盖丢掉）。"""
        heads = {"auto/code-exec-sandbox-555c": "b1d2057e"}
        verdicts = cleanup.classifyBranches(
            heads,
            ancestorOfMain={"auto/code-exec-sandbox-555c": True},
            mergedSourceTips={"b1d2057e"},
        )
        assert cleanup.staleBranches(verdicts) == ["auto/code-exec-sandbox-555c"]

    def testDefaultBranchIsNeverStale(self):
        """仓库默认分支永不被判 stale：它的头不是任何 merge commit 的第二父。

        反向控制：只按「是 main 的祖先」判定（丢掉第二父那条事实）的实现会在这里红 ——
        `main` 自己就是 main 的祖先。
        """
        heads = {"main": "ad1ad254"}
        verdicts = cleanup.classifyBranches(
            heads,
            ancestorOfMain={"main": True},
            mergedSourceTips={"deadbeef"},  # 默认分支的头不在其中
        )
        assert cleanup.staleBranches(verdicts) == []

    def testUnmergedSourceBranchIsKept(self):
        """在途的 PR 源分支（尚未合并）⇒ keep，删掉就是丢成果。"""
        heads = {"auto/relay-not-a-gate-217": "0fbb5068"}
        verdicts = cleanup.classifyBranches(
            heads,
            ancestorOfMain={"auto/relay-not-a-gate-217": False},
            mergedSourceTips={"deadbeef"},
        )
        assert cleanup.staleBranches(verdicts) == []

    def testRealRepoMergeRecordYieldsNonAutoPrefixedSourceBranch(self):
        """语义红灯：直接对本仓**真实 git 历史**取数，钉住那次漏判的形态。

        本仓主线里存在这样一个合并提交 —— `0cc0719a`（`合并来自
        fix-caliber-generated 的合并请求 #217`），其第二父 `bdda0ba1` 就是
        `fix-caliber-generated` 的分支头。这是**已写进主线历史的事实**，
        不随该分支后来是否被删除而改变，所以这条用例只用本地 git 取数（不碰网络）。

        旧口径按名字前缀判定，对这一形态给 `keep`；`bdda0ba1` 落进合并记录
        却不带 `auto/` 前缀，正是它漏判的那一类。判据改为「读合并事实」后，
        同样的输入必须判 `stale`。
        """
        tips = cleanup.mergedSourceTips()
        assert "bdda0ba19933b07935adaf8f40bcbcd04201fd21" in tips, (
            "本地 git 历史里找不到 0cc0719a 的第二父 —— 取数口径与主线历史不符"
        )
        heads = {"fix-caliber-generated": "bdda0ba19933b07935adaf8f40bcbcd04201fd21"}
        verdicts = cleanup.classifyBranches(
            heads, tips, ancestorOfMain={"fix-caliber-generated": True}
        )
        assert cleanup.staleBranches(verdicts) == ["fix-caliber-generated"], (
            "实测漏判形态：fix-caliber-generated 是 #217 的分支头、已是 main 的祖先，"
            "却因名字不带 auto/ 前缀被名字前缀口径放行"
        )

    def testMergedSourceTipsReadMergeSecondParents(self, tmp_path, monkeypatch):
        """取数口径：`mergedSourceTips()` 只认 merge commit 的第二父位。

        合成一段 `git log --merges --format=%P` 输出：非 merge 行、单父行都不得混入。
        """
        captured = {}

        class _Done:
            returncode = 0
            stdout = (
                "ad1ad254\n"                                        # 非 merge（单父）→ 不收
                "aaaaaaaa 259b6ad1aaaa00000000000000000000000000\n"     # merge → 收第二父
                "bbbbbbbb 1ce8f2c0bbbb77777777777777777777777777\n"
            )
            stderr = ""

        def _run(cmd, **kwargs):
            captured["cmd"] = cmd
            return _Done()

        monkeypatch.setattr(cleanup.subprocess, "run", _run)
        tips = cleanup.mergedSourceTips()
        assert tips == {"259b6ad1aaaa00000000000000000000000000",
                        "1ce8f2c0bbbb77777777777777777777777777"}, tips
        assert "--merges" in captured["cmd"], "取数没有限定 merge commit"


class TestRemoteHeadParsing:
    """取数口径：只认 `refs/heads/`，tag 与其它引用不得混进判据。"""

    def test_only_heads_are_collected(self):
        raw = (
            "c35eafd7\trefs/heads/auto/a\n"
            "feedface\trefs/tags/v1.0.0\n"
            "7a807828\trefs/heads/main\n"
            "badc0de\trefs/pull/1/head\n"
        )
        assert cleanup.parseRemoteHeads(raw) == {"auto/a": "c35eafd7", "main": "7a807828"}

    def test_malformed_lines_are_skipped_not_guessed(self):
        """畸形行跳过，不猜——猜出来的分支名会变成一条假的"待删"读数。"""
        assert cleanup.parseRemoteHeads("\n\nno-tab-line\n") == {}


class TestLedgerIsReadableInRepo:
    """台账必须在仓内可读：判定口径与当前远端事实都要有落点。

    本类不连网络。它校验的是「取数与判定**有**可复核的结论面」——
    纪律写在 AGENTS.md 里、读数却只在某次会话的评论里，就是断点。
    """

    def test_ledger_exists(self):
        assert LEDGER.is_file(), (
            f"分支归档台账不存在：{LEDGER.relative_to(PROJECT_ROOT)}\n"
            "AGENTS.md §0 要求归档分支立即删除；无台账则该纪律在仓内不可复核。"
        )

    def test_ledger_records_dispositions_not_live_branch_state(self):
        """台账只登记**已发生的处置**，不登记**当前的远端分支状态**。

        根因（本轮实测）：台账 §3 有一张"保留的分支"表，逐行断言某分支"未合并进主线、
        在途工作"——那是**当下的远端事实**，而台账没有任何刷新机制。Issue #197 批收口后
        实测：该表 4 行里 **3 行已失效**（`auto/issue197-judgement-registration` /
        `auto/issue197-registration-guard-recover` / `auto/t11a-uncap-generations-90`
        对应 PR 已合入或已删，三支均不在远端），第 4 行 `auto/npc-glmcoder-59d9` 尚在。
        台账自己 §4 已写明"分支列表本身不入台账——每次 fetch 都在变，抄进文档就立刻过期"，
        但 §3 正是抄了一份：规则与行为不一致，且**无人复核**（本条判据之前不存在）。

        判据：台账里的**登记行**（表格行 / 列表项）每出现一条分支，就必须带一个
        **已完成的处置**标记（已删 / 已合入 / 已归档）。写"未合并进主线 / 在途工作"
        这类当下状态即红——要查当前在途分支，跑 `scripts/ci/npc_branch_cleanup.py`
        （唯一取数入口）。

        为什么只判登记行：判据要拦的形态是「一张"当前保留"的表/清单」，不是
        正文里叙述历史的散文（那段散文提到已失效的分支名，正是要说明它们为何被删）。
        把散文也算进来，只会训练人删掉解释、留下表格。
        """
        dispositions = ("已删", "已合入", "已归档")
        #: 只认**具体的分支全名**（`auto/` + 名字）。口径说明里的裸 `auto/` 是命名空间，
        #: 不是某条分支的登记行 —— 拿前缀本身匹配会把 §1 的判定口径也报成违规。
        branchNames = re.compile(re.escape(cleanup.NPC_BRANCH_PREFIX) + r"[A-Za-z0-9][\w.\-]*")
        offenders = []
        for lineno, line in enumerate(io.open(LEDGER, encoding="utf-8").read().splitlines(), 1):
            stripped = line.strip()
            if not (stripped.startswith("|") or stripped.startswith("- ")):
                continue
            if not branchNames.search(stripped):
                continue
            if not any(mark in stripped for mark in dispositions):
                offenders.append(f"第 {lineno} 行：{stripped[:110]}")
        assert not offenders, (
            "台账登记了分支的**当前状态**而非**已发生的处置**（这类行会随远端变化立刻过期，"
            "且台账没有刷新机制）：\n  " + "\n  ".join(offenders)
            + "\n修法：台账只写「已删 / 已合入 / 已归档」这类完成的动作；"
            "当前在途分支用 `python scripts/ci/npc_branch_cleanup.py` 现算，不抄进文档。"
        )

    def test_disposition_check_has_discriminating_power(self, tmp_path, monkeypatch):
        """反向锁：人造一份「当前保留」表 → 必须判红；处置表 → 必须判绿。

        没有这条，上面那条只是「当前这份文档恰好长这样」的快照。
        """
        stale = tmp_path / "stale.md"
        stale.write_text(
            "# 台账\n\n| 分支 | 状态 | 保留理由 |\n"
            "|------|------|----------|\n"
            "| `auto/inflight-x` | 未合并进主线 | 在途工作 |\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            sys.modules[__name__], "LEDGER", stale)
        with pytest.raises(AssertionError, match="auto/inflight-x"):
            sys.modules[__name__].TestLedgerIsReadableInRepo() \
                .test_ledger_records_dispositions_not_live_branch_state()

        good = tmp_path / "good.md"
        good.write_text(
            "# 台账\n\n| 分支 | 处置 |\n|------|------|\n"
            "| `auto/done-x` | 已删 |\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            sys.modules[__name__], "LEDGER", good)
        sys.modules[__name__].TestLedgerIsReadableInRepo() \
            .test_ledger_records_dispositions_not_live_branch_state()

    def test_ledger_declares_the_rule_and_the_probe(self):
        """台账须同时给出：纪律出处、复算入口、以及判定口径的两个事实。

        断言的是**判定口径本身**，不是分支命名空间 —— 命名空间已不再参与判定
        （见 `TestCriterionIsMergeFactNotBranchName`），拿它当"口径"会把
        已经退役的判据重新钉进文档。
        """
        text = io.open(LEDGER, encoding="utf-8").read()
        assert "AGENTS.md" in text, "台账没有指向纪律出处"
        assert "npc_branch_cleanup.py" in text, "台账没有给出复算入口"
        #: 判定口径必须在**「一、判定口径」那一节里**写明，不能散落在处置记录中 ——
        #: 全文搜"第二父"不够：处置表与修正说明里也会出现这个词，断言会在
        #: 口径节被改回旧措辞时照样绿（本轮实测：整节替换成旧的"名字以 auto/ 开头"
        #: 后仍 18 passed）。故先切出该节，再在节内断言两条事实。
        items = _criterion_items(_criterion_section(text))
        assert "第二父" in items, (
            "判定口径的编号条目没有写明「经合并请求并入主线」这条事实（第二父位）——"
            "成员资格若退回按分支名判定，同一形态的归档分支会被放行"
        )
        assert re.search(r"祖先|已合并进主线", items), (
            "判定口径的编号条目没有写明「已合并」的祖先条件"
        )
        assert "分支名以" not in items, (
            "判定口径的编号条目把成员资格写回了分支名 —— 名字是平台的产物、"
            "不是事实（实测：fix-caliber-generated 是 #217 的 head 却被名字前缀口径放行）"
        )
