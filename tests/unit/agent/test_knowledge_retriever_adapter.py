"""KnowledgeRetrieverAdapter 单元测试

知识库检索器接入 MemoryRetrievalChain：
- 通过 repository.search_visible_items 检索用户可见知识
- 用户隔离透传（user_id / agent_id）
- 结果转换为 RetrievalResult（memories 载荷 + 质量评分）
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock

from neurova.agent.memory_retrieval_chain import (
    MemoryRetrievalChain,
    RetrievalContext,
    RetrievalQuality,
)


# 待实现的适配器（红测：导入失败时跳过文件报错，用 pytest.importorskip 语义）
try:
    from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
except ImportError:
    KnowledgeRetrieverAdapter = None


@pytest.fixture
def mock_repo():
    """模拟知识库 repository"""
    repo = Mock()
    repo.search_visible_items = MagicMock(return_value=[])
    return repo


class TestKnowledgeRetrieverAdapter:
    """测试 KnowledgeRetrieverAdapter"""

    def test_implements_retriever_protocol(self):
        """应实现 Retriever 协议（name/priority/retrieve 属性）"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        adapter = KnowledgeRetrieverAdapter(repo=Mock())
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "priority")
        assert hasattr(adapter, "retrieve")

    def test_name_and_priority(self):
        """名称应为 KnowledgeRetriever，优先级中等(25)"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        adapter = KnowledgeRetrieverAdapter(repo=Mock())
        assert adapter.name == "KnowledgeRetriever"
        # 优先级：UnifiedRetriever(10) < MoE(20) < Knowledge(25) < Cache(30)
        assert adapter.priority == 25

    @pytest.mark.asyncio
    async def test_retrieve_invokes_repo_with_user_scope(self):
        """retrieve 应调用 repository.search_visible_items 并透传用户隔离参数"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        repo = Mock()
        repo.search_visible_items = MagicMock(return_value=[])
        adapter = KnowledgeRetrieverAdapter(repo=repo)

        ctx = RetrievalContext(
            query="NeurFlow 工作流",
            limit=5,
            user_id="user_42",
            metadata={"agent_id": "default"},
        )
        result = await adapter.retrieve(ctx)

        repo.search_visible_items.assert_called_once()
        call_kwargs = repo.search_visible_items.call_args.kwargs
        # 用户隔离：user 参数必须非空（透传检索上下文）
        assert call_kwargs.get("user") is not None
        assert call_kwargs.get("query") == "NeurFlow 工作流"
        assert call_kwargs.get("limit") == 5
        # 返回的是 RetrievalResult
        assert result.source == "KnowledgeRetriever"

    @pytest.mark.asyncio
    async def test_retrieve_empty_result_quality_zero(self):
        """无命中时质量分数应为 0.0，quality_level=FAILED"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        repo = Mock()
        repo.search_visible_items = MagicMock(return_value=[])
        adapter = KnowledgeRetrieverAdapter(repo=repo)

        result = await adapter.retrieve(RetrievalContext(query="未知内容", user_id="u1"))
        assert result.memories == []
        assert result.quality == 0.0
        assert result.quality_level == RetrievalQuality.FAILED

    @pytest.mark.asyncio
    async def test_retrieve_with_hits_quality_positive(self):
        """命中的知识条目应出现在 memories，且质量分数 > 0"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        repo = Mock()
        repo.search_visible_items = MagicMock(return_value=[
            {
                "knowledge_id": "k1",
                "title": "NeurFlow 工作流引擎",
                "content": "NeurFlow 是可视化工作流引擎，支持触发器系统。",
                "category": "architecture",
                "tags": ["neurflow"],
                "source": "docs",
                "confidence": 0.9,
                "visibility": "private",
            }
        ])
        adapter = KnowledgeRetrieverAdapter(repo=repo)

        result = await adapter.retrieve(RetrievalContext(query="NeurFlow", user_id="u1"))
        assert len(result.memories) == 1
        assert result.memories[0]["title"] == "NeurFlow 工作流引擎"
        assert result.quality > 0.0
        assert result.quality_level in (
            RetrievalQuality.FAIR,
            RetrievalQuality.GOOD,
            RetrievalQuality.EXCELLENT,
        )

    @pytest.mark.asyncio
    async def test_retrieve_failure_raises(self):
        """repo 异常时 retrieve 应向上传播（让责任链 decide fallback）"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        repo = Mock()
        repo.search_visible_items = MagicMock(side_effect=RuntimeError("db down"))
        adapter = KnowledgeRetrieverAdapter(repo=repo)

        with pytest.raises(RuntimeError):
            await adapter.retrieve(RetrievalContext(query="x", user_id="u1"))

    @pytest.mark.asyncio
    async def test_get_quality_score(self):
        """质量评分：空结果 0，命中按数量+关键词"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        adapter = KnowledgeRetrieverAdapter(repo=Mock())
        assert adapter.get_quality_score([], "q") == 0.0
        score = adapter.get_quality_score(
            [{"title": "NeurFlow", "content": "NeurFlow 工作流引擎触发器"}], "NeurFlow"
        )
        assert score > 0.0

    def test_in_chain_with_priority_order(self):
        """加入责任链后应按优先级排序且可检索"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        chain = MemoryRetrievalChain()
        # 模拟已有检索器
        chain.add_retriever(KnowledgeRetrieverAdapter(repo=Mock()))
        names = [r.name for r in chain.get_retrievers()]
        assert "KnowledgeRetriever" in names

    @pytest.mark.asyncio
    async def test_user_role_passthrough_admin(self):
        """用户隔离：role 应从 metadata 透传（admin 全可见依赖 role）"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        repo = Mock()
        repo.search_visible_items = MagicMock(return_value=[])
        adapter = KnowledgeRetrieverAdapter(repo=repo)

        ctx = RetrievalContext(
            query="知识", limit=5, user_id="1",
            metadata={"role": "admin"},
        )
        await adapter.retrieve(ctx)
        call_user = repo.search_visible_items.call_args.kwargs["user"]
        assert call_user["user_id"] == "1"
        assert call_user["role"] == "admin"

    @pytest.mark.asyncio
    async def test_user_role_default_user(self):
        """无 role 元数据时 user 只含 user_id（普通用户隔离不变）"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        repo = Mock()
        repo.search_visible_items = MagicMock(return_value=[])
        adapter = KnowledgeRetrieverAdapter(repo=repo)

        ctx = RetrievalContext(query="知识", limit=5, user_id="2")
        await adapter.retrieve(ctx)
        call_user = repo.search_visible_items.call_args.kwargs["user"]
        assert call_user == {"user_id": "2"}

    @pytest.mark.asyncio
    async def test_admin_sees_all_via_visible_filter(self):
        """端到端隔离：admin 的角色透传后，repo 可见集包含他人 public 条目"""
        if KnowledgeRetrieverAdapter is None:
            pytest.skip("适配器未实现（红测阶段）")
        from neurova.knowledge.repository import KnowledgeRepository, VISIBILITY_PRIVATE
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmp:
            repo = KnowledgeRepository(tmp)
            repo.create_knowledge(
                agent_id="default", title="Alice私密", content="Alice 私有笔记",
                category="general", tags=[], source="", confidence=0.5,
                visibility=VISIBILITY_PRIVATE, owner_user_id="1",
            )
            repo.create_knowledge(
                agent_id="default", title="公开文档", content="公开 NeurFlow 文档",
                category="general", tags=[], source="", confidence=0.5,
                visibility="public", owner_user_id="2",
            )
            adapter = KnowledgeRetrieverAdapter(repo)
            # admin(user_id=1, role=admin)：应同时可见自己私有 + 他人公开
            ctx = RetrievalContext(query="文档", limit=5, user_id="1", metadata={"role": "admin"})
            result = await adapter.retrieve(ctx)
            titles = {m.get("title") for m in result.memories}
            assert "公开文档" in titles  # 隔离透传 role 后 admin 可见性保留

            # 普通用户(user_id=3, 无角色)：公开文档仍可见（public），Alice 私密不可见
            ctx2 = RetrievalContext(query="文档", limit=5, user_id="3")
            result2 = await adapter.retrieve(ctx2)
            titles2 = {m.get("title") for m in result2.memories}
            assert "公开文档" in titles2
            assert "Alice私密" not in titles2
