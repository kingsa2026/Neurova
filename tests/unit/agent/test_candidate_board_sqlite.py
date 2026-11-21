# -*- coding: utf-8 -*-
"""M7（拍板乙）：候选板 SQLite 单源——跨实例 CAS、重启持久（含正文）、
swarm 装配接线（NEUROVA_SWARM_CANDIDATE_DB）。房间 pending 登记表 SQLite 形态
同批验证（NEUROVA_SWARM_ROOM_PENDING_DB）。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_candidate_sqlite_0123456789")

import pytest

from neurova.agent.candidate_merge import (
    CANDIDATE_ACCEPTED,
    CANDIDATE_SUBMITTED,
    CandidateConflictError,
    CandidateMergeBoard,
    CandidateMergeError,
)


class TestCandidateBoardSqlite:
    def test_cas_across_instances_and_restart(self, tmp_path):
        db = str(tmp_path / "board.db")
        b1 = CandidateMergeBoard(db_path=db)
        c1 = b1.submitCandidate("run1", "产出A", ["doc-a"])
        assert c1.baseRevision == 0
        # 另一实例（模拟另一进程）同 key 同基准提交 → 双方标冲突、都保留
        b2 = CandidateMergeBoard(db_path=db)
        c2 = b2.submitCandidate("run2", "产出B", ["doc-a"])
        c1After = b1.candidate(c1.candidateId)
        assert c1After.conflictWith == [c2.candidateId], "先提交方的冲突标记由后提交方写库"
        assert c2.conflictWith == [c1.candidateId]
        # b1 合入 c1 → revision 1；b2 对 c2（base 0）CAS 失败 → 冲突保留
        assert b1.mergeCandidate(c1.candidateId)["merged"] is True
        with pytest.raises(CandidateConflictError):
            b2.mergeCandidate(c2.candidateId)
        assert b2.candidate(c2.candidateId).status == CANDIDATE_SUBMITTED
        # 重启（新实例）后候选与版本仍在，且正文可查（投影不再缺 content）
        b3 = CandidateMergeBoard(db_path=db)
        assert b3.revision == 1
        accepted = b3.candidate(c1.candidateId)
        assert accepted.status == CANDIDATE_ACCEPTED
        assert accepted.content == "产出A"
        assert b3.candidate(c2.candidateId).status == CANDIDATE_SUBMITTED

    def test_status_transitions_persist(self, tmp_path):
        db = str(tmp_path / "board2.db")
        b1 = CandidateMergeBoard(db_path=db)
        cand = b1.submitCandidate("run1", "初稿", ["k1"])
        b1.markReviseRequired(cand.candidateId, "验收不达标")
        b2 = CandidateMergeBoard(db_path=db)
        assert b2.candidate(cand.candidateId).status == "reviseRequired"
        with pytest.raises(CandidateMergeError):
            b2.mergeCandidate(cand.candidateId), "reviseRequired 不可直接合入"
        b2.resubmitCandidate(cand.candidateId, "修正稿")
        b3 = CandidateMergeBoard(db_path=db)
        assert b3.candidate(cand.candidateId).status == CANDIDATE_SUBMITTED
        assert b3.candidate(cand.candidateId).content == "修正稿"

    def test_swarm_board_wiring_env(self, tmp_path, monkeypatch):
        """NEUROVA_SWARM_CANDIDATE_DB 指向显式路径时，swarm 候选板落库且跨管理器重建可见。"""
        from neurova.agent.swarm import SubAgentRun, get_swarm_manager, reset_swarm_manager

        db = str(tmp_path / "swarm_board.db")
        monkeypatch.setenv("NEUROVA_SWARM_CANDIDATE_DB", db)
        reset_swarm_manager()
        mgr = get_swarm_manager()
        run = SubAgentRun(agent_id="child", agent_name="子代理", task="t",
                          session_id="s1", origin="chat")
        mgr._runs[run.subagent_id] = run
        cand = mgr._submitResultCandidate(run, "重启后仍在的报告")
        assert cand.content == "重启后仍在的报告"
        reset_swarm_manager()
        mgr2 = get_swarm_manager()
        again = mgr2._candidates.candidate(cand.candidateId)
        assert again is not None, "SQLite 形态下候选跨管理器重建可见"
        assert again.content == "重启后仍在的报告"
        reset_swarm_manager()


class TestRoomPendingSqlite:
    def test_registry_persists_across_instances(self, tmp_path, monkeypatch):
        from neurova.agent import approval_chain as ac

        db = str(tmp_path / "room_pending.db")
        monkeypatch.setenv("NEUROVA_SWARM_ROOM_PENDING_DB", db)
        ac._roomBridgeStoreInstance = None
        try:
            ac._roomBridgePut("approval", "rid1", "room1")
            ac._roomBridgePut("candidate", "cid1", "room1")
            ac._roomBridgeStoreInstance = None  # 模拟另一进程重建单例
            assert ac.roomPendingApprovals("room1") == ["rid1"]
            assert ac.roomPendingCandidates("room1") == ["cid1"]
            assert ac._roomBridgeHas("approval", "rid1") is True
            ac._roomBridgePop("approval", "rid1")
            assert ac.roomPendingApprovals("room1") == []
            assert ac._matchRoomTarget("candidate", "room1", "处理 cid1") == "cid1"
        finally:
            ac._roomBridgeStoreInstance = None
            ac._roomBridgeClearAllForTests()

    def test_default_env_unset_uses_memory(self, monkeypatch):
        from neurova.agent import approval_chain as ac

        monkeypatch.delenv("NEUROVA_SWARM_ROOM_PENDING_DB", raising=False)
        ac._roomBridgeStoreInstance = None
        try:
            assert ac._roomBridgeStore() is None, "缺省不落库（内存形态）"
            ac._roomBridgePut("approval", "rid2", "room2")
            assert ac.roomPendingApprovals("room2") == ["rid2"]
        finally:
            ac._roomBridgeStoreInstance = None
            ac._roomBridgeClearAllForTests()
