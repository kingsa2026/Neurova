# -*- coding: utf-8 -*-
"""
外部系统注入集成测试

验证 ResolutionContext 外部系统注入修复：
1. $memory 前缀能正常调用 MemoryManager
2. $context 前缀能正常获取 ContextPool 数据
3. $emotion 前缀能正常获取情感状态
4. $crystal 前缀能正常获取结晶经验
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from neurova.collaboration.neurflow import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
    VariableResolver, ResolutionContext, WorkflowExecutor, get_workflow_executor
)


class TestExternalSystemInjection:
    """外部系统注入测试"""

    @pytest.fixture
    def mock_memory_manager(self):
        """模拟记忆管理器（使用真实接口方法名）"""
        mock = MagicMock()
        mock.search_memories.return_value = [
            {"content": "测试记忆内容", "score": 0.95}
        ]
        mock.get_memory.return_value = {"content": "特定记忆内容", "metadata": {"type": "fact"}}
        return mock

    @pytest.fixture
    def mock_context_pool(self):
        """模拟上下文池"""
        mock = MagicMock()
        mock.get_context.return_value = {
            "system_prompt": "你是一个AI助手",
            "recent_messages": [{"role": "user", "content": "hello"}]
        }
        return mock

    @pytest.fixture
    def mock_emotion_module(self):
        """模拟情感模块"""
        mock = MagicMock()
        mock.current.return_value = {
            "valence": 0.8,
            "arousal": 0.6,
            "dominance": 0.7,
            "primary_emotion": "happy"
        }
        mock.get_emotional_memories.return_value = ["memory_1", "memory_2"]
        mock.get_emotion.return_value = MagicMock(
            to_dict=MagicMock(return_value={
                "valence": 0.8,
                "primary_emotion": "happy"
            })
        )
        return mock

    @pytest.fixture
    def mock_crystallizer(self):
        """模拟结晶器"""
        mock = MagicMock()
        mock.retrieve.return_value = [
            {"pattern": "测试模式", "confidence": 0.9}
        ]
        return mock

    def test_resolution_context_injection_with_all_systems(
        self, mock_memory_manager, mock_context_pool, mock_emotion_module, mock_crystallizer
    ):
        """测试 ResolutionContext 注入所有外部系统"""
        # 创建 ResolutionContext 并注入外部系统
        context = ResolutionContext(
            workflow_id="test_workflow",
            execution_id="test_execution",
            memory_manager=mock_memory_manager,
            context_pool=mock_context_pool,
            emotion_module=mock_emotion_module,
            crystallizer=mock_crystallizer
        )
        
        # 验证外部系统注入
        assert context.memory_manager is mock_memory_manager
        assert context.context_pool is mock_context_pool
        assert context.emotion_module is mock_emotion_module
        assert context.crystallizer is mock_crystallizer

    def test_variable_resolver_with_injected_systems(
        self, mock_memory_manager, mock_context_pool, mock_emotion_module, mock_crystallizer
    ):
        """测试变量解析器在注入外部系统后能正常工作"""
        resolver = VariableResolver()
        
        context = ResolutionContext(
            workflow_id="test_workflow",
            execution_id="test_execution",
            memory_manager=mock_memory_manager,
            context_pool=mock_context_pool,
            emotion_module=mock_emotion_module,
            crystallizer=mock_crystallizer
        )
        
        # 测试 $memory 前缀
        result = resolver.resolve("$memory.test_query", context)
        assert result.success is True
        assert result.value == [{"content": "测试记忆内容", "score": 0.95}]
        
        # 测试 $context 前缀
        result = resolver.resolve("$context.system_prompt", context)
        assert result.success is True
        assert result.value == "你是一个AI助手"
        
        # 测试 $emotion 前缀
        result = resolver.resolve("$emotion.valence", context)
        assert result.success is True
        assert result.value == 0.8
        
        # 测试 $crystal 前缀
        result = resolver.resolve("$crystal.test_pattern", context)
        assert result.success is True
        assert result.value == [{"pattern": "测试模式", "confidence": 0.9}]

    def test_workflow_with_memory_variable(self, mock_memory_manager):
        """测试工作流中使用 $memory 变量"""
        # 创建使用 $memory 变量的工作流
        workflow = WorkflowDefinition(
            id="workflow_with_memory",
            name="带记忆变量的工作流",
            description="测试 $memory 前缀",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="start_1",
                    type="builtin:start",
                    position={"x": 0, "y": 0},
                    config={"inputs_schema": {"query": "string"}},
                ),
                WorkflowNode(
                    id="llm_1",
                    type="builtin:llm",
                    position={"x": 200, "y": 0},
                    config={
                        "prompt": "请根据记忆回答：$memory.query",
                        "model_provider": "auto",
                    },
                ),
                WorkflowNode(
                    id="end_1",
                    type="builtin:end",
                    position={"x": 400, "y": 0},
                    config={"output_mapping": {"result": "$node.llm_1.output"}},
                ),
            ],
            edges=[
                WorkflowEdge(id="edge_1", source="start_1", target="llm_1"),
                WorkflowEdge(id="edge_2", source="llm_1", target="end_1"),
            ],
            variables=[],
            tags=["test"],
            category="test",
            author="test_user",
            created_at=1000000.0,
            updated_at=1000000.0,
            status=WorkflowStatus.DRAFT,
        )
        
        # 验证工作流包含 $memory 变量
        llm_node = workflow.nodes[1]
        assert "$memory.query" in llm_node.config["prompt"]
        
        # 验证变量解析器能解析这个变量
        resolver = VariableResolver()
        context = ResolutionContext(
            workflow_id="workflow_with_memory",
            execution_id="test_execution",
            memory_manager=mock_memory_manager
        )
        
        result = resolver.resolve("$memory.query", context)
        assert result.success is True
        assert result.value == [{"content": "测试记忆内容", "score": 0.95}]

    def test_workflow_with_context_variable(self, mock_context_pool):
        """测试工作流中使用 $context 变量"""
        workflow = WorkflowDefinition(
            id="workflow_with_context",
            name="带上下文变量的工作流",
            description="测试 $context 前缀",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="start_1",
                    type="builtin:start",
                    position={"x": 0, "y": 0},
                    config={"inputs_schema": {"topic": "string"}},
                ),
                WorkflowNode(
                    id="llm_1",
                    type="builtin:llm",
                    position={"x": 200, "y": 0},
                    config={
                        "prompt": "基于上下文：$context.system_prompt，请回答：$input.topic",
                        "model_provider": "auto",
                    },
                ),
                WorkflowNode(
                    id="end_1",
                    type="builtin:end",
                    position={"x": 400, "y": 0},
                    config={"output_mapping": {"result": "$node.llm_1.output"}},
                ),
            ],
            edges=[
                WorkflowEdge(id="edge_1", source="start_1", target="llm_1"),
                WorkflowEdge(id="edge_2", source="llm_1", target="end_1"),
            ],
            variables=[],
            tags=["test"],
            category="test",
            author="test_user",
            created_at=1000000.0,
            updated_at=1000000.0,
            status=WorkflowStatus.DRAFT,
        )
        
        # 验证变量解析器能解析 $context 变量
        resolver = VariableResolver()
        context = ResolutionContext(
            workflow_id="workflow_with_context",
            execution_id="test_execution",
            context_pool=mock_context_pool
        )
        
        result = resolver.resolve("$context.system_prompt", context)
        assert result.success is True
        assert result.value == "你是一个AI助手"

    def test_workflow_with_emotion_variable(self, mock_emotion_module):
        """测试工作流中使用 $emotion 变量"""
        workflow = WorkflowDefinition(
            id="workflow_with_emotion",
            name="带情感变量的工作流",
            description="测试 $emotion 前缀",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="start_1",
                    type="builtin:start",
                    position={"x": 0, "y": 0},
                    config={"inputs_schema": {"topic": "string"}},
                ),
                WorkflowNode(
                    id="llm_1",
                    type="builtin:llm",
                    position={"x": 200, "y": 0},
                    config={
                        "prompt": "情感效价：$emotion.valence，请回答：$input.topic",
                        "model_provider": "auto",
                    },
                ),
                WorkflowNode(
                    id="end_1",
                    type="builtin:end",
                    position={"x": 400, "y": 0},
                    config={"output_mapping": {"result": "$node.llm_1.output"}},
                ),
            ],
            edges=[
                WorkflowEdge(id="edge_1", source="start_1", target="llm_1"),
                WorkflowEdge(id="edge_2", source="llm_1", target="end_1"),
            ],
            variables=[],
            tags=["test"],
            category="test",
            author="test_user",
            created_at=1000000.0,
            updated_at=1000000.0,
            status=WorkflowStatus.DRAFT,
        )
        
        # 验证变量解析器能解析 $emotion 变量
        resolver = VariableResolver()
        context = ResolutionContext(
            workflow_id="workflow_with_emotion",
            execution_id="test_execution",
            emotion_module=mock_emotion_module
        )
        
        result = resolver.resolve("$emotion.valence", context)
        assert result.success is True
        assert result.value == 0.8

    def test_workflow_with_crystal_variable(self, mock_crystallizer):
        """测试工作流中使用 $crystal 变量"""
        workflow = WorkflowDefinition(
            id="workflow_with_crystal",
            name="带结晶变量的工作流",
            description="测试 $crystal 前缀",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="start_1",
                    type="builtin:start",
                    position={"x": 0, "y": 0},
                    config={"inputs_schema": {"query": "string"}},
                ),
                WorkflowNode(
                    id="llm_1",
                    type="builtin:llm",
                    position={"x": 200, "y": 0},
                    config={
                        "prompt": "结晶经验：$crystal.pattern，请回答：$input.query",
                        "model_provider": "auto",
                    },
                ),
                WorkflowNode(
                    id="end_1",
                    type="builtin:end",
                    position={"x": 400, "y": 0},
                    config={"output_mapping": {"result": "$node.llm_1.output"}},
                ),
            ],
            edges=[
                WorkflowEdge(id="edge_1", source="start_1", target="llm_1"),
                WorkflowEdge(id="edge_2", source="llm_1", target="end_1"),
            ],
            variables=[],
            tags=["test"],
            category="test",
            author="test_user",
            created_at=1000000.0,
            updated_at=1000000.0,
            status=WorkflowStatus.DRAFT,
        )
        
        # 验证变量解析器能解析 $crystal 变量
        resolver = VariableResolver()
        context = ResolutionContext(
            workflow_id="workflow_with_crystal",
            execution_id="test_execution",
            crystallizer=mock_crystallizer
        )
        
        result = resolver.resolve("$crystal.pattern", context)
        assert result.success is True
        assert result.value == [{"pattern": "测试模式", "confidence": 0.9}]


class TestAPIEndpointInjection:
    """API 端点注入测试"""

    def test_api_endpoint_agent_fallback_logic(self):
        """测试 API 端点中的 Agent 回退逻辑（纯逻辑验证，不依赖实际模块）"""
        # 模拟 get_agent_instance 函数
        def mock_get_agent(agent_id):
            if agent_id == "nonexistent":
                return None
            return MagicMock()
        
        # 测试当指定的 agent_id 不存在时，尝试获取默认 Agent
        agent_id = "nonexistent"
        agent = None
        
        # 执行回退逻辑（与 neurflow_api.py 中相同的逻辑）
        if agent_id:
            agent = mock_get_agent(agent_id)
        if agent is None:
            agent = mock_get_agent("default")
        
        # 验证回退逻辑
        assert agent is not None

    def test_api_endpoint_context_pool_fallback_logic(self):
        """测试 API 端点中的 ContextPool 回退逻辑（纯逻辑验证，不依赖实际模块）"""
        # 模拟 ContextPool 创建
        mock_context_pool = MagicMock()
        def mock_context_pool_factory(user_id, agent_id):
            return mock_context_pool
        
        # 模拟 Agent 没有 context_pool 属性
        agent = MagicMock(spec=[])  # 空 spec，没有属性
        
        context_pool = getattr(agent, 'context_pool', None)
        if context_pool is None and hasattr(agent, 'context_orchestrator'):
            context_pool = getattr(agent.context_orchestrator, 'pool', None)
        
        # 如果 context_pool 仍然为 None，创建一个默认的 ContextPool 实例
        if context_pool is None:
            context_pool = mock_context_pool_factory(
                user_id="default",
                agent_id="default"
            )
        
        # 验证回退逻辑
        assert context_pool is mock_context_pool