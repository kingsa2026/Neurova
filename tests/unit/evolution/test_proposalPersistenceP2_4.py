"""两臂提案持久化收口单元测试（P2-4，计划书 §1.7-11 / §6 P2 批 P2-4）。

红灯判据（现状）：RSI 臂 ``_save_proposal_to_disk`` 直接 ``write_text``——
进程在写中途崩溃会留下半写文件，读者 ``json.loads`` 失败即整条提案"消失"；
台账无界增长；两臂"列出提案"各走各的读口。

绿灯判据：
- 原子写：tmp + os.replace，落盘后无 .tmp 残留；崩溃残留的 .tmp 半成品
  不被重启加载误读；
- 有界：台账超过 50 条时最旧者归档进 archive/（审计留痕，不删除）；
- 统一读口：``proposal_lifecycle.collectProposals`` 一次读出两臂（行带 arm
  标记、状态按规范值过滤），文本臂 / RSI 臂互不串。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.rollback_manager import RSIRollbackManager
from neurova.evolution.rsi.self_improvement_proposer import SelfImprovementProposer


def _makeProposer(proposalsDir: Path, agentId: str = "kai") -> SelfImprovementProposer:
    from neurova.skill_system import SkillRegistry
    from neurova.skills.skill_service import SkillService

    return SelfImprovementProposer(
        agent_id=agentId,
        proposals_dir=proposalsDir,
        deployment_controller=RSIDeploymentController(initial_phase=4),
        rollback_manager=RSIRollbackManager(),
        skill_service=SkillService(agentId, skills_dir=str(proposalsDir.parent / "skills")),
        skill_registry=SkillRegistry(),
    )


class TestAtomicSave:
    def test_saveLeavesNoTmpResidue(self, tmp_path):
        ledger = tmp_path / "proposals"
        proposer = _makeProposer(ledger)
        proposal = proposer.propose_skill_manifest("s1", "name: s1")

        proposer.submit_proposal(proposal)

        assert list(ledger.glob("*.tmp")) == [], "落盘后不得残留 .tmp 半成品"
        saved = ledger / f"{proposal.proposal_id}.json"
        assert saved.exists()
        assert json.loads(saved.read_text(encoding="utf-8"))["proposal_id"] == (
            proposal.proposal_id
        )

    def test_midWriteCrashLeavesPreviousStateIntact(self, tmp_path):
        """原子写判据：写中途崩溃（先写坏再抛错）不得破坏已落盘的上一份。

        直接 write_text 的旧实现会把坏字节写进正式文件（读者 json.loads 失败
        即丢提案）；tmp + os.replace 的实现只污染 .tmp，正式文件始终完整。
        """
        from unittest.mock import patch

        ledger = tmp_path / "proposals"
        proposer = _makeProposer(ledger)
        proposal = proposer.propose_skill_manifest("s1", "name: s1")
        proposer.submit_proposal(proposal)
        saved = ledger / f"{proposal.proposal_id}.json"
        before = saved.read_text(encoding="utf-8")
        realWriteText = Path.write_text

        def crashingWriteText(pathSelf, data, *args, **kwargs):
            if pathSelf.parent == ledger:  # 台账目录内的任何落盘都先写坏再崩
                realWriteText(pathSelf, "CORRUPTED-HALF-WRITE", *args, **kwargs)
                raise OSError("模拟写中途崩溃")
            return realWriteText(pathSelf, data, *args, **kwargs)

        with patch.object(Path, "write_text", crashingWriteText):
            with pytest.raises(OSError):
                proposer._save_proposal_to_disk(proposal)

        assert saved.read_text(encoding="utf-8") == before, (
            "写中途崩溃破坏了已落盘提案（非原子写）"
        )
        assert json.loads(saved.read_text(encoding="utf-8"))["proposal_id"] == (
            proposal.proposal_id
        )

    def test_staleTmpFromCrashIsNotLoaded(self, tmp_path):
        """崩溃残留的 .tmp 半成品：重启加载必须无视（glob 只认 *.json）。"""
        ledger = tmp_path / "proposals"
        proposer = _makeProposer(ledger)
        proposal = proposer.propose_skill_manifest("s1", "name: s1")
        proposer.submit_proposal(proposal)
        (ledger / "prop-deadbeef.json.tmp").write_text(
            '{"proposal_id": "prop-deadbeef"', encoding="utf-8"
        )

        reloaded = _makeProposer(ledger)

        ids = {p.proposal_id for p in reloaded.list_all_proposals()}
        assert proposal.proposal_id in ids
        assert "prop-deadbeef" not in ids, "半写文件被当成合法提案读回"

    def test_textArmAlsoAtomic(self, tmp_path):
        """文本臂既有原子写不回归（对照面）。"""
        from neurova.evolution.eval.service import (
            EvolutionProposal,
            SkillEvolutionService,
        )

        evoDir = tmp_path / "text-evo"
        service = SkillEvolutionService("t-agent", base_dir=evoDir)
        service._append_proposal(
            EvolutionProposal(
                proposal_id="prop-text-1",
                agent_id="t-agent",
                skill_id="skill-a",
                artifact_type="skill",
                baseline_text="before",
                improved_text="after",
            )
        )
        assert list(evoDir.glob("*.tmp")) == []
        items = json.loads((evoDir / "proposals.json").read_text(encoding="utf-8"))
        assert items[0]["proposal_id"] == "prop-text-1"


class TestBoundedLedger:
    def test_ledgerBoundedAtFiftyWithOldestArchived(self, tmp_path):
        ledger = tmp_path / "proposals"
        proposer = _makeProposer(ledger)
        ids: list[str] = []
        for index in range(55):
            proposal = proposer.propose_skill_manifest(f"s{index}", f"name: s{index}")
            proposer.submit_proposal(proposal)
            ids.append(proposal.proposal_id)
            time.sleep(0.05)  # Windows 时钟粒度 ~15ms：拉开 mtime，保证"最旧"判定确定

        live = {p.stem for p in ledger.glob("*.json")}
        archived = {p.stem for p in (ledger / "archive").glob("*.json")}
        assert len(live) == 50, f"台账未收口到 50：{len(live)}"
        assert len(archived) == 5
        # 最旧的 5 条被归档、最新的留在台账（审计留痕，不删除）
        assert set(ids[:5]) == archived
        assert set(ids[5:]) == live

    def test_archiveDirectoryNotMatchedByLedgerGlob(self, tmp_path):
        ledger = tmp_path / "proposals"
        proposer = _makeProposer(ledger)
        for index in range(52):
            proposal = proposer.propose_skill_manifest(f"s{index}", f"name: s{index}")
            proposer.submit_proposal(proposal)
            time.sleep(0.05)
        # archive/ 是子目录，reload 的 glob("*.json") 不得把它当台账读：
        # 重启后缓存只含台账现存的 50 条（归档的 2 条不在加载面）
        reloaded = _makeProposer(ledger)
        assert len(reloaded.list_all_proposals()) == 50


class TestCrossArmListing:
    def test_bothArmsReadableThroughSingleEntry(self, tmp_path):
        from neurova.evolution.eval.service import (
            EvolutionProposal,
            SkillEvolutionService,
        )
        from neurova.evolution.proposal_lifecycle import collectProposals

        textService = SkillEvolutionService("t-agent", base_dir=tmp_path / "text-evo")
        textProposal = EvolutionProposal(
            proposal_id="prop-text-1",
            agent_id="t-agent",
            skill_id="skill-a",
            artifact_type="skill",
            baseline_text="before",
            improved_text="after",
        )
        textService._append_proposal(textProposal)

        ledger = tmp_path / "proposals"
        proposer = _makeProposer(ledger)
        rsiProposal = proposer.propose_skill_manifest("s1", "name: s1")
        proposer.submit_proposal(rsiProposal)

        rows = collectProposals(textService=textService, rsiProposer=proposer)

        assert {row["arm"] for row in rows} == {"text_evolution", "rsi"}
        ids = {row["proposal_id"] for row in rows}
        assert textProposal.proposal_id in ids
        assert rsiProposal.proposal_id in ids
        # 状态过滤按规范值双臂统一
        pending = collectProposals(
            textService=textService, rsiProposer=proposer, status="pending"
        )
        assert {row["arm"] for row in pending} == {"text_evolution", "rsi"}
        # RSI 臂拒绝一条后，rejected 过滤只命中它
        proposer.reject_proposal(rsiProposal.proposal_id, reason="不需要")
        rejected = collectProposals(
            textService=textService, rsiProposer=proposer, status="rejected"
        )
        assert [row["proposal_id"] for row in rejected] == [rsiProposal.proposal_id]

    def test_emptySourcesYieldEmptyList(self):
        from neurova.evolution.proposal_lifecycle import collectProposals

        assert collectProposals() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
