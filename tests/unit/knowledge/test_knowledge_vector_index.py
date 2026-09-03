"""
知识库持久化向量索引（遗留修复 ②）

契约（KnowledgeVectorIndex）：
- ensure_indexed(repo, user)：把当前用户可见条目增量写入索引
  （按条目 updated_at/数量判断新增/变更，重启后从磁盘恢复，不重算未变条目）
- search(query, user, top_k)：query 单次 embedding，索引内余弦相似度，
  返回 [{id, title, content, score}]
- 索引持久化在 storage_dir（JSON：条目 id → 向量 + updated_at 指纹）
- embedding 引擎不可用时优雅降级（search 返回 []，ensure 不抛出）
"""
import pytest

from neurova.knowledge.vector_index import KnowledgeVectorIndex
from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "username": "a", "role": "user", "neuser_id": "1"}


class StubEngine:
    """确定性 embedding 桩：词袋 one-hot（维度=固定 8）"""

    VOCAB = ["quantum", "rust", "async", "cookie", "recipe", "travel", "sales", "plan"]

    def encode(self, text):
        t = (text or "").lower()
        return [1.0 if w in t else 0.0 for w in self.VOCAB]

    def encode_batch(self, texts):
        return [self.encode(t) for t in texts]


@pytest.fixture()
def repo(tmp_path):
    r = KnowledgeRepository(str(tmp_path / "kb"))
    r.create_knowledge("a", title="Quantum Guide", content="quantum computing",
                       visibility="public", owner_user_id="1")
    r.create_knowledge("a", title="Secret Recipe", content="grandma cookie recipe",
                       owner_user_id="1")
    return r


@pytest.fixture()
def idx(tmp_path):
    return KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())


class TestPersistence:
    def test_index_survives_restart_no_recompute(self, repo, idx, tmp_path):
        idx.ensure_indexed(repo, ALICE)
        first_stats = idx.stats()
        assert first_stats["entry_count"] == 2

        # 新实例（模拟重启）：同引擎 + 同目录
        idx2 = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
        idx2.ensure_indexed(repo, ALICE)
        assert idx2.stats()["entry_count"] == 2
        assert idx2.stats()["computed"] == 0  # 指纹未变，全部复用磁盘向量

    def test_new_or_changed_entry_incremental(self, repo, idx, tmp_path):
        idx.ensure_indexed(repo, ALICE)
        repo.create_knowledge("a", title="Travel Plan", content="travel plan", owner_user_id="1")

        idx2 = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
        stats = idx2.ensure_indexed(repo, ALICE)
        assert stats["computed"] == 1
        assert idx2.stats()["entry_count"] == 3

    def test_invisible_entries_not_indexed(self, repo, idx, tmp_path):
        idx.ensure_indexed(repo, ALICE)
        bob = {"user_id": "2", "username": "b", "role": "user", "neuser_id": "2"}
        bob_view = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
        bob_view.ensure_indexed(repo, bob)
        # bob 只能看到 public 一条
        assert bob_view.stats()["entry_count"] == 1


class TestSearch:
    def test_semantic_hit_via_index(self, repo, idx):
        idx.ensure_indexed(repo, ALICE)
        hits = idx.search("quantum computing basics", ALICE, top_k=3)
        assert hits and hits[0]["title"] == "Quantum Guide"
        assert 0.0 < hits[0]["score"] <= 1.0

    def test_private_not_leaked_to_others(self, repo, tmp_path):
        idx_alice = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
        idx_alice.ensure_indexed(repo, ALICE)
        bob = {"user_id": "2", "username": "b", "role": "user", "neuser_id": "2"}
        hits = idx_alice.search("cookie recipe", bob, top_k=3)
        assert hits == []  # Secret Recipe 是 alice 私有

    def test_engine_unavailable_degrades(self, repo, tmp_path):
        idx = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=None)
        idx.ensure_indexed(repo, ALICE)  # 不抛出
        assert idx.search("quantum", ALICE, top_k=3) == []


class TestHybridIntegration:
    def test_hybrid_uses_persisted_index(self, repo, idx, monkeypatch):
        """hybrid 的向量路命中持久化索引（通过 get_knowledge_vector_index 单例）"""
        from neurova.knowledge import vector_index as vi

        idx.ensure_indexed(repo, ALICE)
        monkeypatch.setattr(vi, "get_knowledge_vector_index", lambda: idx)

        got = vi.get_knowledge_vector_index()
        assert got.stats()["entry_count"] == 2
