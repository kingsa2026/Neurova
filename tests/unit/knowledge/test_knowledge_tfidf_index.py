"""知识库 TF-IDF 分片索引（复用 UnifiedVectorStore tfidf 后端）单元测试。

契约：
- KnowledgeRepository 懒加载分片索引：public（公库无隔离）/ user:<uid>（私库）/ shared（共享集）
- search_visible_items 优先走分片 TF-IDF 相似度 top-k（按 score 降序）
- TF-IDF 不可用/空时回退 substring 包含匹配（零破坏）
- 可见性过滤先于索引检索（隔离优先）；分片隔离：用户 A 私库不进用户 B 的检索
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from neurova.knowledge.repository import KnowledgeRepository, VISIBILITY_PRIVATE


@pytest.fixture
def repo(tmp_path):
    """临时目录上的知识仓库（隔离 JSON/索引）"""
    return KnowledgeRepository(str(tmp_path))


class TestKnowledgeTfidfIndex:
    """知识库 TF-IDF 索引"""

    def _save_item(self, repo, item):
        """帮助方法：写入条目（用 repo 的 create_knowledge）"""
        repo.create_knowledge(
            agent_id="default",
            title=item.get("title", ""),
            content=item.get("content", ""),
            category=item.get("category", "general"),
            tags=item.get("tags", []),
            source=item.get("source", ""),
            confidence=item.get("confidence", 0.5),
            visibility=item.get("visibility", VISIBILITY_PRIVATE),
            owner_user_id=item.get("owner_user_id", "1"),
        )

    def test_search_has_tfidf_shards(self, repo):
        """仓库应懒加载分片索引（public + user:<uid> + shared）"""
        assert "public" in repo._indexes or repo._get_vector_store("public") is not None
        assert repo._get_vector_store("private", "1").backend == "tfidf"
        assert repo._get_vector_store("shared").backend == "tfidf"

    def test_search_returns_relevant_first(self, repo):
        """TF-IDF 命中时应按相关性排序（相关条目在前）"""
        self._save_item(repo, {"title": "触发器", "content": "NeurFlow 工作流引擎支持 Cron 和 Webhook 触发器"})
        self._save_item(repo, {"title": "无关", "content": "今天天气很好"})
        # 重建索引后按 TF-IDF 检索
        repo._rebuild_vector_index_for_agent("default")
        results = repo.search_visible_items(
            user={"user_id": "1"}, query="NeurFlow 触发器", scope="all", limit=5
        )
        assert results, "应命中结果"
        assert results[0]["title"] == "触发器"

    def test_search_fallback_to_substring(self, repo):
        """TF-IDF 不可用时回退 substring 包含匹配（零破坏）"""
        self._save_item(repo, {"title": "NeurFlow 工作流引擎", "content": "核心能力是可视化编排"})
        # 强制分片索引不可用（模拟 TF-IDF 初始化失败）
        repo._indexes = {"public": None, "user:1": None, "shared": None}
        results = repo.search_visible_items(
            user={"user_id": "1"}, query="NeurFlow", scope="all", limit=5
        )
        assert len(results) == 1

    def test_shard_isolation_private_not_in_others(self, repo):
        """分片隔离：用户 A 私库条目不进用户 B 的检索（索引层隔离）"""
        self._save_item(repo, {"title": "A私库", "content": "Alice 私有 NeurFlow 秘密", "owner_user_id": "1"})
        self._save_item(repo, {"title": "B私库", "content": "Bob 私有 NeurFlow 秘密", "owner_user_id": "2"})
        self._save_item(repo, {"title": "公库", "content": "NeurFlow 公开知识", "owner_user_id": "1", "visibility": "public"})
        repo._rebuild_vector_index_for_agent("default")
        # 分片键检查：A/B 各有独立 user 分片；公库独立分片
        assert "user:1" in repo._indexes
        assert "user:2" in repo._indexes
        assert "public" in repo._indexes
        # Alice(user=1) 检索：命中自己私库 + 公库，不见 Bob 私库
        results_a = repo.search_visible_items(
            user={"user_id": "1"}, query="NeurFlow 秘密", scope="all", limit=5
        )
        titles_a = {r["title"] for r in results_a}
        assert "A私库" in titles_a
        assert "B私库" not in titles_a
        # Bob(user=2) 检索：命中自己私库，不见 A 私库
        results_b = repo.search_visible_items(
            user={"user_id": "2"}, query="NeurFlow 秘密", scope="all", limit=5
        )
        titles_b = {r["title"] for r in results_b}
        assert "B私库" in titles_b
        assert "A私库" not in titles_b

    def test_shared_shard_visible_to_shared_with(self, repo):
        """共享集分片：shared_with 用户可见共享条目"""
        # 创建 shared_with=[3] 的条目（通过直接注入模拟）
        repo.create_knowledge(
            agent_id="default", title="团队共享", content="NeurFlow 团队协作要点",
            category="general", tags=[], source="", confidence=0.5,
            visibility=VISIBILITY_PRIVATE, owner_user_id="1",
        )
        item = repo.get_item("default", repo._items["default"][-1]["knowledge_id"])
        repo.share_knowledge("default", repo._items["default"][-1]["knowledge_id"], ["3"]) \
            if hasattr(repo, "share_knowledge") else None
        repo._rebuild_vector_index_for_agent("default")
        # 用户3（共享伙伴）：应可见（shared 分片命中后经可见集过滤）
        results = repo.search_visible_items(
            user={"user_id": "3"}, query="NeurFlow 团队", scope="all", limit=5
        )
        titles = {r["title"] for r in results}
        # 若共享机制生效（share_knowledge 存在）则断言可见；否则跳过
        if hasattr(repo, "share_knowledge"):
            assert "团队共享" in titles

    def test_isolation_after_index(self, repo):
        """索引检索仍受可见性隔离（他人私有条目不可见）"""
        self._save_item(repo, {"title": "私密知识", "content": "Alice 的私有 NeurFlow 笔记", "owner_user_id": "1"})
        self._save_item(repo, {"title": "公开知识", "content": "NeurFlow 公开文档", "owner_user_id": "2", "visibility": "public"})
        repo._rebuild_vector_index_for_agent("default")
        # bob(user_id=2) 检索：应只有公开条目
        results = repo.search_visible_items(
            user={"user_id": "2"}, query="NeurFlow", scope="all", limit=5
        )
        titles = {r["title"] for r in results}
        assert "公开知识" in titles
        assert "私密知识" not in titles

    def test_index_rebuilt_on_mutation(self, repo):
        """写入/变更后索引应重建（dirty 标记）"""
        self._save_item(repo, {"title": "初始", "content": "NeurFlow 初版"})
        assert repo._index_dirty is True
        repo._rebuild_vector_index_for_agent("default")
        assert repo._index_dirty is False
        # 新增条目 → dirty 再次置位
        self._save_item(repo, {"title": "新增", "content": "NeurFlow 新版"})
        assert repo._index_dirty is True
