# -*- coding: utf-8 -*-
"""
P1-5 检查点防回归网（对标实施文档 P1-5）

范围：会话 JSON + 知识库文件；git 裸仓库（零新依赖，git CLI plumbing）；
refs 规范 {auto,snap,pre-restore}/{session_key}/{ts}；恢复前自动
pre-restore 留档；GC keep_count/keep_days。

锁定契约：
1. 快照 → 修改 → 恢复 → 还原（端到端）
2. restore 前自动 pre-restore 存在
3. GC 保留策略（keep_count / keep_days 双维度）
4. 列表按时间排序、kind 过滤
"""
import pytest


@pytest.fixture()
def svc(tmp_path):
    from neurova.checkpoints.service import CheckpointService

    return CheckpointService(
        agent_id="agt1",
        base_dir=str(tmp_path / "checkpoints"),
        debounce_seconds=0,  # 测试不防抖
    )


SESSION_V1 = {"messages": [{"role": "user", "content": "hi"}], "turn": 1}
SESSION_V2 = {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}], "turn": 2}
KB_V1 = {"kb/notes.md": "# 笔记\n第一版", "kb/api.json": '{"v": 1}'}
KB_V2 = {"kb/notes.md": "# 笔记\n第二版", "kb/api.json": '{"v": 2}'}


class TestSnapshotRestoreRoundtrip:
    def test_snapshot_modify_restore_roundtrip(self, svc):
        import json

        ref1 = svc.snapshot_auto("sess-A", SESSION_V1, KB_V1)
        assert ref1.startswith("refs/auto/sess-A/")

        ref2 = svc.snapshot_auto("sess-A", SESSION_V2, KB_V2)
        assert ref2 != ref1

        # 恢复第一版：会话与 KB 均还原
        restored = svc.restore_snapshot(ref1)
        assert json.loads(restored["session_json"]) == SESSION_V1
        assert restored["kb_files"]["kb/notes.md"] == KB_V1["kb/notes.md"]
        assert restored["kb_files"]["kb/api.json"] == KB_V1["kb/api.json"]

    def test_manual_snapshot_ref_kind(self, svc):
        ref = svc.snapshot_manual("sess-B", SESSION_V1, KB_V1)
        assert ref.startswith("refs/snap/sess-B/")


class TestPreRestore:
    def test_restore_creates_pre_restore_snapshot(self, svc):
        import json

        ref1 = svc.snapshot_auto("sess-C", SESSION_V1, KB_V1)
        svc.snapshot_auto("sess-C", SESSION_V2, KB_V2)

        before = svc.list_snapshots(session_key="sess-C", kind="pre-restore")
        assert before == []

        svc.restore_snapshot(ref1)
        pres = svc.list_snapshots(session_key="sess-C", kind="pre-restore")
        assert len(pres) == 1
        # pre-restore 内容 = 恢复前的最新状态（V2）
        content = svc.restore_snapshot(pres[0]["ref"])
        assert json.loads(content["session_json"]) == SESSION_V2

    def test_restore_ref_itself_is_not_clobbered(self, svc):
        ref1 = svc.snapshot_auto("sess-D", SESSION_V1, KB_V1)
        svc.snapshot_auto("sess-D", SESSION_V2, KB_V2)
        svc.restore_snapshot(ref1)
        # 再读 ref1 仍是 V1（pre-restore 写别的 ref）
        import json

        assert json.loads(svc.restore_snapshot(ref1)["session_json"]) == SESSION_V1


class TestListSnapshots:
    def test_list_sorted_by_time_desc_with_meta(self, svc):
        r1 = svc.snapshot_auto("sess-E", SESSION_V1, KB_V1)
        r2 = svc.snapshot_auto("sess-E", SESSION_V2, KB_V2)
        snaps = svc.list_snapshots(session_key="sess-E")
        refs = [s["ref"] for s in snaps]
        assert refs == sorted(refs, reverse=True)  # 新在前
        assert snaps[0]["kind"] == "auto"
        assert snaps[0]["timestamp"] >= snaps[1]["timestamp"]
        assert r1 and r2

    def test_kind_filter(self, svc):
        svc.snapshot_auto("sess-F", SESSION_V1, KB_V1)
        svc.snapshot_manual("sess-F", SESSION_V2, KB_V2)
        auto = svc.list_snapshots(session_key="sess-F", kind="auto")
        snap = svc.list_snapshots(session_key="sess-F", kind="snap")
        assert len(auto) == 1 and len(snap) == 1


class TestGC:
    def test_gc_keeps_most_recent_by_count(self, svc):
        refs = [svc.snapshot_auto("sess-G", SESSION_V1, KB_V1) for _ in range(6)]
        # 每次内容相同 → hash 相同，但 ref 含 ts 必然不同；强制内容差异避免缓存歧义
        removed = svc.gc(keep_count=3, keep_days=3650)
        remaining = [s["ref"] for s in svc.list_snapshots(session_key="sess-G")]
        assert len(remaining) == 3
        assert removed >= 3

    def test_gc_drops_older_than_keep_days(self, svc):
        svc.snapshot_auto("sess-H", SESSION_V1, KB_V1)
        # 用 future ts 造一个"过期"快照：keep_days 极小
        svc.gc(keep_count=100, keep_days=0)
        remaining = svc.list_snapshots(session_key="sess-H")
        assert remaining == []  # 0 天保留 → 全部清掉

    def test_gc_respects_kinds_independently(self, svc):
        svc.snapshot_auto("sess-I", SESSION_V1, KB_V1)
        svc.snapshot_auto("sess-I", SESSION_V2, KB_V2)
        svc.gc(keep_count=1, keep_days=3650)
        assert len(svc.list_snapshots(session_key="sess-I", kind="auto")) == 1


class TestDebounce:
    def test_auto_snapshot_debounced(self, tmp_path):
        from neurova.checkpoints.service import CheckpointService

        svc = CheckpointService(
            agent_id="agt2",
            base_dir=str(tmp_path / "cp"),
            debounce_seconds=3600,  # 1 小时内不重复
        )
        svc.snapshot_auto("sess-J", SESSION_V1, KB_V1)
        svc.snapshot_auto("sess-J", SESSION_V2, KB_V2)  # 应被防抖吞掉
        assert len(svc.list_snapshots(session_key="sess-J", kind="auto")) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
