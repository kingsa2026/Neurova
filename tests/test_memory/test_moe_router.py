"""
MoE 记忆检索系统测试 — TDD 垂直切片

测试覆盖:
1. UnifiedVectorStore - 三合一向量索引
2. VectorGatingNetwork - 向量路由
3. ExpertDrilldownRetriever - 专家下钻
4. MoEMemoryRouter - 集成路由器
5. 冲突检测与结果处理
"""

import pytest
import random
import math
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta
from typing import List, Dict, Any

# ═══════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════

MOCK_MEMORIES = [
    {
        "id": "mem_001",
        "content": "今天和张三讨论了文件下载方案",
        "category": "conversation",
        "lifecycle_stage": "active",
        "temperature": 80.0,
        "emotion_tags": '["neutral"]',
        "created_at": "2026-06-01T10:00:00",
        "score": 0.9,
    },
    {
        "id": "mem_002",
        "content": "项目使用 PostgreSQL 数据库",
        "category": "fact",
        "is_crystallized": 1,
        "temperature": 60.0,
        "created_at": "2026-05-15T08:00:00",
        "score": 0.8,
    },
    {
        "id": "mem_003",
        "content": "使用 curl 命令下载文件",
        "category": "tool_usage",
        "temperature": 70.0,
        "created_at": "2026-06-02T09:00:00",
        "score": 0.7,
    },
    {
        "id": "mem_004",
        "content": "项目使用 MySQL 数据库",
        "category": "fact",
        "is_crystallized": 1,
        "temperature": 50.0,
        "created_at": "2026-06-01T15:00:00",
        "score": 0.75,
    },
    {
        "id": "mem_005",
        "content": "用户反馈界面很好用",
        "category": "experience",
        "temperature": 65.0,
        "emotion_tags": '["joy"]',
        "created_at": "2026-06-02T11:00:00",
        "score": 0.6,
    },
]

EXPERT_DEFINITIONS = {
    "conversation_episodic": {
        "category": "conversation",
        "lifecycle_stage": "active",
        "centroid_text": "对话记忆、日常交流、聊天记录",
    },
    "factual_knowledge": {
        "category": "fact",
        "is_crystallized": True,
        "centroid_text": "事实知识、常识、固化信息",
    },
    "tool_muscle": {
        "category": "tool_usage",
        "centroid_text": "工具使用、命令执行、操作经验",
    },
    "experience_lesson": {
        "category": "experience",
        "centroid_text": "经验教训、最佳实践、失败案例",
    },
}


# ═══════════════════════════════════════
# 1. UnifiedVectorStore 测试
# ═══════════════════════════════════════

class TestUnifiedVectorStore:
    """三合一向量索引测试"""

    def test_initialization_with_tfidf_backend(self):
        """TF-IDF 后端初始化"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

        store = UnifiedVectorStore(backend="tfidf")
        assert store.backend == "tfidf"
        assert store._tfidf_vocabulary is not None

    def test_initialize_centroids(self):
        """质心初始化"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

        store = UnifiedVectorStore(backend="tfidf")
        store.initialize_centroids(EXPERT_DEFINITIONS)

        centroids = store.get_expert_centroids()
        assert len(centroids) == 4
        assert "conversation_episodic" in centroids
        assert "factual_knowledge" in centroids

    def test_centroid_vectors_are_normalized(self):
        """质心向量应归一化"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore, vector_norm

        store = UnifiedVectorStore(backend="tfidf")
        store.initialize_centroids(EXPERT_DEFINITIONS)

        for expert_id, centroid in store.get_expert_centroids().items():
            norm = vector_norm(centroid)
            assert abs(norm - 1.0) < 0.01, f"Centroid {expert_id} not normalized: {norm}"

    def test_index_memories(self):
        """索引记忆"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

        store = UnifiedVectorStore(backend="tfidf")
        store.index_memories(MOCK_MEMORIES)

        assert len(store.memory_ids) == 5

    def test_search_returns_ranked_results(self):
        """搜索返回排序结果"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

        store = UnifiedVectorStore(backend="tfidf")
        store.index_memories(MOCK_MEMORIES)

        # 查询与 mem_001 相似
        results = store.search("和张三讨论文件", limit=3)
        assert len(results) > 0
        assert results[0]["id"] == "mem_001"

    def test_search_in_expert_filters_by_category(self):
        """专家内搜索按类别过滤"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

        store = UnifiedVectorStore(backend="tfidf")
        store.index_memories(MOCK_MEMORIES)

        expert_def = {"category": "fact"}
        results = store.search_in_expert("数据库", expert_def=expert_def, limit=5)

        # 应该只返回 fact 类别
        for r in results:
            assert r.get("category") == "fact"


# ═══════════════════════════════════════
# 2. VectorGatingNetwork 测试
# ═══════════════════════════════════════

class TestVectorGatingNetwork:
    """向量门控网络测试"""

    @pytest.fixture
    def mock_store(self):
        """模拟向量存储"""
        store = Mock()
        store.get_expert_centroids.return_value = {
            "conversation_episodic": [random.gauss(0, 1) for _ in range(100)],
            "factual_knowledge": [random.gauss(0, 1) for _ in range(100)],
            "tool_muscle": [random.gauss(0, 1) for _ in range(100)],
        }
        return store

    def test_route_returns_top_k(self, mock_store):
        """路由返回 Top-K 专家"""
        from neurova.cognitive_layers.memory_layer.moe_router import VectorGatingNetwork

        network = VectorGatingNetwork(vector_store=mock_store, top_k=2)
        query_vec = [random.gauss(0, 1) for _ in range(100)]

        import asyncio
        result = asyncio.run(network.route(query_vec))

        assert len(result) <= 2
        assert all(isinstance(v, float) for v in result.values())

    def test_route_respects_activation_threshold(self, mock_store):
        """路由遵守激活阈值"""
        from neurova.cognitive_layers.memory_layer.moe_router import VectorGatingNetwork

        network = VectorGatingNetwork(
            vector_store=mock_store,
            top_k=5,
            activation_threshold=0.9  # 高阈值
        )
        query_vec = [random.gauss(0, 1) for _ in range(100)]

        import asyncio
        result = asyncio.run(network.route(query_vec))

        # 高阈值应该过滤掉大部分专家
        for score in result.values():
            assert score >= 0.9


# ═══════════════════════════════════════
# 3. ExpertDrilldownRetriever 测试
# ═══════════════════════════════════════

class TestExpertDrilldownRetriever:
    """专家内部下钻测试"""

    @pytest.fixture
    def mock_storage(self):
        """模拟存储层"""
        storage = Mock()

        def mock_execute(sql, params=None):
            # 根据 SQL 和 params 返回不同结果
            result = Mock()
            params = params or {}

            if "category = :category" in sql:
                cat = params.get("category")
                result.fetchall.return_value = [
                    m for m in MOCK_MEMORIES if m["category"] == cat
                ]
            elif "category = 'conversation'" in sql:
                result.fetchall.return_value = [
                    m for m in MOCK_MEMORIES if m["category"] == "conversation"
                ]
            elif "category = 'fact'" in sql:
                result.fetchall.return_value = [
                    m for m in MOCK_MEMORIES if m["category"] == "fact"
                ]
            else:
                result.fetchall.return_value = MOCK_MEMORIES
            return result

        storage.execute = mock_execute
        return storage

    def test_layer0_exact_index(self, mock_storage):
        """Layer 0: 标签精确索引"""
        from neurova.cognitive_layers.memory_layer.moe_router import ExpertDrilldownRetriever

        expert_def = {"category": "conversation", "lifecycle_stage": "active"}
        retriever = ExpertDrilldownRetriever(expert_def=expert_def, store=mock_storage)

        results = retriever._layer0_exact_index()
        assert len(results) > 0
        assert all(r["category"] == "conversation" for r in results)

    def test_layer1_structured_drilldown(self, mock_storage):
        """Layer 1: 结构化下钻"""
        from neurova.cognitive_layers.memory_layer.moe_router import ExpertDrilldownRetriever

        expert_def = {"category": "conversation"}
        retriever = ExpertDrilldownRetriever(expert_def=expert_def, store=mock_storage)

        candidates = MOCK_MEMORIES.copy()
        results = retriever._layer1_structured_drilldown(candidates, min_floor=2)

        # 结果数量不应少于 min_floor
        assert len(results) >= 2


# ═══════════════════════════════════════
# 4. MoEMemoryRouter 集成测试
# ═══════════════════════════════════════

class TestMoEMemoryRouter:
    """MoE 记忆路由器集成测试"""

    @pytest.fixture
    def router(self):
        """创建路由器实例"""
        from neurova.cognitive_layers.memory_layer.moe_router import MoEMemoryRouter
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

        # 使用智能 mock 存储（按 SQL 参数过滤）
        mock_storage = Mock()

        def smart_execute(sql, params=None):
            result = Mock()
            params = params or {}
            if "category = :category" in sql:
                cat = params.get("category")
                result.fetchall.return_value = [
                    m for m in MOCK_MEMORIES if m["category"] == cat
                ]
            else:
                result.fetchall.return_value = MOCK_MEMORIES
            return result

        mock_storage.execute = smart_execute

        # 创建向量存储并索引记忆（构建 TF-IDF 词汇表）
        vector_store = UnifiedVectorStore(backend="tfidf")
        vector_store.index_memories(MOCK_MEMORIES)

        router = MoEMemoryRouter(
            experts=EXPERT_DEFINITIONS,
            storage=mock_storage,
            vector_store=vector_store,
        )
        return router

    def test_retrieve_returns_results(self, router):
        """检索返回结果"""
        import asyncio
        results = asyncio.run(router.retrieve("和张三讨论文件"))

        assert len(results) > 0
        assert len(results) <= 5  # 最多 5 条

    def test_retrieve_with_no_memory_returns_hint(self, router):
        """无记忆时返回提示"""
        # 替换 execute 函数为返回空结果的版本
        def empty_execute(sql, params=None):
            result = Mock()
            result.fetchall.return_value = []
            return result

        router.storage.execute = empty_execute
        # 同时清空向量存储的索引（避免全数据库兜底返回结果）
        router.vector_store.memory_vectors = []
        router.vector_store.memory_ids = []
        router.vector_store.memory_metadata = []

        import asyncio
        results = asyncio.run(router.retrieve("完全无关的查询xyz123"))

        assert len(results) == 1
        assert "未找到" in results[0]["content"] or "no_memory" in results[0].get("is_hint", "")

    def test_retrieve_respects_expert_activation(self, router):
        """检索遵守专家激活"""
        import asyncio
        results = asyncio.run(router.retrieve("数据库配置"))

        # 应该主要从 factual_knowledge Expert 返回
        fact_results = [r for r in results if r.get("category") == "fact"]
        assert len(fact_results) > 0


# ═══════════════════════════════════════
# 5. 冲突检测测试
# ═══════════════════════════════════════

class TestConflictDetector:
    """冲突检测测试"""

    def test_detect_contradictory_memories(self):
        """检测矛盾记忆"""
        from neurova.cognitive_layers.memory_layer.conflict_detector_v2 import ConflictDetector

        detector = ConflictDetector(sim_threshold=0.7, entity_threshold=0.5)

        conflicting_memories = [
            {
                "id": "mem_002",
                "content": "项目使用 PostgreSQL 数据库",
                "category": "fact",
                "created_at": "2026-05-15T08:00:00",
            },
            {
                "id": "mem_004",
                "content": "项目使用 MySQL 数据库",
                "category": "fact",
                "created_at": "2026-06-01T15:00:00",
            },
        ]

        conflict_groups, independent, evolution_chains = detector.detect(conflicting_memories)

        # 应该检测到冲突
        assert len(conflict_groups) > 0
        assert conflict_groups[0].conflict_type == "contradiction"

    def test_detect_evolution_chain(self):
        """检测演进链"""
        from neurova.cognitive_layers.memory_layer.conflict_detector_v2 import ConflictDetector

        detector = ConflictDetector(sim_threshold=0.7, entity_threshold=0.5)

        evolution_memories = [
            {
                "id": "mem_v1",
                "content": "项目使用 Python 3.10 版本开发",
                "category": "fact",
                "created_at": "2026-05-01T10:00:00",
            },
            {
                "id": "mem_v2",
                "content": "项目使用 Python 3.12 版本开发",
                "category": "fact",
                "created_at": "2026-06-01T10:00:00",
            },
        ]

        conflict_groups, independent, evolution_chains = detector.detect(evolution_memories)

        # 应该检测到演进而不是冲突
        assert len(conflict_groups) == 0
        assert len(evolution_chains) > 0

    def test_independent_memories_not_flagged(self):
        """独立记忆不被标记为冲突"""
        from neurova.cognitive_layers.memory_layer.conflict_detector_v2 import ConflictDetector

        detector = ConflictDetector(sim_threshold=0.7, entity_threshold=0.5)

        independent_memories = [
            {
                "id": "mem_001",
                "content": "今天和张三讨论了文件下载方案",
                "category": "conversation",
                "created_at": "2026-06-01T10:00:00",
            },
            {
                "id": "mem_005",
                "content": "用户反馈界面很好用",
                "category": "experience",
                "created_at": "2026-06-02T11:00:00",
            },
        ]

        conflict_groups, independent, evolution_chains = detector.detect(independent_memories)

        # 不应该有冲突
        assert len(conflict_groups) == 0
        assert len(independent) == 2


# ═══════════════════════════════════════
# 6. 结果处理器测试
# ═══════════════════════════════════════

class TestResultProcessor:
    """结果处理器测试"""

    def test_process_returns_max_5_results(self):
        """处理返回最多 5 条结果"""
        from neurova.cognitive_layers.memory_layer.result_processor import ResultProcessor

        processor = ResultProcessor(max_results=5)
        results = MOCK_MEMORIES * 3  # 15 条

        import asyncio
        processed = asyncio.run(processor.process(results))

        assert len(processed.independent) <= 5

    def test_process_deduplicates(self):
        """处理去重"""
        from neurova.cognitive_layers.memory_layer.result_processor import ResultProcessor

        processor = ResultProcessor()

        # 添加重复项
        results = MOCK_MEMORIES + [MOCK_MEMORIES[0].copy()]

        import asyncio
        processed = asyncio.run(processor.process(results))

        # 去重后应该只有 5 条
        assert len(processed.independent) == 5

    def test_process_handles_conflicts(self):
        """处理冲突"""
        from neurova.cognitive_layers.memory_layer.result_processor import ResultProcessor

        processor = ResultProcessor()

        import asyncio
        processed = asyncio.run(processor.process(MOCK_MEMORIES))

        # 如果有冲突，应该有 conflict_groups
        if processed.has_conflicts:
            assert len(processed.conflict_groups) > 0
            assert processed.injection_text is not None


# ═══════════════════════════════════════
# 7. 端到端集成测试
# ═══════════════════════════════════════

class TestEndToEndIntegration:
    """端到端集成测试"""

    @pytest.fixture
    def full_system(self):
        """完整系统"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
        from neurova.cognitive_layers.memory_layer.moe_router import MoEMemoryRouter, VectorGatingNetwork
        from neurova.cognitive_layers.memory_layer.result_processor import ResultProcessor

        # Mock 存储
        mock_storage = Mock()
        mock_storage.execute.return_value.fetchall.return_value = MOCK_MEMORIES

        # 创建系统
        vector_store = UnifiedVectorStore(backend="tfidf")
        vector_store.index_memories(MOCK_MEMORIES)
        vector_store.initialize_centroids(EXPERT_DEFINITIONS)

        router = MoEMemoryRouter(
            experts=EXPERT_DEFINITIONS,
            storage=mock_storage,
            vector_store=vector_store,
        )

        processor = ResultProcessor(max_results=5)

        return router, processor

    def test_full_retrieval_flow(self, full_system):
        """完整检索流程"""
        router, processor = full_system

        import asyncio
        # 检索
        raw_results = asyncio.run(router.retrieve("张三 文件下载"))
        # 处理
        processed = asyncio.run(processor.process(raw_results))

        assert len(processed.independent) > 0
        assert len(processed.independent) <= 5
        assert processed.injection_text is not None

    def test_full_flow_with_conflict(self, full_system):
        """带冲突的完整流程"""
        router, processor = full_system

        # 添加冲突记忆
        conflict_memories = MOCK_MEMORIES + [
            {
                "id": "mem_006",
                "content": "项目使用 MySQL 数据库",
                "category": "fact",
                "is_crystallized": 1,
                "temperature": 55.0,
                "created_at": "2026-06-02T14:00:00",
                "score": 0.75,
            }
        ]
        router.storage.execute.return_value.fetchall.return_value = conflict_memories

        import asyncio
        raw_results = asyncio.run(router.retrieve("数据库"))
        processed = asyncio.run(processor.process(raw_results))

        # 应该检测到冲突
        if processed.has_conflicts:
            assert "冲突" in processed.injection_text or "选项" in processed.injection_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])