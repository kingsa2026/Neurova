"""
统一检索器 — TDD 测试

垂直切片：每个测试验证一个行为，逐步实现。
"""

import asyncio

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from typing import List, Dict, Any


# ── Tracer Bullet 1: UnifiedRetriever 初始化 ─────────────────────────────────

class TestUnifiedRetrieverInit:
    """UnifiedRetriever 可以正确初始化"""

    def test_init_with_engine_only(self):
        """只提供 CognitiveStorageEngine 时可以初始化"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        retriever = UnifiedRetriever(engine=engine)
        
        assert retriever.engine is engine
        assert retriever._moe is None
        assert retriever._recall is None
        assert retriever._hebb is None

    def test_init_with_all_retrievers(self):
        """提供所有旧检索器时可以初始化"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        moe = MagicMock()
        recall = MagicMock()
        hebb = MagicMock()
        
        retriever = UnifiedRetriever(
            engine=engine,
            moe_router=moe,
            recall_engine=recall,
            hebb_manager=hebb,
        )
        
        assert retriever.engine is engine
        assert retriever._moe is moe
        assert retriever._recall is recall
        assert retriever._hebb is hebb


# ── Tracer Bullet 2: retrieve() 基本功能 ──────────────────────────────────────

class TestUnifiedRetrieverRetrieve:
    """retrieve() 方法的基本功能"""

    def test_retrieve_returns_list(self):
        """retrieve() 返回列表"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        engine.retrieve.return_value = []
        
        retriever = UnifiedRetriever(engine=engine)
        result = asyncio.run(retriever.retrieve("test query"))
        
        assert isinstance(result, list)

    def test_retrieve_calls_engine(self):
        """retrieve() 调用 CognitiveStorageEngine.retrieve()"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine, UnifiedMemoryNode
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        mock_node = MagicMock()
        mock_node.id = "test-id"
        mock_node.content = "test content"
        mock_node.memory_type.value = "semantic"
        mock_node.temperature = 0.8
        mock_node.category = "general"
        mock_node.metadata = {}
        
        engine.retrieve.return_value = [mock_node]
        
        retriever = UnifiedRetriever(engine=engine)
        result = asyncio.run(retriever.retrieve("test query", limit=5))
        
        engine.retrieve.assert_called_once_with("test query", limit=5)
        assert len(result) == 1
        assert result[0]['id'] == "test-id"
        assert result[0]['content'] == "test content"


# ── Tracer Bullet 3: retrieve() 与 MoE 路由器集成 ─────────────────────────────

class TestUnifiedRetrieverMoE:
    """retrieve() 与 MoE 路由器集成"""

    def test_retrieve_calls_moe_when_provided(self):
        """当提供 MoE 路由器时，retrieve() 会调用它"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        engine.retrieve.return_value = []
        
        moe = MagicMock()
        moe.retrieve.return_value = [
            {"content": "moe result", "score": 0.9}
        ]
        
        retriever = UnifiedRetriever(engine=engine, moe_router=moe)
        result = asyncio.run(retriever.retrieve("test query"))
        
        moe.retrieve.assert_called_once()
        assert moe.retrieve.call_args.args[0] == "test query"
        assert any("moe result" in r.get("content", "") for r in result)

    def test_retrieve_does_not_call_moe_when_none(self):
        """当 MoE 路由器为 None 时，retrieve() 不调用它"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        engine.retrieve.return_value = []
        
        retriever = UnifiedRetriever(engine=engine, moe_router=None)
        # 应该不抛出异常
        result = asyncio.run(retriever.retrieve("test query"))
        assert isinstance(result, list)


# ── Tracer Bullet 4: retrieve() 与 RecallEngine 集成 ──────────────────────────

class TestUnifiedRetrieverRecall:
    """retrieve() 与 RecallEngine 集成"""

    def test_retrieve_calls_recall_when_provided(self):
        """当提供 RecallEngine 时，retrieve() 会调用它"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        engine.retrieve.return_value = []
        
        recall = MagicMock()
        recall.recall_flat.return_value = [
            {"content": "recall result", "score": 0.8}
        ]
        
        retriever = UnifiedRetriever(engine=engine, recall_engine=recall)
        result = asyncio.run(retriever.retrieve("test query", limit=5))
        
        recall.recall_flat.assert_called_once_with("test query", limit=5)
        assert any("recall result" in r.get('content', '') for r in result)

    def test_retrieve_does_not_call_recall_when_none(self):
        """当 RecallEngine 为 None 时，retrieve() 不调用它"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        engine.retrieve.return_value = []
        
        retriever = UnifiedRetriever(engine=engine, recall_engine=None)
        # 应该不抛出异常
        result = asyncio.run(retriever.retrieve("test query"))
        assert isinstance(result, list)


# ── Tracer Bullet 5: retrieve() 与 HebbManager 集成 ────────────────────────────

class TestUnifiedRetrieverHebb:
    """retrieve() 与 HebbManager 集成"""

    def test_retrieve_calls_hebb_when_provided(self):
        """当提供 HebbManager 时，retrieve() 会调用它"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        engine.retrieve.return_value = []
        
        hebb = MagicMock()
        mock_hebb = MagicMock()
        mock_hebb.content = "hebb result"
        hebb.retrieve_neurova_hebb.return_value = [mock_hebb]
        hebb.convert_to_recall_format.return_value = {"content": "hebb result", "score": 0.7}
        
        retriever = UnifiedRetriever(engine=engine, hebb_manager=hebb)
        result = asyncio.run(retriever.retrieve("test query"))
        
        hebb.retrieve_neurova_hebb.assert_called_once_with("test query")
        assert any("hebb result" in r.get('content', '') for r in result)

    def test_retrieve_does_not_call_hebb_when_none(self):
        """当 HebbManager 为 None 时，retrieve() 不调用它"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        engine.retrieve.return_value = []
        
        retriever = UnifiedRetriever(engine=engine, hebb_manager=None)
        # 应该不抛出异常
        result = asyncio.run(retriever.retrieve("test query"))
        assert isinstance(result, list)


# ── Tracer Bullet 6: _node_to_dict() 转换 ─────────────────────────────────────

class TestUnifiedRetrieverNodeToDict:
    """_node_to_dict() 正确转换 UnifiedMemoryNode 到字典"""

    def test_node_to_dict_conversion(self):
        """_node_to_dict() 返回正确的字典格式"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode, MemoryType,
        )
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        retriever = UnifiedRetriever(engine=engine)
        
        node = UnifiedMemoryNode(
            id="test-id",
            content="test content",
            memory_type=MemoryType.EPISODIC,
            category="conversation",
            temperature=0.75,
            metadata={"key": "value"},
        )
        
        result = retriever._node_to_dict(node)
        
        assert result['id'] == "test-id"
        assert result['content'] == "test content"
        assert result['score'] == 0.75
        assert result['source'] == "episodic"
        assert result['temperature'] == 0.75
        assert result['category'] == "conversation"
        assert result['metadata'] == {"key": "value"}


# ── Tracer Bullet 7: _dedup_rank() 去重排序 ──────────────────────────────────

class TestUnifiedRetrieverDedupRank:
    """_dedup_rank() 正确去重和排序"""

    def test_dedup_removes_duplicates(self):
        """_dedup_rank() 移除重复项"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        retriever = UnifiedRetriever(engine=engine)
        
        results = [
            {"content": "duplicate content", "score": 0.9},
            {"content": "duplicate content", "score": 0.8},  # 重复
            {"content": "unique content", "score": 0.7},
        ]
        
        deduped = retriever._dedup_rank(results, limit=10)
        
        assert len(deduped) == 2
        assert deduped[0]['content'] == "duplicate content"
        assert deduped[1]['content'] == "unique content"

    def test_dedup_sorts_by_score(self):
        """_dedup_rank() 按分数降序排序"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        retriever = UnifiedRetriever(engine=engine)
        
        results = [
            {"content": "low score", "score": 0.3},
            {"content": "high score", "score": 0.9},
            {"content": "medium score", "score": 0.6},
        ]
        
        sorted_results = retriever._dedup_rank(results, limit=10)
        
        assert sorted_results[0]['content'] == "high score"
        assert sorted_results[1]['content'] == "medium score"
        assert sorted_results[2]['content'] == "low score"

    def test_dedup_respects_limit(self):
        """_dedup_rank() 尊重 limit 参数"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        retriever = UnifiedRetriever(engine=engine)
        
        results = [
            {"content": f"result {i}", "score": 1.0 - i * 0.1}
            for i in range(10)
        ]
        
        limited = retriever._dedup_rank(results, limit=3)
        
        assert len(limited) == 3
        assert limited[0]['content'] == "result 0"
        assert limited[1]['content'] == "result 1"
        assert limited[2]['content'] == "result 2"


# ── Tracer Bullet 8: retrieve() 完整流程 ──────────────────────────────────────

class TestUnifiedRetrieverFullFlow:
    """retrieve() 完整流程测试"""

    def test_retrieve_integrates_all_sources(self):
        """retrieve() 整合所有数据源"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine, UnifiedMemoryNode
        
        # Mock engine
        engine = MagicMock(spec=CognitiveStorageEngine)
        mock_node = MagicMock()
        mock_node.id = "engine-id"
        mock_node.content = "engine content"
        mock_node.memory_type.value = "semantic"
        mock_node.temperature = 0.8
        mock_node.category = "general"
        mock_node.metadata = {}
        engine.retrieve.return_value = [mock_node]
        
        # Mock MoE
        moe = MagicMock()
        moe.retrieve.return_value = [
            {"content": "moe content", "score": 0.9}
        ]
        
        # Mock Recall
        recall = MagicMock()
        recall.recall_flat.return_value = [
            {"content": "recall content", "score": 0.7}
        ]
        
        # Mock Hebb
        hebb = MagicMock()
        mock_hebb = MagicMock()
        mock_hebb.content = "hebb content"
        hebb.retrieve_neurova_hebb.return_value = [mock_hebb]
        hebb.convert_to_recall_format.return_value = {"content": "hebb content", "score": 0.6}
        
        retriever = UnifiedRetriever(
            engine=engine,
            moe_router=moe,
            recall_engine=recall,
            hebb_manager=hebb,
        )
        
        result = asyncio.run(retriever.retrieve("test query", limit=10))
        
        # 验证所有数据源被调用
        engine.retrieve.assert_called_once()
        moe.retrieve.assert_called_once()
        recall.recall_flat.assert_called_once()
        hebb.retrieve_neurova_hebb.assert_called_once()
        
        # 验证结果去重
        assert len(result) <= 10
        contents = [r.get('content') for r in result]
        assert "engine content" in contents
        assert "moe content" in contents
        assert "recall content" in contents
        assert "hebb content" in contents