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


class TestBranchVerdictLogic:
    """判定口径：`auto/` 命名空间 + 「是 main 的祖先」两个条件同时成立才算已归档。"""

    def test_merged_npc_branch_is_stale(self):
        """已合并进 main 的 auto/* 分支 ⇒ stale（待删）。"""
        heads = {"auto/done-xyz": "abc123"}
        verdicts = cleanup.classifyBranches(
            heads, ancestorOfMain={"auto/done-xyz": True}
        )
        assert cleanup.staleBranches(verdicts) == ["auto/done-xyz"]

    def test_unmerged_npc_branch_is_kept(self):
        """未合并的 auto/* 分支 ⇒ keep（可能还有在途工作，删掉就是丢成果）。"""
        heads = {"auto/inflight-xyz": "abc123"}
        verdicts = cleanup.classifyBranches(
            heads, ancestorOfMain={"auto/inflight-xyz": False}
        )
        assert cleanup.staleBranches(verdicts) == []

    @pytest.mark.parametrize("branch", ["main", "docs/context-chain-reverify-0923", "feature/x"])
    def test_non_npc_namespace_is_out_of_scope(self, branch):
        """非 `auto/` 命名空间的分支不由本判据裁决（长期分支由人管理）。

        反向控制：这条也是判据的区分力证明——把所有已合并分支都判 stale 的实现
        会在这里红（`main` 自己就是"已合并"）。
        """
        heads = {branch: "abc123"}
        verdicts = cleanup.classifyBranches(
            heads, ancestorOfMain={branch: True}
        )
        assert cleanup.staleBranches(verdicts) == []
        assert "非 NPC 自动分支命名空间" in str(verdicts[0]["reason"])

    def test_non_npc_namespace_never_triggers_ancestor_lookup(self, monkeypatch):
        """非 `auto/` 分支不得触发祖先判定——否则判据在"不存在的东西"上依赖环境。

        实测回归（本守卫首版发现）：判定对 `main` 自己也跑一次 `merge-base`，
        在只拿到远端头的检出里 `origin/main` 可能还没建，于是判据在环境前置条件上
        报错。修法是判据只对 `auto/*` 说话（那才是它裁决的对象）。
        """
        def _boom(*args, **kwargs):  # pragma: no cover - 被调用即失败
            raise AssertionError("非 NPC 分支触发了祖先判定（判据越界到环境前置条件）")

        monkeypatch.setattr(cleanup, "isMergedIntoMain", _boom)
        verdicts = cleanup.classifyBranches({"main": "abc", "docs/x": "def"})
        assert cleanup.staleBranches(verdicts) == []


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

    def test_ledger_declares_the_rule_and_the_probe(self):
        """台账须同时给出：纪律出处、复算入口、以及判定口径的两个条件。"""
        text = io.open(LEDGER, encoding="utf-8").read()
        assert "AGENTS.md" in text, "台账没有指向纪律出处"
        assert "npc_branch_cleanup.py" in text, "台账没有给出复算入口"
        assert cleanup.NPC_BRANCH_PREFIX in text, "台账没有写明裁决的命名空间"
        assert re.search(r"祖先|已合并进主线", text), "台账没有写明「已合并」的判定口径"
