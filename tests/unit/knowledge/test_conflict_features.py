"""冲突特征矩阵：相似 vs 数字对冲 vs 主题不同 vs 人工复核。"""
from neurova.knowledge.conflict_features import (
    buildConflictFeatures,
    classifyConflict,
)
from neurova.knowledge.repository import KnowledgeRepository


def test_four_quadrants():
    similar = buildConflictFeatures(
        "预算金额 100 万元，项目 Alpha", "预算金额 100 万元，项目 Alpha",
        vectorSimilarity=0.95,
    )
    assert classifyConflict(similar)[0] == "similar"

    conflict = buildConflictFeatures(
        "预算金额 100 万元，项目 Alpha", "预算金额 200 万元，项目 Alpha",
        vectorSimilarity=0.95,
    )
    assert classifyConflict(conflict)[0] == "conflict"

    different = buildConflictFeatures(
        "预算金额 100 万元，项目 Alpha", "服务器端口 9527，缓存策略",
        vectorSimilarity=0.90,
    )
    assert classifyConflict(different)[0] in ("different", "manual")

    manual = buildConflictFeatures(
        "Alpha 项目负责人张三", "Alpha 项目负责人李四",
        vectorSimilarity=0.20,
    )
    assert classifyConflict(manual)[0] == "manual"


def test_repository_conflict_records_features(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    first = repo.create_knowledge("default", "预算", "预算金额 100 万元", owner_user_id="1")
    repo.create_knowledge("default", "预算", "预算金额 200 万元", owner_user_id="1")

    conflicts = repo.list_conflicts("pending")
    assert conflicts
    item = next(c for c in conflicts if c.get("old_id") == first["knowledge_id"])
    assert item["features"]["numbers_conflict"] is True
    assert item["decision"] == "conflict"
    assert item["feature_reason"] == "high_similarity_but_numbers_conflict"
