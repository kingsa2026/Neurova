"""P0#1 知识库索引增量更新测试。

契约：
- 索引已建立后的条目变更走分片级增量操作（remove_documents + 新文档
  index_memories(incremental=True)），不再触发全量重建。
- 仅非索引字段变更（category/tags/confidence/source/graph_node_ids）
  不记录任何索引操作（graph_bridge 回写不刷屏重建）。
- content 更新时 chunks 同步重切（索引与块命中不读到旧文本）。
- 待应用操作数达阈值或应用异常 → 退回全量重建（陈旧 IDF 有界收敛）。
- 全量重建覆盖所有 agent 分组（修复：原实现只重建传入 agent，
  其他分组条目在重建时被静默清出索引）。
- UnifiedVectorStore：remove_documents 谓词删除 + _extend_idf 累积
  （修复：增量路径原以新文档统计整体重置 IDF，老词项 IDF 清零、存量向量不可达）。
"""

import pytest
from unittest.mock import patch

from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
from neurova.knowledge.repository import KnowledgeRepository, VISIBILITY_PRIVATE


@pytest.fixture
def repo(tmp_path):
    return KnowledgeRepository(str(tmp_path))


def _seed(repo, title, content, owner="1", **kw):
    item = repo.create_knowledge(
        agent_id=kw.pop("agent_id", "default"),
        title=title,
        content=content,
        owner_user_id=owner,
        **kw,
    )
    return item["knowledge_id"]


def _built(repo):
    """触发一次全量重建，把索引置于"已建立、干净"状态。"""
    repo._rebuild_vector_index_for_agent("default")
    assert repo._index_dirty is False


class TestVectorStoreOps:
    def test_remove_documents_exact_and_prefix(self):
        store = UnifiedVectorStore(backend="tfidf")
        store.index_memories([
            {"id": "x", "content": "hello world"},
            {"id": "y", "content": "hello python"},
            {"id": "k#0", "content": "alpha doc"},
            {"id": "k#1", "content": "beta doc"},
        ])
        n = store.remove_documents(lambda mid: mid == "x" or mid == "k" or str(mid).startswith("k#"))
        assert n == 3
        assert sorted(store.memory_ids) == ["y"]
        assert len(store.memory_vectors) == 1
        assert len(store.memory_metadata) == 1
        # 矩阵同步刷新（搜索不再命中已删文档）
        assert store._np_matrix is None or store._np_matrix.shape[0] == 1
        hits = store.search("alpha beta doc", limit=5)
        assert all((h.get("id") or h.get("memory_id")) not in ("x", "k#0", "k#1") for h in hits)

    def test_incremental_idf_keeps_old_tokens(self):
        """修复根因：index_memories(incremental) 原把 IDF 重置为仅新文档统计，
        老词项从 _idf_values 消失 → 查询老词时存量向量不可达。"""
        store = UnifiedVectorStore(backend="tfidf")
        store.index_memories([
            {"id": "a", "content": "alpha beta"},
            {"id": "b", "content": "alpha gamma"},
        ])
        store.index_memories([{"id": "c", "content": "beta delta"}], incremental=True)
        # 全语料统计：alpha df=2/3 == delta df=1/3？不等——alpha 更高频 IDF 更低，        # 关键是老词项仍存活
        assert "alpha" in store._idf_values, "增量后老词项 IDF 不得清零"
        assert store._idf_values["alpha"] < store._idf_values["delta"]
        hits = store.search("alpha", limit=3)
        hit_ids = [(h.get("id") or h.get("memory_id")) for h in hits]
        assert "a" in hit_ids and "b" in hit_ids


class TestIncrementalMutation:
    def test_create_uses_incremental_op(self, repo):
        _seed(repo, "初始", "NeurFlow 引擎")
        _built(repo)
        _seed(repo, "新增", "Zephyr 编排")  # 独有词，与"初始"零词面重叠
        assert repo._index_dirty is False, "增量路径不得置脏"
        assert len(repo._pending_ops) == 1
        with patch.object(repo, "_rebuild_indexes", wraps=repo._rebuild_indexes) as m:
            results = repo.search_visible_items(
                user={"user_id": "1"}, query="Zephyr 编排", scope="all", limit=5
            )
            assert m.call_count == 0, "已建立索引后检索不应触发全量重建"
        assert [r["title"] for r in results] == ["新增"]
        assert repo._pending_ops == []

    def test_old_docs_still_searchable_after_increment(self, repo):
        _seed(repo, "甲", "NeurFlow 触发器")
        _built(repo)
        _seed(repo, "乙", "Zephyr 编排")
        repo.search_visible_items(user={"user_id": "1"}, query="Zephyr", scope="all", limit=5)
        results = repo.search_visible_items(user={"user_id": "1"}, query="触发器", scope="all", limit=5)
        assert results[0]["title"] == "甲"

    def test_update_reindexes_only_indexed_fields(self, repo):
        kid = _seed(repo, "AlphaX", "NeurFlow 正文")
        _built(repo)
        repo.update_knowledge("default", kid, {"category": "ops"})
        assert repo._pending_ops == [], "非索引字段变更不触发索引操作"
        repo.update_knowledge("default", kid, {"title": "BetaY"})
        assert repo._pending_ops and repo._pending_ops[0][0] == "reindex"
        results = repo.search_visible_items(user={"user_id": "1"}, query="BetaY", scope="all", limit=5)
        assert results and results[0]["knowledge_id"] == kid
        old = repo.search_visible_items(user={"user_id": "1"}, query="AlphaX", scope="all", limit=5)
        assert not old

    def test_content_update_rechunks(self, repo):
        """内容更新必须重切 chunks——旧块文本/偏移不得污染索引与块命中。"""
        long1 = "旧内容说明。" * 100  # 必然多块
        long2 = "新主题论述。" * 100
        kid = _seed(repo, "演化", long1)
        _built(repo)
        repo.update_knowledge("default", kid, {"content": long2})
        item = repo.get_item("default", kid)
        assert item["chunks"][0]["content"].startswith("新主题")
        results = repo.search_visible_items(user={"user_id": "1"}, query="新主题论述", scope="all", limit=5)
        assert results and results[0]["knowledge_id"] == kid
        hits = results[0].get("chunk_hits") or []
        assert hits and all("旧内容" not in h["content"] for h in hits)
        gone = repo.search_visible_items(user={"user_id": "1"}, query="旧内容说明", scope="all", limit=5)
        assert not gone

    def test_delete_removes_from_index(self, repo):
        kid = _seed(repo, "将被删除", "Quantum 独有词条目")
        _built(repo)
        repo.search_visible_items(user={"user_id": "1"}, query="Quantum", scope="all", limit=5)
        repo.delete_knowledge("default", kid)
        assert repo._pending_ops == [("remove", kid)]
        results = repo.search_visible_items(user={"user_id": "1"}, query="Quantum", scope="all", limit=5)
        assert not results

    def test_share_moves_shard_incrementally(self, repo):
        kid = _seed(repo, "共享文档", "Orbit 协作要点")
        _built(repo)
        # user2 先检索（建立 public/user:2 分片；shared 分片为空）
        before = repo.search_visible_items(user={"user_id": "2"}, query="Orbit", scope="all", limit=5)
        assert not before, "共享前 user2 不可见"
        repo.share_entry({"user_id": "1"}, kid, ["2"])
        assert repo._pending_ops, "分片迁移应记录 reindex 操作"
        after = repo.search_visible_items(user={"user_id": "2"}, query="Orbit", scope="all", limit=5)
        assert [r["title"] for r in after] == ["共享文档"]
        # owner 依然可见（私库分片移除、shared 分片加入）
        own = repo.search_visible_items(user={"user_id": "1"}, query="Orbit", scope="all", limit=5)
        assert [r["title"] for r in own] == ["共享文档"]

    def test_restore_reindexes(self, repo):
        kid = _seed(repo, "复活的", "Lazarus 条目")
        _built(repo)
        repo.delete_knowledge("default", kid)
        repo.search_visible_items(user={"user_id": "1"}, query="Lazarus", scope="all", limit=5)
        repo.restore_knowledge(kid)
        results = repo.search_visible_items(user={"user_id": "1"}, query="Lazarus", scope="all", limit=5)
        assert [r["title"] for r in results] == ["复活的"]


class TestRebuildSafetyNet:
    def test_ops_threshold_triggers_full_rebuild(self, repo, monkeypatch):
        import neurova.knowledge.repository as repo_mod

        monkeypatch.setattr(repo_mod, "_INCREMENTAL_OPS_LIMIT", 3)
        _seed(repo, "阈值", "Threshold 词汇")
        _built(repo)
        for i in range(3):
            _seed(repo, f"批量{i}", f"BatchTerm{i} 内容")
        assert len(repo._pending_ops) >= 3
        results = repo.search_visible_items(user={"user_id": "1"}, query="BatchTerm2", scope="all", limit=5)
        assert [r["title"] for r in results] == ["批量2"]
        assert repo._pending_ops == [], "阈值触发全量重建后清空操作队列"

    def test_rebuild_covers_all_agents(self, repo):
        """修复：全量重建只覆盖传入 agent_id 分组，其他分组条目被清出索引。"""
        _seed(repo, "默认组", "Crossflow 默认引擎", agent_id="default")
        _seed(repo, "其他组", "Crossflow 其他引擎", agent_id="agent-b")
        results = repo.search_visible_items(
            user={"user_id": "1"}, query="Crossflow", scope="all", limit=10
        )
        titles = {r["title"] for r in results}
        assert titles == {"默认组", "其他组"}

    def test_incremental_failure_falls_back(self, repo):
        """应用增量操作异常 → 退回全量重建兜底，检索仍正确。"""
        _seed(repo, "基线", "Baseline 条目")
        _built(repo)
        kid = _seed(repo, "扰动", "Perturb 条目")
        with patch.object(repo, "_apply_pending_ops", side_effect=RuntimeError("boom")):
            repo.search_visible_items(user={"user_id": "1"}, query="Perturb", scope="all", limit=5)
        results = repo.search_visible_items(user={"user_id": "1"}, query="Perturb", scope="all", limit=5)
        assert results and results[0]["knowledge_id"] == kid
