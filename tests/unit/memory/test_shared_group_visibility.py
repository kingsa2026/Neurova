# -*- coding: utf-8 -*-
"""P1-10 残留实装·共享组可见性验收（黑盒，双读路）。

语义（isolation.py 单源）：行标记 shared（旧模式＝本 agent 全员可见）或
share_group_ids 与读者组有交集时，跨第 2/3 层可见；其余行维持三层隔离。
读者组经 set_shared_group_resolver 注入（core 不 import auth）。
"""
import pytest


@pytest.fixture
def mgr(tmp_path):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    mgr = MemoryManager(
        db_path=str(tmp_path / "m.db"),
        agent_id="agent_iso",
        neuser_id="default",
        user_id="default",
    )
    # 读者组关系源：u-b ∈ g1；其余用户无组
    mgr.set_shared_group_resolver(lambda uid: ("g1",) if uid == "u-b" else ())
    return mgr


def _contents(rows):
    return [(r.get("content") if isinstance(r, dict) else getattr(r, "content", "")) or "" for r in rows]


class TestSharedGroupVisibility:
    def test_group_member_sees_shared_row_both_read_paths(self, mgr):
        mgr.set_request_scope(neuser_id="ne-a", user_id="u-a")
        mgr.remember("共享组记忆标记S", auto_classify=False, share_group_ids=["g1"])

        # 读者 u-b（组 g1）：内存召回路（仲裁器）
        mgr.set_request_scope(neuser_id="ne-b", user_id="u-b")
        assert any("共享组记忆标记S" in c for c in _contents(mgr.recall("共享组记忆标记S"))), (
            "同组读者经内存召回路必须可见"
        )
        # db 全文检索路（SQL 含共享行候选 + 仲裁器裁决）
        assert any(
            "共享组记忆标记S" in c for c in _contents(mgr.searchMemoriesFulltext("共享组记忆标记S"))
        ), "同组读者经全文检索路必须可见"

    def test_non_member_cannot_see_shared_row(self, mgr):
        mgr.set_request_scope(neuser_id="ne-a", user_id="u-a")
        mgr.remember("共享组记忆标记S", auto_classify=False, share_group_ids=["g1"])

        mgr.set_request_scope(neuser_id="ne-c", user_id="u-c")  # 无组
        assert not any(
            "共享组记忆标记S" in c
            for c in _contents(mgr.recall("共享组记忆标记S") + mgr.searchMemoriesFulltext("共享组记忆标记S"))
        ), "无组读者不得看见共享组行"

    def test_legacy_shared_flag_visible_to_whole_agent(self, mgr):
        mgr.set_request_scope(neuser_id="ne-a", user_id="u-a")
        mgr.remember("旧模式共享标记L", auto_classify=False, shared=True)

        mgr.set_request_scope(neuser_id="ne-b", user_id="u-b")
        assert any(
            "旧模式共享标记L" in c
            for c in _contents(mgr.recall("旧模式共享标记L") + mgr.searchMemoriesFulltext("旧模式共享标记L"))
        ), "旧模式 shared=1＝本 agent 全员可见"

    def test_unshared_row_stays_isolated(self, mgr):
        mgr.set_request_scope(neuser_id="ne-a", user_id="u-a")
        mgr.remember("私有记忆P", auto_classify=False)

        mgr.set_request_scope(neuser_id="ne-b", user_id="u-b")
        assert not any(
            "私有记忆P" in c
            for c in _contents(mgr.recall("私有记忆P") + mgr.searchMemoriesFulltext("私有记忆P"))
        ), "无共享标记的行维持三层隔离"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
