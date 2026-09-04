"""P0-2 知识条目 revision 链 + tombstone 删除（Utopia 对标落地清单）。

契约（docs/Neurova_Utopia代码级对比_2026-09-04.md §2.1/§2.7/§4 P0-2）：
- update_knowledge：知识实体字段（title/content/category/tags/confidence/source）
  被覆盖前，旧值快照追加进条目 revisions 账本（append-only，不随 update 丢失）；
  引擎簿记字段（graph_node_ids）变化不产生 revision（防 graph_bridge 写入刷屏）；
- list_revisions：按时间倒序返回 revision（最新在前）；
- delete_knowledge：tombstone 软删（打 deleted_at，全部读路径不可见），数据可恢复；
- purge_knowledge：物理删除（保留显式清除通道，如违规内容清理）；
- restore_knowledge：tombstone 复活（Utopia 0022 删除是事件，可从名单读回）；
- list_deleted：墓碑清单（含 deleted_at/deleted_by）；
- 重启（重新加载存储）后墓碑与 revision 账本均持久保留；
- 墓碑不进检索索引（失败方向：漏过滤的错误表现是"检索不到"而非"脏数据混入"）。
"""

import pytest

from neurova.knowledge.repository import KnowledgeRepository


@pytest.fixture
def repo(tmp_path):
    return KnowledgeRepository(tmp_path)


class TestRevisionChain:
    def test_content_update_snapshots_old_value(self, repo):
        item = repo.create_knowledge("default", title="账本", content="第一版内容")
        assert repo.update_knowledge(
            "default", item["knowledge_id"], {"content": "第二版内容"}
        )

        stored = repo.get_item("default", item["knowledge_id"])
        assert stored["content"] == "第二版内容"

        revs = repo.list_revisions(item["knowledge_id"])
        assert len(revs) == 1
        assert revs[0]["old"]["content"] == "第一版内容"
        assert revs[0]["changed_fields"] == ["content"]

    def test_multiple_updates_chain(self, repo):
        item = repo.create_knowledge("default", title="v0", content="c0")
        repo.update_knowledge("default", item["knowledge_id"], {"title": "v1"})
        repo.update_knowledge("default", item["knowledge_id"], {"title": "v2", "content": "c2"})

        revs = repo.list_revisions(item["knowledge_id"])
        assert len(revs) == 2
        # 最新在前
        assert revs[0]["old"]["title"] == "v1"
        assert revs[0]["old"]["content"] == "c0"
        assert revs[1]["old"]["title"] == "v0"

    def test_engine_bookkeeping_fields_do_not_spawn_revisions(self, repo):
        item = repo.create_knowledge("default", title="t", content="c")
        repo.update_knowledge(
            "default", item["knowledge_id"], {"graph_node_ids": ["n1", "n2"]}
        )
        assert repo.list_revisions(item["knowledge_id"]) == []

    def test_revisions_persist_across_instances(self, tmp_path):
        repo1 = KnowledgeRepository(tmp_path)
        item = repo1.create_knowledge("default", title="原题", content="原文")
        repo1.update_knowledge("default", item["knowledge_id"], {"title": "新题"})

        repo2 = KnowledgeRepository(tmp_path)
        revs = repo2.list_revisions(item["knowledge_id"])
        assert len(revs) == 1
        assert revs[0]["old"]["title"] == "原题"

    def test_list_revisions_unknown_entry(self, repo):
        assert repo.list_revisions("no-such-id") == []


class TestTombstoneDelete:
    def test_delete_hides_from_all_read_paths(self, repo):
        item = repo.create_knowledge(
            "default", title="要删的条目", content="量子计算内容", owner_user_id="u1"
        )
        kid = item["knowledge_id"]
        assert repo.delete_knowledge("default", kid, deleted_by="u1") is True

        assert repo.get_item("default", kid) is None
        assert repo.find_item(kid) is None
        assert repo.list_knowledge("default") == []
        assert repo.search_knowledge("default", "量子计算") == []
        admin = {"user_id": "admin", "role": "admin"}
        assert repo.visible_items(admin) == []

    def test_tombstone_persists_and_survives_reload(self, tmp_path):
        repo1 = KnowledgeRepository(tmp_path)
        item = repo1.create_knowledge("default", title="墓碑", content="c")
        kid = item["knowledge_id"]
        repo1.delete_knowledge("default", kid, deleted_by="u1")

        # 重启后墓碑仍在（数据没丢），且依然不可见
        repo2 = KnowledgeRepository(tmp_path)
        assert repo2.get_item("default", kid) is None
        deleted = repo2.list_deleted()
        assert len(deleted) == 1
        assert deleted[0]["item"]["knowledge_id"] == kid
        assert deleted[0]["deleted_by"] == "u1"
        assert deleted[0]["deleted_at"] > 0

    def test_deleted_excluded_from_index(self, repo):
        item = repo.create_knowledge("default", title="索引目标", content="独有关键词骷髅湾")
        kid = item["knowledge_id"]
        assert len(repo.search_visible_items({"user_id": "default"}, "骷髅湾")) == 1

        repo.delete_knowledge("default", kid)
        assert repo.search_visible_items({"user_id": "default"}, "骷髅湾") == []

    def test_restore_brings_back_visible(self, repo):
        item = repo.create_knowledge("default", title="复活条目", content="c")
        kid = item["knowledge_id"]
        repo.delete_knowledge("default", kid, deleted_by="u1")
        assert repo.restore_knowledge(kid) is True
        assert repo.get_item("default", kid)["title"] == "复活条目"
        assert repo.list_deleted() == []

    def test_restore_live_entry_is_noop_false(self, repo):
        item = repo.create_knowledge("default", title="活着", content="c")
        assert repo.restore_knowledge(item["knowledge_id"]) is False

    def test_purge_removes_everywhere(self, tmp_path):
        repo1 = KnowledgeRepository(tmp_path)
        item = repo1.create_knowledge("default", title="违规内容", content="c")
        kid = item["knowledge_id"]
        assert repo1.purge_knowledge("default", kid) is True

        repo2 = KnowledgeRepository(tmp_path)
        assert repo2.get_item("default", kid) is None
        assert repo2.list_deleted() == []

    def test_purge_unknown_returns_false(self, repo):
        assert repo.purge_knowledge("default", "no-such-id") is False

    def test_delete_unknown_returns_false(self, repo):
        assert repo.delete_knowledge("default", "no-such-id") is False
