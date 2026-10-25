"""知识索引周期维护与全量重算入口。"""
from neurova.knowledge.repository import KnowledgeRepository
from neurova.knowledge.vector_index import KnowledgeVectorIndex

ALICE = {"user_id": "1", "role": "admin"}


def _repo(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge(
        "default", title="alpha", content="alpha content",
        visibility="public", owner_user_id="1",
    )
    repo.create_knowledge(
        "default", title="beta", content="beta content",
        visibility="public", owner_user_id="1",
    )
    return repo


def test_repository_maintain_incremental_and_force(tmp_path):
    repo = _repo(tmp_path)

    incremental = repo.maintainIndexes(force=False)
    forced = repo.maintainIndexes(force=True)

    assert incremental["force"] is False
    assert forced["force"] is True
    assert forced["dirty"] is False
    assert forced["indexes"] >= 1
    assert repo.search_visible_items(ALICE, "alpha")


class Engine:
    """维护面替身：**每段文本都有自己的非零向量**。

    早先两行写成"含 alpha 才给 [1.0]，其余全 0"，于是 beta 那行拿到的是零向量——
    那正是嵌入引擎"没算出来"的兜底形态，写侧按"未算出"拒收（教义第 2 条：零向量
    不许当有效向量落库）。替身自己造出与生产同一型的坏输入，红出来的就是"少算了一条"。
    实测：改前 `computed == 1`（beta 缺席），改后 2。
    """

    model_name = "maintenance-stub"

    def encode(self, text):
        lowered = (text or "").lower()
        return [1.0 if "alpha" in lowered else 0.0, 1.0 if "beta" in lowered else 0.0]

    def encode_batch(self, texts):
        return [self.encode(t) for t in texts]


def test_vector_maintain_all_incremental_and_force(tmp_path):
    repo = _repo(tmp_path)
    vec = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=Engine())
    assert vec.ensure_indexed(repo, ALICE)["computed"] == 2
    assert vec.indexedUserIds() == ["1"]

    incremental = vec.maintainAll(repo, force=False)
    forced = vec.maintainAll(repo, force=True)

    assert incremental["users"] == 1
    assert incremental["entries"] == 2
    assert incremental["computed"] == 0
    assert forced["computed"] == 2
    assert forced["errors"] == []


def test_maintenance_wrapper_reports_both_faces(tmp_path):
    from neurova.knowledge.maintenance import maintainKnowledgeIndexes

    repo = _repo(tmp_path)
    vec = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=Engine())
    vec.ensure_indexed(repo, ALICE)

    result = maintainKnowledgeIndexes(force=False, repo=repo, vector=vec)

    assert "repository" in result and "vector" in result
    assert result["vector"]["users"] == 1
