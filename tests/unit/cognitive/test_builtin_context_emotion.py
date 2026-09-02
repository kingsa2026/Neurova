"""
测试 builtin:context 和 builtin:emotion 节点修复

验证：
1. exec_context 从 ctx 获取 context_pool 并正确调用 get_contexts()
2. exec_emotion 从 ctx 获取 emotion_module 并正确调用 analyze_text_emotion()
3. exec_memory_load/exec_memory_save 从 ctx 获取 memory_manager
4. ResolutionContext 外部系统引用正确传递到节点执行上下文
"""
import json
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

from neurova.context_pool import ContextSource, ContextInput


# ============================================================
# 辅助：构造 mock 对象
# ============================================================


@dataclass
class MockEmotionState:
    primary_emotion: Any
    intensity: float = 0.5
    valence: float = 0.0
    arousal: float = 0.5
    secondary_emotions: Dict[Any, float] = field(default_factory=dict)


def _make_context_pool():
    pool = MagicMock()
    pool.get_contexts.return_value = [
        ContextInput(source=ContextSource.MEMORY, content="记得开会", priority=80, tokens=20),
        ContextInput(source=ContextSource.EMOTION, content="开心", priority=60, tokens=10),
        ContextInput(source=ContextSource.CONVERSATION, content="用户问天气", priority=40, tokens=15),
    ]
    return pool


def _make_emotion_module():
    module = MagicMock()
    joy_type = MagicMock()
    joy_type.value = "joy"
    emotion_state = MockEmotionState(
        primary_emotion=joy_type,
        intensity=0.8,
        valence=0.7,
        arousal=0.6,
        secondary_emotions={},
    )
    # exec_emotion 的 analyze_fn 优先 analyze、退化 analyze_text_emotion——
    # MagicMock 会自动补全 analyze 属性，必须显式预置同返回值
    module.analyze_text_emotion.return_value = emotion_state
    module.analyze.return_value = emotion_state
    module.get_emotional_memories.return_value = ["mem_001", "mem_002"]
    module.get_emotion.return_value = MockEmotionState(
        primary_emotion=joy_type,
        intensity=0.9,
        valence=0.8,
        arousal=0.7,
    )
    return module


def _make_memory_manager():
    manager = MagicMock()
    manager.search.return_value = [
        {"content": "记忆1", "importance": 0.8},
        {"content": "记忆2", "importance": 0.5},
    ]
    manager.remember.return_value = "mem_new_001"
    return manager


# ============================================================
# exec_context 测试
# ============================================================

class TestExecContext:
    """测试 builtin:context 节点执行器"""

    @pytest.mark.asyncio
    async def test_skip_when_no_context_pool_in_ctx(self):
        """当 ctx 中无 context_pool 时返回 failed"""
        from neurova.collaboration.neurflow.builtin import exec_context
        result = await exec_context({}, {})
        assert result["status"] == "failed"
        assert "context_pool" in result["error"]

    @pytest.mark.asyncio
    async def test_get_all_contexts(self):
        """获取所有上下文"""
        from neurova.collaboration.neurflow.builtin import exec_context
        pool = _make_context_pool()
        result = await exec_context(
            {"sources": '["memory", "emotion", "conversation"]', "token_budget": 4096},
            {"context_pool": pool},
        )

        assert result["status"] == "success"
        assert len(result["output"]) == 3
        pool.get_contexts.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_by_source(self):
        """按来源过滤"""
        from neurova.collaboration.neurflow.builtin import exec_context
        pool = _make_context_pool()
        result = await exec_context(
            {"sources": '["memory"]', "token_budget": 4096},
            {"context_pool": pool},
        )

        assert result["status"] == "success"
        assert len(result["output"]) == 1
        assert result["output"][0]["source"] == "memory"

    @pytest.mark.asyncio
    async def test_token_budget_limit(self):
        """Token 预算截断"""
        from neurova.collaboration.neurflow.builtin import exec_context
        pool = _make_context_pool()
        # 设置很大的 tokens 使 budget 只能容纳一个
        pool.get_contexts.return_value = [
            ContextInput(source=ContextSource.MEMORY, content="长文本" * 100, priority=80, tokens=2000),
            ContextInput(source=ContextSource.EMOTION, content="情感", priority=60, tokens=2000),
        ]
        result = await exec_context(
            {"sources": '["memory", "emotion"]', "token_budget": 2500},
            {"context_pool": pool},
        )

        assert result["status"] == "success"
        assert len(result["output"]) == 1  # 第二个超出预算
        assert result["metadata"]["total_tokens"] <= 2500

    @pytest.mark.asyncio
    async def test_sources_as_list(self):
        """sources 传入列表格式"""
        from neurova.collaboration.neurflow.builtin import exec_context
        pool = _make_context_pool()
        result = await exec_context(
            {"sources": ["memory"], "token_budget": 4096},
            {"context_pool": pool},
        )

        assert result["status"] == "success"
        assert len(result["output"]) == 1

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """异常处理：新式接口抛错会回退旧式 get_context——两条路径都炸才 failed"""
        from neurova.collaboration.neurflow.builtin import exec_context
        pool = _make_context_pool()
        pool.get_contexts.side_effect = RuntimeError("DB error")
        pool.get_context.side_effect = RuntimeError("DB error too")

        result = await exec_context({}, {"context_pool": pool})
        assert result["status"] == "failed"
        assert "DB error" in result["error"]


# ============================================================
# exec_emotion 测试
# ============================================================

class TestExecEmotion:
    """测试 builtin:emotion 节点执行器"""

    @pytest.mark.asyncio
    async def test_skip_when_no_emotion_module_in_ctx(self):
        """当 ctx 中无 emotion_module 时返回 failed"""
        from neurova.collaboration.neurflow.builtin import exec_emotion
        result = await exec_emotion({}, {})
        assert result["status"] == "failed"
        assert "emotion_module" in result["error"]

    @pytest.mark.asyncio
    async def test_analyze_mode(self):
        """analyze 模式：分析文本情感"""
        from neurova.collaboration.neurflow.builtin import exec_emotion
        module = _make_emotion_module()
        result = await exec_emotion(
            {"text": "我今天很开心", "mode": "analyze"},
            {"emotion_module": module},
        )

        assert result["status"] == "success"
        assert result["output"]["primary_emotion"] == "joy"
        assert result["output"]["intensity"] == 0.8
        module.analyze.assert_called_once_with("我今天很开心")

    @pytest.mark.asyncio
    async def test_query_mode(self):
        """query 模式：查询情感记忆"""
        from neurova.collaboration.neurflow.builtin import exec_emotion
        module = _make_emotion_module()
        result = await exec_emotion(
            {"text": "", "mode": "query", "min_intensity": 0.3, "limit": 5},
            {"emotion_module": module},
        )

        assert result["status"] == "success"
        assert result["output"] == ["mem_001", "mem_002"]

    @pytest.mark.asyncio
    async def test_state_mode(self):
        """state 模式：获取记忆情感状态"""
        from neurova.collaboration.neurflow.builtin import exec_emotion
        module = _make_emotion_module()
        result = await exec_emotion(
            {"mode": "state", "memory_id": "mem_001"},
            {"emotion_module": module},
        )

        assert result["status"] == "success"
        assert result["output"]["primary_emotion"] == "joy"
        module.get_emotion.assert_called_once_with("mem_001")

    @pytest.mark.asyncio
    async def test_state_mode_no_memory_id(self):
        """state 模式缺少 memory_id"""
        from neurova.collaboration.neurflow.builtin import exec_emotion
        module = _make_emotion_module()
        result = await exec_emotion(
            {"mode": "state"},
            {"emotion_module": module},
        )

        assert result["status"] == "failed"
        assert "memory_id" in result["error"]

    @pytest.mark.asyncio
    async def test_unknown_mode(self):
        """未知模式"""
        from neurova.collaboration.neurflow.builtin import exec_emotion
        module = _make_emotion_module()
        result = await exec_emotion(
            {"mode": "unknown"},
            {"emotion_module": module},
        )

        assert result["status"] == "failed"
        assert "未知模式" in result["error"]

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """异常处理"""
        from neurova.collaboration.neurflow.builtin import exec_emotion
        module = _make_emotion_module()
        module.analyze.side_effect = RuntimeError("分析失败")

        result = await exec_emotion(
            {"text": "test", "mode": "analyze"},
            {"emotion_module": module},
        )
        assert result["status"] == "failed"
        assert "分析失败" in result["error"]


# ============================================================
# exec_memory_load / exec_memory_save 测试
# ============================================================

class TestExecMemoryNodes:
    """测试 builtin:memory-load 和 builtin:memory-save 节点"""

    @pytest.mark.asyncio
    async def test_memory_load_uses_ctx_first(self):
        """memory_load 优先使用 ctx 中的 memory_manager"""
        from neurova.collaboration.neurflow.builtin import exec_memory_load
        manager = _make_memory_manager()
        result = await exec_memory_load(
            {"query": "开会", "limit": 2},
            {"memory_manager": manager},
        )

        assert result["status"] == "success"
        manager.search.assert_called_once_with("开会", limit=2)

    @pytest.mark.asyncio
    async def test_memory_save_uses_ctx_first(self):
        """memory_save 优先使用 ctx 中的 memory_manager"""
        from neurova.collaboration.neurflow.builtin import exec_memory_save
        manager = _make_memory_manager()
        result = await exec_memory_save(
            {"content": "新记忆", "importance": 0.9},
            {"memory_manager": manager},
        )

        assert result["status"] == "success"
        manager.remember.assert_called_once()

    @pytest.mark.asyncio
    async def test_memory_load_skip_when_no_manager(self):
        """memory_load 无 manager 时返回 failed"""
        from neurova.collaboration.neurflow.builtin import exec_memory_load
        result = await exec_memory_load({"query": "test"}, {})
        assert result["status"] == "failed"


# ============================================================
# ResolutionContext → 节点上下文传递测试
# ============================================================

class TestContextPropagation:
    """测试 ResolutionContext 外部系统引用正确传递到节点"""

    @pytest.mark.asyncio
    async def test_node_context_includes_external_refs(self):
        """验证 execution_engine 将外部系统引用传入节点 context"""
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowStatus
        )

        now = time.time()
        start_node = WorkflowNode(
            id="start", type="builtin:start",
            position={"x": 0, "y": 0}, config={},
        )
        workflow = WorkflowDefinition(
            id="wf_test", name="Test", description="test", version="1.0.0",
            nodes=[start_node],
            edges=[], variables=[], tags=[], category="general",
            author="test", created_at=now, updated_at=now,
            status=WorkflowStatus.DRAFT,
        )

        mock_memory = MagicMock()
        mock_context = _make_context_pool()
        mock_emotion = _make_emotion_module()

        # 构造 mock validation result
        mock_validation = MagicMock()
        mock_validation.is_valid = True
        mock_validation.errors = []

        with patch("neurova.collaboration.neurflow.execution_engine.get_node_registry") as mock_nr, \
             patch("neurova.collaboration.neurflow.execution_engine.get_variable_resolver") as mock_vr, \
             patch("neurova.collaboration.neurflow.execution_engine.get_dag_validator") as mock_dv:
            mock_nr.return_value.ensure_builtin = MagicMock()
            mock_dv.return_value.validate.return_value = mock_validation
            mock_dv.return_value.get_execution_path.return_value = ["start"]
            mock_vr.return_value.resolve_config.return_value = {}
            executor = WorkflowExecutor()

            # 捕获 _execute_node 的 context 参数
            captured_ctx = {}
            original_execute_node = executor._execute_node

            async def spy_execute_node(node, config, context):
                captured_ctx.update(context)
                return await original_execute_node(node, config, context)

            executor._execute_node = spy_execute_node

            await executor.execute(
                workflow, {},
                memory_manager=mock_memory,
                context_pool=mock_context,
                emotion_module=mock_emotion,
            )

            assert captured_ctx.get("memory_manager") is mock_memory
            assert captured_ctx.get("context_pool") is mock_context
            assert captured_ctx.get("emotion_module") is mock_emotion
            assert "variable_resolver" in captured_ctx
            assert "resolution_context" in captured_ctx
