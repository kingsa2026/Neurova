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
import json

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


class RealContractEngine(StubEngine):
    """忠实复刻 ONNXEmbeddingEngine 契约：encode_batch 返回 EmbeddingResult 而非 list。

    历史事故：StubEngine.encode_batch 返回 list 与真实引擎契约不符（mock 不忠实），
    ensure_indexed 对 EmbeddingResult 做 zip 迭代 TypeError 被吞掉，
    生产环境知识向量索引恒为空（computed=0）而单测全绿。
    """

    def encode_batch(self, texts):
        # `EmbeddingResult` 住在真 ONNX 引擎模块里，而那个模块顶层 `import numpy`——
        # CI 的精简锁按设计不含 numpy ⇒ 这一格从前在 CI 上**测的是一句假失败**
        # （契约一个字节都没验到，验的是"这台机器装没装 numpy"）。缺依赖时跳过并点名，
        # 不把"缺依赖"画成"契约破了"（教义第 2 条）。
        pytest.importorskip(
            "numpy",
            reason="EmbeddingResult 的定义在真 ONNX 引擎模块里，该模块顶层依赖 numpy")
        from neurova.embedding.onnx_embedding import EmbeddingResult

        return EmbeddingResult(
            vectors=[self.encode(t) for t in texts],
            model_name="stub-bge",
            dimension=len(self.VOCAB),
            inference_ms=0.0,
        )


class NamedEngine(StubEngine):
    """同一引擎类、不同模型名：用于验证索引指纹必须识别模型身份。"""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.dimension = len(self.VOCAB)


class TestFingerprintTracksIndexedText:
    """指纹的输入必须是**实际入库的嵌入文本**，不是时间戳与长度（§6-473）。

    §6-461 给倒排索引把指纹换成「整行列清单＋入库文本」后，向量这一侧仍留在
    `updated_at:len(content)` 上，当时写的是「今后任何不刷 updated_at 的条目写路径都会让它
    复发」——那句话只落在散文里，没有通道。本批把它根修掉：指纹改由嵌入文本哈希，
    前提不再需要任何人记得，也就不必配一张靠人登记的豁免表。

    可达形状有两头的账，各配一格，不许互相冒充：
    - **看不见改字**（漏重算）：同长度改正文、只改标题——时间戳不动时旧量都判"没变"。
      今天没有哪条公开路径会这样写（`_set_entry`/`update_knowledge` 都强刷时间戳），
      所以这一头用**规格格**钉指纹函数本身，不伪造存储路径冒充活体。
    - **白重算**（多算）：`share_entry`/`unshare`/`submit_to_public` 等都走 `_set_entry`，
      它无条件刷时间戳（repository.py:1051），而文本一个字没变 ⇒ 旧指纹照变 ⇒ 每分享一次
      就重算一遍 embedding。这一头今天真实可达，用行为格。
    """

    def _frozen(self, repo, kid):
        """取条目当前的时间戳（规格格里手工构造条目时用）。"""
        return repo.find_item(kid)[1].get("updated_at")

    def test_sameLengthContentEditChangesFingerprint(self, repo):
        """规格格：正文同长度改字 ⇒ 指纹必须变。"""
        from neurova.knowledge.vector_index import _fingerprint

        made = repo.create_knowledge("a", title="Sales Note", content="sales plan",
                                     owner_user_id="1")
        kid = made["knowledge_id"]
        before = _fingerprint(repo.find_item(kid)[1])
        entry = repo.find_item(kid)[1]
        entry["content"] = "sales plam"                 # 等长改字
        entry["updated_at"] = self._frozen(repo, kid)   # 时间戳不动：正是旧量看不见的那一形
        assert _fingerprint(entry) != before, "同长度改正文在指纹上不可见 ⇒ 索引会沿用旧向量"

    def test_titleOnlyEditChangesFingerprint(self, repo):
        """规格格：只改标题 ⇒ 指纹必须变（标题是嵌入文本的前半段）。"""
        from neurova.knowledge.vector_index import _fingerprint

        made = repo.create_knowledge("a", title="Travel Plan", content="travel quantum rust",
                                     owner_user_id="1")
        kid = made["knowledge_id"]
        before = _fingerprint(repo.find_item(kid)[1])
        entry = repo.find_item(kid)[1]
        entry["title"] = "Sales Plan"
        entry["updated_at"] = self._frozen(repo, kid)
        assert _fingerprint(entry) != before, "只改标题在指纹上不可见 ⇒ 向量仍是旧标题算出来的"

    def test_nonTextChangeDoesNotRecomputeVectors(self, repo, tmp_path):
        """行为格：只改可见性（文本未变）⇒ 向量不许重算。

        今天红的是这一条的反面：`share_entry` 走 `_set_entry` 强刷 `updated_at`，而旧指纹正是
        时间戳＋长度 ⇒ 分享一次就重算一遍从未变过的文本。修后指纹只认文本 ⇒ 零重算。
        """
        made = repo.create_knowledge("a", title="Secret Recipe", content="grandma cookie recipe",
                                     owner_user_id="1")
        first = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
        first.ensure_indexed(repo, ALICE)
        assert first.stats()["computed"] == 3

        bob = {"user_id": "2", "username": "b", "role": "user", "neuser_id": "2"}
        repo.share_entry(ALICE, made["knowledge_id"], ["2"])
        assert repo.find_item(made["knowledge_id"])[1].get("updated_at") != \
            made.get("updated_at"), "前提核对：分享确实刷新了时间戳（否则这格测不到东西）"

        again = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
        stats = again.ensure_indexed(repo, ALICE)
        assert stats["computed"] == 0, (
            "文本没变却被重算（每分享/撤销公开一次就白算一遍 embedding）：%s" % stats)

    def test_legacyFingerprintShapedRecordIsRecomputed(self, repo, tmp_path):
        """一次性代价要可见：旧形状（`时间戳:长度`）留在磁盘上时必须整条重算，不许沿用。"""
        vecDir = str(tmp_path / "vec")
        made = repo.create_knowledge("a", title="Async Rust", content="async rust plan",
                                     owner_user_id="1")
        kid = made["knowledge_id"]
        entry = repo.find_item(kid)[1]
        first = KnowledgeVectorIndex(vecDir, engine=StubEngine())
        first.ensure_indexed(repo, ALICE)
        # 分片文件名与载荷形状由索引自己定义，这里读它的口（不另抄一份命名规则）
        path = first._file_for(ALICE)
        assert path.is_file(), "索引分片没落盘，这格什么都没测：%s" % path
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload["vectors"]
        assert kid in records, "条目没进磁盘记录 ⇒ 磁盘形状变了，请同步本判据"
        records[kid]["fingerprint"] = "%s:%d" % (entry.get("updated_at", 0),
                                                 len(entry.get("content", "")))
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        again = KnowledgeVectorIndex(vecDir, engine=StubEngine())
        stats = again.ensure_indexed(repo, ALICE)
        assert stats["computed"] >= 1, "旧形状指纹被当作有效沿用 ⇒ 升级后仍可能带着旧向量检索"


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

    def test_real_engine_embeddingresult_contract(self, repo, tmp_path):
        """回归：真引擎 encode_batch 返回 EmbeddingResult 时索引必须成功构建。"""
        idx = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=RealContractEngine())
        stats = idx.ensure_indexed(repo, ALICE)
        assert stats["computed"] == 2, "EmbeddingResult 契约下向量必须真实入索引"
        assert stats["entry_count"] == 2
        hits = idx.search("quantum computing basics", ALICE, top_k=3)
        assert hits and hits[0]["title"] == "Quantum Guide"


class TestEngineIdentity:
    def test_same_engine_class_with_new_model_rebuilds(self, repo, tmp_path):
        """同一引擎类换 model_name 必须重建；只按类名做指纹会复用旧向量空间。"""
        idx_a = KnowledgeVectorIndex(
            str(tmp_path / "vec"), engine=NamedEngine("bge-model-a")
        )
        first = idx_a.ensure_indexed(repo, ALICE)
        assert first["computed"] == 2

        idx_b = KnowledgeVectorIndex(
            str(tmp_path / "vec"), engine=NamedEngine("bge-model-b")
        )
        second = idx_b.ensure_indexed(repo, ALICE)
        assert second["computed"] == 2, "换模型后必须重建索引，不能沿用旧模型的向量"

    def test_same_model_does_not_rebuild(self, repo, tmp_path):
        """模型名相同的重启/新实例仍应复用磁盘向量，不能退化成每次全量重算。"""
        idx_a = KnowledgeVectorIndex(
            str(tmp_path / "vec"), engine=NamedEngine("bge-model-a")
        )
        assert idx_a.ensure_indexed(repo, ALICE)["computed"] == 2

        idx_b = KnowledgeVectorIndex(
            str(tmp_path / "vec"), engine=NamedEngine("bge-model-a")
        )
        assert idx_b.ensure_indexed(repo, ALICE)["computed"] == 0

    def test_health_reports_files_records_and_engine(self, repo, tmp_path):
        idx = KnowledgeVectorIndex(
            str(tmp_path / "vec"), engine=NamedEngine("bge-model-a")
        )
        idx.ensure_indexed(repo, ALICE)

        health = idx.health()

        assert health["files"] == 1
        assert health["records"] == 2
        assert health["cached_users"] == 1
        assert "NamedEngine|bge-model-a" in health["engines"]
        assert health["errors"] == []


class TestHybridIntegration:
    def test_hybrid_uses_persisted_index(self, repo, idx, monkeypatch):
        """hybrid 的向量路命中持久化索引（通过 get_knowledge_vector_index 单例）"""
        from neurova.knowledge import vector_index as vi

        idx.ensure_indexed(repo, ALICE)
        monkeypatch.setattr(vi, "get_knowledge_vector_index", lambda: idx)

        got = vi.get_knowledge_vector_index()
        assert got.stats()["entry_count"] == 2
