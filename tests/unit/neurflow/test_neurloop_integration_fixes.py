# -*- coding: utf-8 -*-
"""
Neurloop 集成断裂点修复测试

测试三个高优先级断裂点的修复：
1. ResolutionContext 注入
2. 进化节点签名匹配
3. 审批回复机制
"""

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.collaboration.neurflow import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeDefinition, NodeCategory, NodePort,
    WorkflowExecutor, ExecutionStatus, get_workflow_executor,
    VariableResolver, ResolutionContext, get_variable_resolver,
    reset_node_registry,
)


# ============ 切片 1: ResolutionContext 注入测试 ============

class TestResolutionContextInjection:
    """测试 ResolutionContext 外部系统注入"""

    @pytest.fixture
    def executor(self):
        """创建工作流执行器"""
        reset_node_registry()
        return get_workflow_executor()

    @pytest.fixture
    def mock_memory_manager(self):
        """模拟记忆管理器"""
        mock = MagicMock()
        mock.search.return_value = [
            MagicMock(content="测试记忆内容", score=0.9)
        ]
        return mock

    @pytest.fixture
    def mock_context_pool(self):
        """模拟上下文池"""
        mock = MagicMock()
        mock.get_context.return_value = "测试上下文"
        return mock

    @pytest.fixture
    def mock_emotion_module(self):
        """模拟情感模块"""
        mock = MagicMock()
        mock.analyze_text_emotion.return_value = {"emotion": "happy", "score": 0.8}
        return mock

    @pytest.fixture
    def mock_crystallizer(self):
        """模拟结晶器"""
        mock = MagicMock()
        mock.retrieve.return_value = [
            MagicMock(content="结晶经验", relevance=0.7)
        ]
        return mock

    def test_resolution_context_should_accept_external_systems(self):
        """测试: ResolutionContext 应该接受外部系统引用"""
        # 准备
        mock_memory = MagicMock()
        mock_context = MagicMock()
        mock_emotion = MagicMock()
        mock_crystal = MagicMock()
        
        # 执行
        ctx = ResolutionContext(
            workflow_id="test",
            execution_id="test_exec",
            memory_manager=mock_memory,
            context_pool=mock_context,
            emotion_module=mock_emotion,
            crystallizer=mock_crystal
        )
        
        # 验证
        assert ctx.memory_manager is mock_memory
        assert ctx.context_pool is mock_context
        assert ctx.emotion_module is mock_emotion
        assert ctx.crystallizer is mock_crystal

    def test_variable_resolver_should_resolve_memory_prefix(self, mock_memory_manager):
        """测试: 变量解析器应该解析 $memory 前缀"""
        # 准备
        resolver = get_variable_resolver()
        ctx = ResolutionContext(
            workflow_id="test",
            execution_id="test_exec",
            memory_manager=mock_memory_manager
        )
        
        # 执行
        result = resolver.resolve("$memory.search", ctx)
        
        # 验证
        assert result is not None
        assert result.success is True
        assert result.value is not None
        mock_memory_manager.search.assert_called_once()

    def test_variable_resolver_should_resolve_context_prefix(self, mock_context_pool):
        """测试: 变量解析器应该解析 $context 前缀"""
        # 准备
        mock_context_pool.get_context.return_value = {
            "system_prompt": "你是一个AI助手",
            "recent_messages": ["消息1", "消息2"]
        }
        resolver = get_variable_resolver()
        ctx = ResolutionContext(
            workflow_id="test",
            execution_id="test_exec",
            context_pool=mock_context_pool
        )
        
        # 执行
        result = resolver.resolve("$context.system_prompt", ctx)
        
        # 验证
        assert result is not None
        assert result.success is True
        assert result.value == "你是一个AI助手"
        mock_context_pool.get_context.assert_called_once()

    def test_variable_resolver_should_resolve_emotion_prefix(self, mock_emotion_module):
        """测试: 变量解析器应该解析 $emotion 前缀"""
        # 准备
        mock_emotion_module.current.return_value = {
            "valence": 0.8,
            "primary_emotion": "happy",
            "intensity": 0.9
        }
        resolver = get_variable_resolver()
        ctx = ResolutionContext(
            workflow_id="test",
            execution_id="test_exec",
            emotion_module=mock_emotion_module
        )
        
        # 执行
        result = resolver.resolve("$emotion.primary_emotion", ctx)
        
        # 验证
        assert result is not None
        assert result.success is True
        assert result.value == "happy"
        mock_emotion_module.current.assert_called_once()

    def test_variable_resolver_should_resolve_crystal_prefix(self, mock_crystallizer):
        """测试: 变量解析器应该解析 $crystal 前缀"""
        # 准备
        mock_crystallizer.retrieve.return_value = ["结晶经验"]
        resolver = get_variable_resolver()
        ctx = ResolutionContext(
            workflow_id="test",
            execution_id="test_exec",
            crystallizer=mock_crystallizer
        )
        
        # 执行
        result = resolver.resolve("$crystal.pattern_name", ctx)
        
        # 验证
        assert result is not None
        assert result.success is True
        assert result.value == ["结晶经验"]
        mock_crystallizer.retrieve.assert_called_once_with("pattern_name")

    def test_variable_resolver_should_return_none_when_not_injected(self):
        """测试: 未注入时应该返回失败结果"""
        # 准备
        resolver = get_variable_resolver()
        ctx = ResolutionContext(
            workflow_id="test",
            execution_id="test_exec"
        )
        
        # 执行
        memory_result = resolver.resolve("$memory.search", ctx)
        context_result = resolver.resolve("$context.system_prompt", ctx)
        emotion_result = resolver.resolve("$emotion.primary_emotion", ctx)
        crystal_result = resolver.resolve("$crystal.pattern_name", ctx)
        
        # 验证
        assert memory_result.success is False
        assert context_result.success is False
        assert emotion_result.success is False
        assert crystal_result.success is False


# ============ 切片 2: 进化节点签名修复测试 ============

class TestEvolutionNodeSignature:
    """测试进化节点签名匹配"""

    @pytest.fixture
    def mock_evolution(self):
        """模拟 EvolutionOrchestrator"""
        mock = MagicMock()
        mock.on_experience_recorded.return_value = {
            "status": "learned",
            "insights": ["工具使用经验"]
        }
        return mock

    def test_get_evolution_orchestrator_should_return_instance(self):
        """测试: get_evolution_orchestrator 应该返回实例"""
        # 准备
        with patch('neurova.evolution.closed_loop.EvolutionOrchestrator') as MockOrchestrator:
            MockOrchestrator.return_value = MagicMock()
            
            # 执行
            from neurova.evolution.closed_loop import get_evolution_orchestrator
            result = get_evolution_orchestrator()
            
            # 验证
            assert result is not None
            MockOrchestrator.assert_called_once()

    def test_exec_evolution_should_unpack_feedback_data(self, mock_evolution):
        """测试: exec_evolution 应该解包 feedback_data"""
        # 准备
        config = {
            "mode": "learn",
            "feedback_data": {
                "text": "成功使用工具完成任务",
                "task": "文件处理",
                "tools": ["file_read", "file_write"],
                "success": True
            }
        }
        ctx = {"execution_id": "test_exec", "node_id": "evolution_1"}
        
        with patch('neurova.collaboration.neurflow.builtin._get_evolution', return_value=mock_evolution):
            from neurova.collaboration.neurflow.builtin import exec_evolution
            
            # 执行
            result = asyncio.run(exec_evolution(config, ctx))
            
            # 验证
            assert result["status"] == "success"
            mock_evolution.on_experience_recorded.assert_called_once_with(
                text="成功使用工具完成任务",
                task="文件处理",
                tools=["file_read", "file_write"],
                success=True
            )

    def test_exec_evolution_should_handle_missing_fields(self, mock_evolution):
        """测试: exec_evolution 应该处理缺失字段"""
        # 准备
        config = {
            "mode": "learn",
            "feedback_data": {
                "text": "部分数据",
                # 缺失 task, tools, success
            }
        }
        ctx = {"execution_id": "test_exec", "node_id": "evolution_1"}
        
        with patch('neurova.collaboration.neurflow.builtin._get_evolution', return_value=mock_evolution):
            from neurova.collaboration.neurflow.builtin import exec_evolution
            
            # 执行
            result = asyncio.run(exec_evolution(config, ctx))
            
            # 验证
            assert result["status"] == "success"
            # 应该使用默认值
            mock_evolution.on_experience_recorded.assert_called_once_with(
                text="部分数据",
                task="",
                tools=[],
                success=False
            )


# ============ 切片 3: 审批回复机制测试 ============

class TestApprovalReplyMechanism:
    """测试审批回复机制"""

    @pytest.fixture
    def mock_channel_manager(self):
        """模拟 ChannelManager"""
        mock = AsyncMock()
        mock.send_message.return_value = "msg_123"
        return mock

    @pytest.fixture
    def mock_message_handler(self):
        """模拟消息处理器"""
        mock = AsyncMock()
        return mock

    def test_approval_should_register_message_handler(self, mock_channel_manager):
        """测试: 审批应该注册消息处理器（现行契约：add_message_handler）"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 2,
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}

        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager',
                   return_value=mock_channel_manager):
            from neurova.collaboration.neurflow.builtin import exec_approval

            # 执行（无真实回复 → 走到超时，但注册必须先发生）
            asyncio.run(exec_approval(config, ctx))

        # 验证：使用 add_message_handler 注册（而非 set，避免覆盖其他处理器）
        mock_channel_manager.add_message_handler.assert_called_once()
        args, kwargs = mock_channel_manager.add_message_handler.call_args
        handler = args[0] if args else kwargs.get("handler")
        assert callable(handler)
        mock_channel_manager.remove_message_handler.assert_called()

    def test_approval_handler_should_process_approve_message(self, mock_channel_manager):
        """测试: 注册的消息处理器应能处理批准回复并解除阻塞"""
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 5,
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}

        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager',
                   return_value=mock_channel_manager):
            from neurova.collaboration.neurflow.builtin import exec_approval

            outcome = {}

            def runner():
                outcome["result"] = asyncio.run(exec_approval(config, ctx))

            t = threading.Thread(target=runner, daemon=True)
            t.start()

            # 等待处理器注册
            for _ in range(50):
                if mock_channel_manager.add_message_handler.called:
                    break
                time.sleep(0.1)
            assert mock_channel_manager.add_message_handler.called, "处理器未注册"

            args, kwargs = mock_channel_manager.add_message_handler.call_args
            handler = args[0] if args else kwargs.get("handler")

            # 模拟审批人回复 approve
            msg = SimpleNamespace(content="approve", sender_id="user_123")
            asyncio.run(handler(msg))

            t.join(timeout=10)
            assert not t.is_alive(), "收到批准后 exec_approval 应解除阻塞"

            result = outcome.get("result", {})
            assert result.get("status") == "success"
            assert (result.get("output") or {}).get("approved") is True

class TestNeurloopIntegration:
    """测试 Neurloop 集成修复"""

    def test_resolution_context_injection_in_workflow_execution(self):
        """测试: 工作流执行中 ResolutionContext 注入"""
        # 准备
        mock_memory = MagicMock()
        mock_memory.search.return_value = [MagicMock(content="记忆内容")]
        
        mock_context = MagicMock()
        mock_context.get_context.return_value = "上下文内容"
        
        # 创建使用 $memory 和 $context 变量的工作流
        workflow = WorkflowDefinition(
            id="test_integration",
            name="集成测试工作流",
            description="测试变量注入",
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
                        "prompt": "根据记忆回答: $memory.search(query='${inputs.query}')",
                        "context": "上下文: $context.get_current()"
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
        
        # 执行
        executor = get_workflow_executor()
        result = asyncio.run(executor.execute(
            workflow=workflow,
            inputs={"query": "测试"},
            memory_manager=mock_memory,
            context_pool=mock_context
        ))
        
        # 验证
        assert result.status == WorkflowStatus.COMPLETED
        # 验证变量被正确解析（通过检查 LLM 节点的输入）
        llm_result = result.node_results.get("llm_1")
        assert llm_result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])