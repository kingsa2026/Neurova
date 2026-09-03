# -*- coding: utf-8 -*-
"""
Neurflow 中等优先级断裂点修复测试

测试内容：
1. LLM 节点变量解析修复
2. 上下文节点实现
3. 情感节点实现
4. Agent 节点实现
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from neurova.collaboration.neurflow import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeDefinition, NodeCategory, NodePort,
    WorkflowExecutor, ExecutionStatus, get_workflow_executor,
    VariableResolver, ResolutionContext, get_variable_resolver,
)


# ============ 辅助函数 ============

def create_llm_workflow() -> WorkflowDefinition:
    """创建工作流：start -> llm -> end"""
    return WorkflowDefinition(
        id="test_llm_workflow",
        name="LLM 测试工作流",
        description="测试 LLM 节点",
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
                position={"x": 100, "y": 0},
                config={
                    "prompt": "请回答: {{query}}",
                    "model": "gpt-4",
                    "temperature": 0.7,
                },
            ),
            WorkflowNode(
                id="end_1",
                type="builtin:end",
                position={"x": 200, "y": 0},
                config={"output_schema": {"result": "string"}},
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


def create_context_workflow() -> WorkflowDefinition:
    """创建工作流：start -> context -> end"""
    return WorkflowDefinition(
        id="test_context_workflow",
        name="上下文测试工作流",
        description="测试上下文节点",
        version="1.0.0",
        nodes=[
            WorkflowNode(
                id="start_1",
                type="builtin:start",
                position={"x": 0, "y": 0},
                config={"inputs_schema": {"query": "string"}},
            ),
            WorkflowNode(
                id="context_1",
                type="builtin:context",
                position={"x": 100, "y": 0},
                config={
                    "sources": ["memory", "emotion"],
                    "token_budget": 4096,
                },
            ),
            WorkflowNode(
                id="end_1",
                type="builtin:end",
                position={"x": 200, "y": 0},
                config={"output_schema": {"result": "string"}},
            ),
        ],
        edges=[
            WorkflowEdge(id="edge_1", source="start_1", target="context_1"),
            WorkflowEdge(id="edge_2", source="context_1", target="end_1"),
        ],
        variables=[],
        tags=["test"],
        category="test",
        author="test_user",
        created_at=1000000.0,
        updated_at=1000000.0,
        status=WorkflowStatus.DRAFT,
    )


def create_emotion_workflow() -> WorkflowDefinition:
    """创建工作流：start -> emotion -> end"""
    return WorkflowDefinition(
        id="test_emotion_workflow",
        name="情感测试工作流",
        description="测试情感节点",
        version="1.0.0",
        nodes=[
            WorkflowNode(
                id="start_1",
                type="builtin:start",
                position={"x": 0, "y": 0},
                config={"inputs_schema": {"text": "string"}},
            ),
            WorkflowNode(
                id="emotion_1",
                type="builtin:emotion",
                position={"x": 100, "y": 0},
                config={
                    "text": "{{text}}",
                    "mode": "analyze",
                },
            ),
            WorkflowNode(
                id="end_1",
                type="builtin:end",
                position={"x": 200, "y": 0},
                config={"output_schema": {"result": "string"}},
            ),
        ],
        edges=[
            WorkflowEdge(id="edge_1", source="start_1", target="emotion_1"),
            WorkflowEdge(id="edge_2", source="emotion_1", target="end_1"),
        ],
        variables=[],
        tags=["test"],
        category="test",
        author="test_user",
        created_at=1000000.0,
        updated_at=1000000.0,
        status=WorkflowStatus.DRAFT,
    )


def create_agent_workflow() -> WorkflowDefinition:
    """创建工作流：start -> agent -> end"""
    return WorkflowDefinition(
        id="test_agent_workflow",
        name="Agent 测试工作流",
        description="测试 Agent 节点",
        version="1.0.0",
        nodes=[
            WorkflowNode(
                id="start_1",
                type="builtin:start",
                position={"x": 0, "y": 0},
                config={"inputs_schema": {"task": "string"}},
            ),
            WorkflowNode(
                id="agent_1",
                type="builtin:agent",
                position={"x": 100, "y": 0},
                config={
                    "agent_id": "agent_123",
                    "task": "{{task}}",
                },
            ),
            WorkflowNode(
                id="end_1",
                type="builtin:end",
                position={"x": 200, "y": 0},
                config={"output_schema": {"result": "string"}},
            ),
        ],
        edges=[
            WorkflowEdge(id="edge_1", source="start_1", target="agent_1"),
            WorkflowEdge(id="edge_2", source="agent_1", target="end_1"),
        ],
        variables=[],
        tags=["test"],
        category="test",
        author="test_user",
        created_at=1000000.0,
        updated_at=1000000.0,
        status=WorkflowStatus.DRAFT,
    )


# ============ 测试类 ============

class TestLLMNodeVariableResolution:
    """测试 LLM 节点变量解析修复"""
    
    @pytest.mark.asyncio
    async def test_llm_node_should_use_pre_resolved_config(self):
        """测试: LLM 节点应该使用预解析的配置"""
        # 准备
        workflow = create_llm_workflow()
        
        # 模拟 Agent
        mock_agent = AsyncMock()
        mock_agent.chat.return_value = MagicMock(content="AI 回答")
        
        with patch('neurova.collaboration.neurflow.builtin._get_agent', return_value=mock_agent):
            
            executor = get_workflow_executor()
            
            # 执行
            result = await executor.execute(
                workflow=workflow,
                inputs={"query": "测试问题"}
            )
            
            # 验证
            assert result.status == WorkflowStatus.COMPLETED
            # LLM 节点应该成功执行
            llm_result = result.node_results.get("llm_1")
            assert llm_result is not None
            assert llm_result.status == "success"
    
    @pytest.mark.asyncio
    async def test_llm_node_should_not_try_to_resolve_variables_again(self):
        """测试: LLM 节点不应该尝试再次解析变量"""
        # 准备
        workflow = create_llm_workflow()
        
        # 模拟 Agent
        mock_agent = AsyncMock()
        mock_agent.chat.return_value = MagicMock(content="AI 回答")
        
        # 模拟变量解析器（不应该被调用）
        mock_resolver = MagicMock()
        mock_resolver.resolve_string = MagicMock()
        
        with patch('neurova.collaboration.neurflow.builtin._get_agent', return_value=mock_agent), \
             patch('neurova.collaboration.neurflow.variable_resolver.get_variable_resolver', return_value=mock_resolver):
            
            executor = get_workflow_executor()
            
            # 执行
            result = await executor.execute(
                workflow=workflow,
                inputs={"query": "测试问题"}
            )
            
            # 验证
            assert result.status == WorkflowStatus.COMPLETED
            # 变量解析器的 resolve_string 不应该被调用
            mock_resolver.resolve_string.assert_not_called()


class TestContextNodeImplementation:
    """测试上下文节点实现"""
    
    @pytest.mark.asyncio
    async def test_context_node_should_call_context_pool(self):
        """测试: 上下文节点应该调用 ContextPool"""
        # 准备
        workflow = create_context_workflow()
        
        # 模拟 ContextPool
        mock_context_pool = MagicMock()
        mock_context_pool.get_context.return_value = {
            "system_prompt": "你是一个AI助手",
            "recent_messages": ["消息1", "消息2"],
            "memory": ["记忆1", "记忆2"],
            "emotion": {"primary": "happy", "score": 0.8}
        }
        
        # 模拟 Agent
        mock_agent = AsyncMock()
        
        with patch('neurova.collaboration.neurflow.builtin._get_context_pool', return_value=mock_context_pool), \
             patch('neurova.collaboration.neurflow.builtin._get_agent', return_value=mock_agent):
            
            executor = get_workflow_executor()
            
            # 执行
            result = await executor.execute(
                workflow=workflow,
                inputs={"query": "测试问题"}
            )
            
            # 验证
            assert result.status == WorkflowStatus.COMPLETED
            # 上下文节点应该成功执行
            context_result = result.node_results.get("context_1")
            assert context_result is not None
            assert context_result.status == "success"
            # 应该调用 context_pool.get_context()
            mock_context_pool.get_context.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_context_node_should_return_context_data(self):
        """测试: 上下文节点应该返回上下文数据"""
        # 准备
        workflow = create_context_workflow()
        
        # 模拟 ContextPool
        expected_context = {
            "system_prompt": "你是一个AI助手",
            "recent_messages": ["消息1", "消息2"],
            "memory": ["记忆1", "记忆2"],
            "emotion": {"primary": "happy", "score": 0.8}
        }
        mock_context_pool = MagicMock()
        mock_context_pool.get_context.return_value = expected_context
        
        # 模拟 Agent
        mock_agent = AsyncMock()
        
        with patch('neurova.collaboration.neurflow.builtin._get_context_pool', return_value=mock_context_pool), \
             patch('neurova.collaboration.neurflow.builtin._get_agent', return_value=mock_agent):
            
            executor = get_workflow_executor()
            
            # 执行
            result = await executor.execute(
                workflow=workflow,
                inputs={"query": "测试问题"}
            )
            
            # 验证
            context_result = result.node_results.get("context_1")
            assert context_result is not None
            assert context_result.output == expected_context


class TestEmotionNodeImplementation:
    """测试情感节点实现"""
    
    @pytest.mark.asyncio
    async def test_emotion_node_should_call_emotion_module_analyze(self):
        """测试: 情感节点应该调用 EmotionModule.analyze()"""
        # 准备
        workflow = create_emotion_workflow()
        
        # 模拟 EmotionModule
        mock_emotion_module = MagicMock()
        mock_emotion_module.analyze.return_value = {
            "emotion": "happy",
            "confidence": 0.8,
            "valence": 0.9
        }
        
        # 模拟 Agent
        mock_agent = AsyncMock()
        
        with patch('neurova.collaboration.neurflow.builtin._get_emotion_module', return_value=mock_emotion_module), \
             patch('neurova.collaboration.neurflow.builtin._get_agent', return_value=mock_agent):
            
            executor = get_workflow_executor()
            
            # 执行
            result = await executor.execute(
                workflow=workflow,
                inputs={"text": "我今天非常开心！"}
            )
            
            # 验证
            assert result.status == WorkflowStatus.COMPLETED
            # 情感节点应该成功执行
            emotion_result = result.node_results.get("emotion_1")
            assert emotion_result is not None
            assert emotion_result.status == "success"
            # 应该调用 emotion_module.analyze()
            mock_emotion_module.analyze.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_emotion_node_should_return_emotion_analysis(self):
        """测试: 情感节点应该返回情感分析结果"""
        # 准备
        workflow = create_emotion_workflow()
        
        # 模拟 EmotionModule
        expected_emotion = {
            "emotion": "happy",
            "confidence": 0.8,
            "valence": 0.9
        }
        mock_emotion_module = MagicMock()
        mock_emotion_module.analyze.return_value = expected_emotion
        
        # 模拟 Agent
        mock_agent = AsyncMock()
        
        with patch('neurova.collaboration.neurflow.builtin._get_emotion_module', return_value=mock_emotion_module), \
             patch('neurova.collaboration.neurflow.builtin._get_agent', return_value=mock_agent):
            
            executor = get_workflow_executor()
            
            # 执行
            result = await executor.execute(
                workflow=workflow,
                inputs={"text": "我今天非常开心！"}
            )
            
            # 验证
            emotion_result = result.node_results.get("emotion_1")
            assert emotion_result is not None
            assert emotion_result.output == expected_emotion


class TestAgentNodeImplementation:
    """测试 Agent 节点实现（蜂群分派架构）"""
    
    @pytest.mark.asyncio
    async def test_agent_node_should_call_agent_chat(self):
        """测试: Agent 节点应该经 SwarmManager 调用目标 agent.chat()（蜂群分派）"""
        # 准备
        workflow = create_agent_workflow()

        # 模拟 Agent（Agent.chat 返回 dict{"text"}）
        mock_agent = AsyncMock()
        mock_agent.chat.return_value = {"text": "Agent 回答"}
        mock_agent.config.name = "agent_123"

        with patch('neurova.api.endpoints.get_agent_instance', return_value=mock_agent):

            executor = get_workflow_executor()

            # 执行
            result = await executor.execute(
                workflow=workflow,
                inputs={"task": "分析数据"}
            )

            # 验证
            assert result.status == WorkflowStatus.COMPLETED
            # Agent 节点应该成功执行
            agent_result = result.node_results.get("agent_1")
            assert agent_result is not None
            assert agent_result.status == "success"
            # 应该调用目标 agent.chat()
            mock_agent.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_node_should_return_agent_response(self):
        """测试: Agent 节点应该返回 Agent 响应（蜂群分派）"""
        # 准备
        workflow = create_agent_workflow()

        # 模拟 Agent
        expected_response = "数据分析完成，发现3个异常"
        mock_agent = AsyncMock()
        mock_agent.chat.return_value = {"text": expected_response}
        mock_agent.config.name = "agent_123"

        with patch('neurova.api.endpoints.get_agent_instance', return_value=mock_agent):

            executor = get_workflow_executor()

            # 执行
            result = await executor.execute(
                workflow=workflow,
                inputs={"task": "分析数据"}
            )

            # 验证
            agent_result = result.node_results.get("agent_1")
            assert agent_result is not None
            assert agent_result.output.get("result") == expected_response
            # 蜂群分派元数据
            assert agent_result.output.get("resolved_agent_id") is not None


class TestNeurloopMediumIntegration:
    """测试中等优先级断裂点集成"""
    
    @pytest.mark.asyncio
    async def test_llm_node_should_work_with_pre_resolved_config(self):
        """测试: LLM 节点应该使用预解析的配置工作"""
        # 准备
        workflow = create_llm_workflow()
        
        # 模拟 Agent
        mock_agent = AsyncMock()
        mock_agent.chat.return_value = MagicMock(content="AI 回答")
        
        with patch('neurova.collaboration.neurflow.builtin._get_agent', return_value=mock_agent):
            
            executor = get_workflow_executor()
            
            # 执行
            result = await executor.execute(
                workflow=workflow,
                inputs={"query": "测试问题"}
            )
            
            # 验证
            assert result.status == WorkflowStatus.COMPLETED
            assert result.error is None