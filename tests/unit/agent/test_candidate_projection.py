# -*- coding: utf-8 -*-
"""P2-3 候选板 H-4 事件重放投影 单元测试。

判据（计划 §5）：
- 折叠规则与 CandidateMergeBoard 状态迁移**一一对应**——同一条生命周期走真实
  CandidateMergeBoard 与 projectCandidateBoard 各一遍，snapshot 逐字段一致；
- 重启模拟（账本还在、内存板没了）后 submitted/merged/conflict 均可查；
- 账本缺事件（引用了不存在的候选）→ 诚实标 incomplete；
- 跨 run 事件按 occurred_at 全序折叠（seq 是 per-run 的，不能拿它当全局序）。
"""

import pytest

from neurova.agent.candidate_merge import CandidateMergeBoard
from neurova.agent.candidate_projection import projectCandidateBoard


def evt(sid: str, type_: str, payload: dict, seq: int, occurred_at: str) -> dict:
    """造一条 H-4 账本事件（与 swarm_event_log.appendRunEvent 落盘形态一致）。"""
    return {
        "event_id": f"evt_{sid}_{seq}",
        "type": type_,
        "subagent_id": sid,
        "causation_id": "",
        "payload": payload,
        "occurred_at": occurred_at,
        "seq": seq,
        "lineage": {"depth": 1, "parent_subagent_id": "", "agent_path": [sid],
                    "team_id": "team-1", "tenant_id": "default"},
    }


def byId(snapshot: dict, candidateId: str) -> dict:
    match = [c for c in snapshot["candidates"] if c["candidate_id"] == candidateId]
    assert len(match) == 1, f"候选 {candidateId} 应恰有一条，实得 {len(match)}"
    return match[0]


class TestFoldMatchesLiveBoard:
    """同一生命周期：真板走一遍、投影折一遍，两边必须逐字段一致。"""

    def test_submitted_then_merged(self):
        board = CandidateMergeBoard()
        c1 = board.submitCandidate("run-1", "报告A", artifactKeys=["docs/api.md"], baseRevision=0)
        board.mergeCandidate(c1.candidateId)
        events = [
            evt("run-1", "candidate_submitted",
                {"candidate_id": c1.candidateId, "base_revision": 0,
                 "artifact_keys": ["docs/api.md"]}, 1, "2026-11-21T10:00:00+00:00"),
            evt("run-1", "candidate_merged",
                {"candidate_id": c1.candidateId, "revision": 1, "approval": "approved:L0"},
                2, "2026-11-21T10:00:05+00:00"),
        ]
        projected = projectCandidateBoard({"run-1": events})
        live = board.snapshot()
        assert projected["revision"] == live["revision"] == 1
        assert len(projected["candidates"]) == len(live["candidates"]) == 1
        got, want = projected["candidates"][0], live["candidates"][0]
        for key in ("candidate_id", "run_id", "artifact_keys", "base_revision",
                    "status", "conflict_with", "note", "decided_at"):
            if key == "decided_at":
                # 时间形态不同（账本 ISO 字符串 vs 板内 epoch 秒），比"是否已裁决"
                assert bool(got[key]) and bool(want[key])
            else:
                assert got[key] == want[key], f"字段 {key} 投影与内存板不一致"
        assert projected["candidates"][0]["status"] == "accepted"
        assert projected["conflicts"] == []

    def test_same_key_clash_flags_both(self):
        board = CandidateMergeBoard()
        a = board.submitCandidate("run-1", "报告A", artifactKeys=["k1"], baseRevision=0)
        b = board.submitCandidate("run-2", "报告B", artifactKeys=["k1"], baseRevision=0)
        assert a.conflictWith == [b.candidateId]
        assert b.conflictWith == [a.candidateId]
        events = [
            evt("run-1", "candidate_submitted",
                {"candidate_id": a.candidateId, "base_revision": 0, "artifact_keys": ["k1"]},
                1, "2026-11-21T10:00:00+00:00"),
            evt("run-1", "candidate_conflict_flagged",
                {"candidate_id": a.candidateId, "conflict_with": [b.candidateId]},
                2, "2026-11-21T10:00:01+00:00"),
            evt("run-2", "candidate_submitted",
                {"candidate_id": b.candidateId, "base_revision": 0, "artifact_keys": ["k1"]},
                3, "2026-11-21T10:00:02+00:00"),
            evt("run-2", "candidate_conflict_flagged",
                {"candidate_id": b.candidateId, "conflict_with": [a.candidateId]},
                4, "2026-11-21T10:00:03+00:00"),
        ]
        projected = projectCandidateBoard({"run-1": events[:2], "run-2": events[2:]})
        live = board.snapshot()
        assert projected["candidates"][0]["conflict_with"] == \
            live["candidates"][0]["conflict_with"] == [b.candidateId]
        assert projected["candidates"][1]["conflict_with"] == \
            live["candidates"][1]["conflict_with"] == [a.candidateId]
        assert len(projected["conflicts"]) == len(live["conflicts"]) == 2

    def test_cas_conflict_keeps_candidate_submitted(self):
        board = CandidateMergeBoard()
        c1 = board.submitCandidate("run-1", "先合", artifactKeys=["k1"], baseRevision=0)
        board.mergeCandidate(c1.candidateId)  # revision → 1
        c2 = board.submitCandidate("run-2", "后交", artifactKeys=["k2"], baseRevision=0)
        from neurova.agent.candidate_merge import CandidateConflictError

        with pytest.raises(CandidateConflictError):
            board.mergeCandidate(c2.candidateId)
        # 冲突后 c2 仍是 submitted（保留待裁决），note 带冲突说明
        events = [
            evt("run-1", "candidate_submitted",
                {"candidate_id": c1.candidateId, "base_revision": 0, "artifact_keys": ["k1"]},
                1, "2026-11-21T10:00:00+00:00"),
            evt("run-1", "candidate_merged",
                {"candidate_id": c1.candidateId, "revision": 1, "approval": "approved:L0"},
                2, "2026-11-21T10:00:02+00:00"),
            evt("run-2", "candidate_submitted",
                {"candidate_id": c2.candidateId, "base_revision": 0, "artifact_keys": ["k2"]},
                3, "2026-11-21T10:00:03+00:00"),
            evt("run-2", "candidate_conflict",
                {"candidate_id": c2.candidateId,
                 # 与 swarm._mergeCandidateForRun 实际落账的 detail 一致：
                 # str(CandidateConflictError) = 板内 note 原文
                 "detail": "CAS 冲突：候选基准 0 ≠ 当前集成版本 1；候选保留待人工裁决"},
                4, "2026-11-21T10:00:05+00:00"),
        ]
        projected = projectCandidateBoard({"run-1": events[:2], "run-2": events[2:]})
        got = byId(projected, c2.candidateId)
        live = board.snapshot()
        liveC2 = [c for c in live["candidates"] if c["candidate_id"] == c2.candidateId][0]
        assert got["status"] == liveC2["status"] == "submitted"
        assert got["note"] == liveC2["note"]
        assert projected["revision"] == live["revision"] == 1

    def test_revise_required_then_room_reject(self):
        board = CandidateMergeBoard()
        c1 = board.submitCandidate("run-1", "草稿", artifactKeys=[], baseRevision=0)
        board.markReviseRequired(c1.candidateId, "验收未达标")
        board.rejectCandidate(c1.candidateId, reason="人工否决")
        events = [
            evt("run-1", "candidate_submitted",
                {"candidate_id": c1.candidateId, "base_revision": 0, "artifact_keys": []},
                1, "2026-11-21T10:00:00+00:00"),
            evt("run-1", "candidate_revise_required",
                {"candidate_id": c1.candidateId, "reason": "验收未达标"},
                2, "2026-11-21T10:00:04+00:00"),
            evt("run-1", "candidate_rejected",
                {"candidate_id": c1.candidateId, "by": "room", "actor": "user-9"},
                3, "2026-11-21T10:00:06+00:00"),
        ]
        projected = projectCandidateBoard({"run-1": events})
        live = board.snapshot()
        got = byId(projected, c1.candidateId)
        liveC1 = live["candidates"][0]
        assert got["status"] == liveC1["status"] == "rejected"
        assert projected["revision"] == live["revision"] == 0

    def test_merge_rejected_changes_nothing(self):
        """candidate_merge_rejected 在板上是 no-op（状态不允许/重复合入都不改板）。"""
        board = CandidateMergeBoard()
        c1 = board.submitCandidate("run-1", "正文", artifactKeys=[], baseRevision=0)
        board.markReviseRequired(c1.candidateId, "先改")
        events = [
            evt("run-1", "candidate_submitted",
                {"candidate_id": c1.candidateId, "base_revision": 0, "artifact_keys": []},
                1, "2026-11-21T10:00:00+00:00"),
            evt("run-1", "candidate_revise_required",
                {"candidate_id": c1.candidateId, "reason": "先改"},
                2, "2026-11-21T10:00:01+00:00"),
            evt("run-1", "candidate_merge_rejected",
                {"candidate_id": c1.candidateId, "detail": "状态为 reviseRequired，不可合入"},
                3, "2026-11-21T10:00:02+00:00"),
        ]
        projected = projectCandidateBoard({"run-1": events})
        got = byId(projected, c1.candidateId)
        assert got["status"] == "reviseRequired"
        assert projected["revision"] == 0


class TestReplayAfterRestart:
    def test_submitted_still_queryable_from_ledger_alone(self, tmp_path, monkeypatch):
        """重启模拟：真账本落盘 → 新进程内存板为空 → 投影仍能查出在途候选。"""
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        from neurova.agent.swarm_event_log import appendRunEvent, readRunEvents

        appendRunEvent("swarm_replay_1", "candidate_submitted",
                       {"candidate_id": "cand_replay1", "base_revision": 0,
                        "artifact_keys": ["docs/x.md"]})
        snapshot = projectCandidateBoard({"swarm_replay_1": readRunEvents("swarm_replay_1")})
        assert snapshot["source"] == "replay"
        assert snapshot["incomplete"] is False
        assert snapshot["candidates"][0]["candidate_id"] == "cand_replay1"
        assert snapshot["candidates"][0]["status"] == "submitted"
        assert snapshot["candidates"][0]["run_id"] == "swarm_replay_1"

    def test_empty_ledger_projects_empty_board(self):
        snapshot = projectCandidateBoard({})
        assert snapshot["candidates"] == []
        assert snapshot["conflicts"] == []
        assert snapshot["revision"] == 0
        assert snapshot["incomplete"] is False


class TestHonestIncomplete:
    def test_event_referencing_unknown_candidate_marks_incomplete(self):
        events = [
            evt("run-1", "candidate_merged",
                {"candidate_id": "cand_ghost", "revision": 1, "approval": "approved:L0"},
                1, "2026-11-21T10:00:00+00:00"),
        ]
        snapshot = projectCandidateBoard({"run-1": events})
        assert snapshot["incomplete"] is True

    def test_bad_submitted_payload_marks_incomplete(self):
        events = [evt("run-1", "candidate_submitted", {"base_revision": 0}, 1,
                      "2026-11-21T10:00:00+00:00")]
        snapshot = projectCandidateBoard({"run-1": events})
        assert snapshot["incomplete"] is True
        assert snapshot["candidates"] == []


class TestCrossRunOrdering:
    def test_global_order_by_occurred_at_not_by_run_grouping(self):
        """seq 是 per-run 计数：run-2 的 seq=1 可能晚于 run-1 的 seq=9。
        折叠必须按 occurred_at 全序，revision 才能收敛到正确的末值。"""
        eventsRun1 = [
            evt("run-1", "candidate_submitted",
                {"candidate_id": "c1", "base_revision": 0, "artifact_keys": ["a"]},
                9, "2026-11-21T10:00:01+00:00"),
            evt("run-1", "candidate_merged",
                {"candidate_id": "c1", "revision": 1, "approval": "approved:L0"},
                10, "2026-11-21T10:00:03+00:00"),
        ]
        eventsRun2 = [
            evt("run-2", "candidate_submitted",
                {"candidate_id": "c2", "base_revision": 1, "artifact_keys": ["b"]},
                1, "2026-11-21T10:00:02+00:00"),
            evt("run-2", "candidate_merged",
                {"candidate_id": "c2", "revision": 2, "approval": "approved:L0"},
                2, "2026-11-21T10:00:04+00:00"),
        ]
        snapshot = projectCandidateBoard({"run-1": eventsRun1, "run-2": eventsRun2})
        assert snapshot["revision"] == 2
        assert byId(snapshot, "c1")["status"] == "accepted"
        assert byId(snapshot, "c2")["status"] == "accepted"


class TestSnapshotShape:
    def test_snapshot_keys_are_pinned(self):
        snapshot = projectCandidateBoard({})
        assert set(snapshot.keys()) == {"revision", "candidates", "conflicts",
                                        "incomplete", "source"}
        events = [evt("run-1", "candidate_submitted",
                      {"candidate_id": "c1", "base_revision": 0, "artifact_keys": ["a"]},
                      1, "2026-11-21T10:00:00+00:00")]
        snapshot = projectCandidateBoard({"run-1": events})
        assert set(snapshot["candidates"][0].keys()) == {
            "candidate_id", "run_id", "artifact_keys", "base_revision", "status",
            "conflict_with", "note", "created_at", "decided_at"}
