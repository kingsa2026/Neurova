# -*- coding: utf-8 -*-
"""S4 结果候选制 单元测试。

覆盖（方案 §S4）：
- CandidateReport 形态与状态域（submitted/accepted/rejected/reviseRequired）；
- member 结果回传先落候选（submitted），**不直接定案**；
- mergeCandidate CAS：候选.baseRevision 与当前 integrationReport.revision 一致才
  合入，不一致判冲突；
- 同 artifactKey 同 baseRevision 的两个候选 → 都保留、标记 conflict，绝不静默
  覆盖；
- 验收驳回 → 候选走 reviseRequired（既有回炉链不变）；
- swarm 回流点：spawn 成功后 run.report 来自合入的候选；integrationReport 增
  candidates/conflicts/revision 字段；合入冲突升级（escalation）且 run 如实判失败。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.candidate_merge import (
    CANDIDATE_ACCEPTED,
    CANDIDATE_REVISE_REQUIRED,
    CANDIDATE_SUBMITTED,
    CandidateConflictError,
    CandidateMergeBoard,
    CandidateMergeError,
    CandidateReport,
    artifactKeysFromOwnership,
)
from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager


def make_agent(reply="成员最终报告"):
    agent = MagicMock()
    agent.config.name = "子Agent"
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


def make_gate_agent(chat_replies, judge_verdicts):
    """chat_replies: 首跑与回炉的正文列表；judge_verdicts: 判定 JSON 列表（逐次）。"""
    agent = MagicMock()
    agent.config.name = "子Agent"
    agent.chat = AsyncMock(side_effect=[{"text": r} for r in chat_replies])
    verdicts = list(judge_verdicts)

    async def fake_verify(messages, *args, **kwargs):
        payload = verdicts.pop(0) if verdicts else {"achieved": True, "confidence": 1.0, "missing": []}
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=fake_verify)
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


@pytest.fixture
def gateOn():
    with patch("neurova.agent.acceptance_gate.get_advanced_settings",
               return_value={"swarm_acceptance_enabled": True}):
        yield


class TestCandidateReport:
    def test_status_vocabulary(self):
        from neurova.agent.candidate_merge import CANDIDATE_STATUSES

        assert CANDIDATE_STATUSES == frozenset(
            {"submitted", "accepted", "rejected", "reviseRequired"})

    def test_new_candidate_defaults_to_submitted(self):
        c = CandidateReport(candidateId="cand_1", runId="run_1",
                            content="产出正文", artifactKeys=["doc-a"], baseRevision=0)
        assert c.status == CANDIDATE_SUBMITTED
        assert c.toDict()["status"] == "submitted"
        assert c.toDict()["candidate_id"] == "cand_1"
        assert c.toDict()["run_id"] == "run_1"


class TestArtifactKeys:
    def test_parse_ownership_text(self):
        assert artifactKeysFromOwnership("doc-a, doc-b；记忆:auth") == [
            "doc-a", "doc-b", "记忆:auth"]

    def test_parse_empty_or_blank(self):
        assert artifactKeysFromOwnership("") == []
        assert artifactKeysFromOwnership("   ") == []

    def test_single_key_without_separator(self):
        assert artifactKeysFromOwnership("docs/api.md") == ["docs/api.md"]


class TestCandidateMergeBoard:
    def test_submit_lands_submitted_not_finalized(self):
        board = CandidateMergeBoard()
        c = board.submitCandidate("run-1", "成员产出", ["doc-a"])
        assert c.status == CANDIDATE_SUBMITTED
        assert c.baseRevision == 0
        assert board.revision == 0, "提交不等于合入：集成版本未推进"
        assert board.candidate(c.candidateId) is c

    def test_merge_accepts_and_bumps_revision(self):
        board = CandidateMergeBoard()
        c = board.submitCandidate("run-1", "成员产出", ["doc-a"])
        out = board.mergeCandidate(c.candidateId)
        assert out["merged"] is True
        assert board.revision == 1
        assert board.candidate(c.candidateId).status == CANDIDATE_ACCEPTED

    def test_merge_cas_conflict_when_revision_moved(self):
        board = CandidateMergeBoard()
        first = board.submitCandidate("run-1", "先合入的结果", ["doc-a"])
        board.mergeCandidate(first.candidateId)  # revision 0→1
        late = board.submitCandidate("run-2", "基于旧基准的结果", ["doc-b"])
        assert late.baseRevision == 1
        stale = board.submitCandidate("run-3", "基于更旧基准的结果", ["doc-c"], baseRevision=0)
        with pytest.raises(CandidateConflictError):
            board.mergeCandidate(stale.candidateId)  # CAS：0 ≠ 当前 1
        # 冲突保留：双方都还在，绝不静默覆盖
        assert board.candidate(first.candidateId).status == CANDIDATE_ACCEPTED
        assert board.candidate(stale.candidateId).status == CANDIDATE_SUBMITTED
        assert board.candidate(stale.candidateId).note

    def test_same_key_same_base_revision_flags_both_and_retains(self):
        board = CandidateMergeBoard()
        a = board.submitCandidate("run-a", "A 的结果", ["doc-a"])
        b = board.submitCandidate("run-b", "B 的结果", ["doc-a"])
        # 同 key 同基准：双方都标记冲突，都保留
        assert a.conflictWith == [b.candidateId]
        assert b.conflictWith == [a.candidateId]
        assert len(board.conflicts()) == 2
        assert board.candidate(a.candidateId) is a
        assert board.candidate(b.candidateId) is b
        # 先合入者按 CAS 正常通过；后合入者 CAS 失败判冲突
        board.mergeCandidate(a.candidateId)
        with pytest.raises(CandidateConflictError):
            board.mergeCandidate(b.candidateId)
        assert board.candidate(b.candidateId).status == CANDIDATE_SUBMITTED

    def test_different_key_same_base_revision_no_conflict(self):
        board = CandidateMergeBoard()
        a = board.submitCandidate("run-a", "A 的结果", ["doc-a"])
        b = board.submitCandidate("run-b", "B 的结果", ["doc-b"])
        assert a.conflictWith == []
        assert b.conflictWith == []
        assert board.conflicts() == []

    def test_gate_rejection_marks_revise_required(self):
        board = CandidateMergeBoard()
        c = board.submitCandidate("run-1", "不达标产出", ["doc-a"])
        board.markReviseRequired(c.candidateId, "acceptance_failed（缺登录跳转）")
        stored = board.candidate(c.candidateId)
        assert stored.status == CANDIDATE_REVISE_REQUIRED
        assert "登录" in stored.note

    def test_resubmit_after_revise_returns_to_submitted(self):
        board = CandidateMergeBoard()
        c = board.submitCandidate("run-1", "不达标产出", ["doc-a"])
        board.markReviseRequired(c.candidateId, "验收打回")
        board.mergeCandidate(board.submitCandidate("run-0", "别的结果", ["doc-x"]).candidateId)
        again = board.resubmitCandidate(c.candidateId, "补齐后的产出")
        assert again.status == CANDIDATE_SUBMITTED
        assert again.content == "补齐后的产出"
        assert again.baseRevision == board.revision, "重提以当前集成版本为新基准"

    def test_merge_unknown_candidate_raises(self):
        board = CandidateMergeBoard()
        with pytest.raises(CandidateMergeError):
            board.mergeCandidate("cand_never")

    def test_double_merge_rejected(self):
        board = CandidateMergeBoard()
        c = board.submitCandidate("run-1", "产出", [])
        board.mergeCandidate(c.candidateId)
        with pytest.raises(CandidateMergeError):
            board.mergeCandidate(c.candidateId)

    def test_snapshot_for_integration_report(self):
        board = CandidateMergeBoard()
        a = board.submitCandidate("run-a", "A", ["doc-a"])
        b = board.submitCandidate("run-b", "B", ["doc-a"])
        snap = board.snapshot()
        assert snap["revision"] == 0
        assert len(snap["candidates"]) == 2
        assert len(snap["conflicts"]) == 2
        assert {x["candidate_id"] for x in snap["conflicts"]} == {
            a.candidateId, b.candidateId}


class TestSwarmCandidateFlow:
    @pytest.mark.asyncio
    async def test_spawn_result_lands_as_candidate_then_accepted(self, swarm):
        agent = make_agent(reply="成员最终报告")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(
                task="子任务", agent_id="researcher",
                task_unit={"goal": "g", "artifactOwnership": "doc-a, doc-b"})
        assert result["status"] == "completed"
        cands = swarm._candidates.candidatesForRun(result["subagent_id"])
        assert len(cands) == 1, "结果必须先落候选（不直接定案）"
        c = cands[0]
        assert c.status == CANDIDATE_ACCEPTED
        assert c.content == "成员最终报告"
        assert c.artifactKeys == ["doc-a", "doc-b"]
        assert c.baseRevision == 0
        assert swarm._candidates.revision == 1
        # 定案内容来自合入的候选，不是绕开候选直传
        assert result["report"] == c.content
        rep = swarm.integrationReport()
        assert rep["revision"] == 1
        assert any(x["candidate_id"] == c.candidateId for x in rep["candidates"])
        assert rep["conflicts"] == []

    @pytest.mark.asyncio
    async def test_gate_rejection_marks_candidate_revise_required(self, swarm, gateOn):
        agent = make_gate_agent(
            ["不完整产出", "回炉后仍不完整"],
            [{"achieved": False, "confidence": 0.8, "missing": ["缺登录跳转"]},
             {"achieved": False, "confidence": 0.8, "missing": ["仍缺登录跳转"]}])
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(
                task="重构登录页", agent_id="researcher",
                task_unit={"goal": "g", "acceptanceCriteria": ["登录成功跳转"]})
        assert result["status"] == "failed"
        cands = swarm._candidates.candidatesForRun(result["subagent_id"])
        assert len(cands) == 1, "被驳回的结果也先落了候选"
        assert cands[0].status == CANDIDATE_REVISE_REQUIRED
        assert cands[0].status != CANDIDATE_ACCEPTED

    @pytest.mark.asyncio
    async def test_merge_conflict_escalates_and_run_fails(self, swarm):
        from neurova.agent.candidate_merge import CandidateConflictError

        agent = make_agent(reply="同产物产出")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(
                task="同产物任务", agent_id="researcher",
                task_unit={"goal": "g", "artifactOwnership": "doc-a"})
        assert result["status"] == "completed"
        sid = result["subagent_id"]
        # 直接注入合入冲突：模拟另一成员先合入推高版本后的 CAS 失败
        def conflict(cid):
            raise CandidateConflictError(
                "CAS 冲突：候选基准 0 ≠ 当前集成版本 1", candidateId=cid)
        swarm._candidates.mergeCandidate = conflict  # type: ignore[assignment]
        fresh = swarm._candidates.submitCandidate(sid, "重试产出", ["doc-a"])
        outcome = await swarm._mergeCandidateForRun(swarm._runs[sid], fresh)
        assert outcome["merged"] is False
        assert outcome["cause"] == "merge_conflict"
        run = swarm._runs[sid]
        assert run.escalation is not None
        assert run.escalation["reason"] == "merge_conflict"
        # 候选保留（绝不静默覆盖）
        assert swarm._candidates.candidate(fresh.candidateId).status == CANDIDATE_SUBMITTED

    @pytest.mark.asyncio
    async def test_integration_report_carries_candidates_and_conflicts(self, swarm):
        agent = make_agent(reply="产出")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            await swarm.spawn(task="子任务A", agent_id="researcher",
                              task_unit={"goal": "g", "artifactOwnership": "doc-a"})
        rep = swarm.integrationReport()
        assert "candidates" in rep
        assert "conflicts" in rep
        assert "revision" in rep
        assert rep["revision"] >= 1
        assert len(rep["candidates"]) == 1


class TestApprovalChannelFailClosed:
    """修复计划 M4：审批通道故障时不得放行合入（原实现 fail-open 返回
    approval_channel_unavailable=True，L2「强制人工」语义被基础设施抖动豁免）。
    修后：通道故障 → merge_blocked，候选保留 submitted 待人工处置。"""

    @pytest.mark.asyncio
    async def test_channel_failure_blocks_merge_and_keeps_candidate(self, swarm, monkeypatch):
        agent = make_agent(reply="需人审的产出")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(
                task="人审任务", agent_id="researcher",
                task_unit={"goal": "g", "artifactOwnership": "doc-l2"})
        assert result["status"] == "completed"
        sid = result["subagent_id"]

        monkeypatch.setenv("NEUROVA_SWARM_MERGE_APPROVAL_LEVEL", "L2")

        async def brokenChannel(*a, **k):
            raise RuntimeError("审批基础设施不可用（模拟通道故障）")

        monkeypatch.setattr(
            "neurova.agent.approval_chain.requestRunApproval", brokenChannel)

        cand = swarm._candidates.submitCandidate(sid, "需人审的产出", ["doc-l2"])
        outcome = await swarm._mergeCandidateForRun(swarm._runs[sid], cand)

        assert outcome["merged"] is False, "审批通道故障不得放行合入（L2 必须人工）"
        assert outcome["cause"] == "merge_blocked"
        assert swarm._candidates.candidate(cand.candidateId).status == CANDIDATE_SUBMITTED, \
            "候选必须保留在板上待人工处置（候选板即等待态载体）"
