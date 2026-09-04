"""P0-3 同值冲突可见化（Utopia 对标落地清单）。

契约（docs/Neurova_Utopia代码级对比_2026-09-04.md §2.5/§4 P0-3）：
- 新条目入库时与同 agent 内可见旧条目做冲突检测；判定为"同一事实的新说法"
  （标题或内容高度相似）时，旧条目打 conflict 标记，进待审列表；
- 冲突检测不阻断写入（新条目照常落库）——失败方向：检测缺席的错误表现是
  "少一个待审项"，绝不是"新知识丢失"；
- 冲突记录双端可追溯：old_id/new_id/knowledge_id（被标记条目自身视角）/
  similarity/reason/detected_at/status；
- list_conflicts：待审冲突清单（pending）；
- resolve_conflict：人工裁决 keep_both（保留双条目，关闭记录）/
  supersede_old（旧条目打 superseded_by 并 tombstone）；
- 已裁决（resolved）不再出现在待审清单；
- 旧条目已有 conflict 标记时再进新条目：追加新冲突记录，不覆盖旧记录。
"""

import pytest

from neurova.knowledge.repository import KnowledgeRepository


@pytest.fixture
def repo(tmp_path):
    return KnowledgeRepository(tmp_path)


class TestConflictDetection:
    def test_identical_title_flags_conflict(self, repo):
        repo.create_knowledge("default", title="量子计算入门", content="旧内容", owner_user_id="u1")
        item = repo.create_knowledge("default", title="量子计算入门", content="新内容", owner_user_id="u1")

        conflicts = repo.list_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0]["status"] == "pending"
        assert conflicts[0]["new_id"] == item["knowledge_id"]
        assert conflicts[0]["similarity"] >= 0.9

    def test_detection_does_not_block_write(self, repo):
        item = repo.create_knowledge("default", title="重复标题", content="c1")
        item2 = repo.create_knowledge("default", title="重复标题", content="c2")
        # 两条都完整落库
        assert repo.get_item("default", item["knowledge_id"]) is not None
        assert repo.get_item("default", item2["knowledge_id"]) is not None

    def test_unrelated_entries_no_conflict(self, repo):
        repo.create_knowledge("default", title="量子计算", content="量子比特")
        repo.create_knowledge("default", title="红烧肉做法", content="五花肉焯水")
        assert repo.list_conflicts() == []

    def test_conflict_record_has_both_sides(self, repo):
        old = repo.create_knowledge("default", title="同样的标题", content="a")
        new = repo.create_knowledge("default", title="同样的标题", content="b")
        c = repo.list_conflicts()[0]
        assert c["old_id"] == old["knowledge_id"]
        assert c["new_id"] == new["knowledge_id"]
        assert c["detected_at"] > 0
        assert c["reason"]

    def test_self_conflating_disabled_via_kwarg(self, repo):
        """显式关闭检测的导入路径（批量导入）不产生冲突记录。"""
        repo.create_knowledge("default", title="批量A", content="x", detect_conflict=False)
        repo.create_knowledge("default", title="批量A", content="y", detect_conflict=False)
        assert repo.list_conflicts() == []

    def test_conflicts_persist_across_instances(self, tmp_path):
        repo1 = KnowledgeRepository(tmp_path)
        repo1.create_knowledge("default", title="持久冲突", content="a")
        item = repo1.create_knowledge("default", title="持久冲突", content="b")

        repo2 = KnowledgeRepository(tmp_path)
        assert len(repo2.list_conflicts()) == 1
        assert repo2.list_conflicts()[0]["new_id"] == item["knowledge_id"]


class TestConflictResolution:
    def test_resolve_keep_both_closes_record(self, repo):
        repo.create_knowledge("default", title="冲突条目", content="a")
        repo.create_knowledge("default", title="冲突条目", content="b")
        c = repo.list_conflicts()[0]

        assert repo.resolve_conflict(c["conflict_id"], "keep_both", resolved_by="admin") is True
        assert repo.list_conflicts() == []
        # keep_both：两条都还活着
        assert repo.get_item("default", c["old_id"]) is not None
        assert repo.get_item("default", c["new_id"]) is not None

    def test_resolve_supersede_old_tombstones_old(self, repo):
        old = repo.create_knowledge("default", title="旧版知识", content="a")
        new = repo.create_knowledge("default", title="旧版知识", content="b")
        c = repo.list_conflicts()[0]

        assert repo.resolve_conflict(
            c["conflict_id"], "supersede_old", resolved_by="admin"
        ) is True
        # 旧条目进墓碑并带 superseded_by 链；新条目照常可见
        assert repo.get_item("default", old["knowledge_id"]) is None
        assert repo.get_item("default", new["knowledge_id"]) is not None
        deleted = repo.list_deleted()
        assert len(deleted) == 1
        assert deleted[0]["item"]["knowledge_id"] == old["knowledge_id"]
        assert deleted[0]["superseded_by"] == new["knowledge_id"]
        # 复活不带 supersede 链（普通复活）
        repo.restore_knowledge(old["knowledge_id"])
        assert repo.list_deleted() == []

    def test_resolved_conflicts_queryable(self, repo):
        repo.create_knowledge("default", title="裁决历史", content="a")
        repo.create_knowledge("default", title="裁决历史", content="b")
        c = repo.list_conflicts()[0]
        repo.resolve_conflict(c["conflict_id"], "keep_both", resolved_by="admin1")

        done = repo.list_conflicts(status="resolved")
        assert len(done) == 1
        assert done[0]["resolution"] == "keep_both"
        assert done[0]["resolved_by"] == "admin1"

    def test_invalid_resolution_raises(self, repo):
        repo.create_knowledge("default", title="非法裁决", content="a")
        repo.create_knowledge("default", title="非法裁决", content="b")
        c = repo.list_conflicts()[0]
        with pytest.raises(ValueError):
            repo.resolve_conflict(c["conflict_id"], "delete_everything")

    def test_supersede_failure_path_leaves_no_side_effect(self, repo):
        """坑1 回归锁：supersede_old 途中旧条目缺失（已删/已清）→ LookupError，
        冲突必须仍为 pending、不产生墓碑、不落 resolved——
        状态置位绝不能先于条目搬移（内存态与账本一致）。"""
        repo.create_knowledge("default", title="将被删除", content="a")
        repo.create_knowledge("default", title="将被删除", content="b")
        c = repo.list_conflicts()[0]
        # 旧条目先被外部删除
        repo.delete_knowledge("default", c["old_id"])

        with pytest.raises(LookupError):
            repo.resolve_conflict(c["conflict_id"], "supersede_old", resolved_by="admin")

        # 账本未被污染：仍 pending，无 resolved 历史
        assert len(repo.list_conflicts()) == 1
        assert repo.list_conflicts(status="resolved") == []
        # 新条目未被动过；墓碑只有 delete_knowledge 自己那条（superseded_by 为
        # None），resolve 失败路径没有再产生 supersede 墓碑
        assert repo.get_item("default", c["new_id"]) is not None
        deleted = repo.list_deleted()
        assert len(deleted) == 1
        assert deleted[0]["knowledge_id"] == c["old_id"]
        assert deleted[0]["superseded_by"] is None

    def test_second_new_entry_appends_not_overwrites(self, repo):
        repo.create_knowledge("default", title="三连冲突", content="a")
        repo.create_knowledge("default", title="三连冲突", content="b")
        repo.create_knowledge("default", title="三连冲突", content="c")
        assert len(repo.list_conflicts()) == 2
