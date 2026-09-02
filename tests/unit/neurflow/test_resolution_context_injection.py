"""测试 ResolutionContext 外部系统注入修复

Bug: neurflow_api.py 的 execute_workflow() 构建 ResolutionContext 时，
memory_manager/emotion_module/crystallizer 始终为 None，
因为只有 context_pool 有降级逻辑，其他三个外部系统没有。
影响: $memory/$emotion/$crystal 变量前缀在工作流节点中全部返回 None。
"""
import pytest
import sys
import asyncio
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestResolutionContextInjection:
    """测试 ResolutionContext 外部系统注入"""

    def test_resolution_context_stores_external_systems(self):
        """ResolutionContext 应正确存储外部系统引用"""
        from neurova.collaboration.neurflow.variable_resolver import ResolutionContext

        mock_memory = Mock()
        mock_context = Mock()
        mock_emotion = Mock()
        mock_crystal = Mock()

        ctx = ResolutionContext(
            workflow_id="wf_1",
            execution_id="exec_1",
            memory_manager=mock_memory,
            context_pool=mock_context,
            emotion_module=mock_emotion,
            crystallizer=mock_crystal,
        )

        assert ctx.memory_manager is mock_memory
        assert ctx.context_pool is mock_context
        assert ctx.emotion_module is mock_emotion
        assert ctx.crystallizer is mock_crystal

    def test_variable_resolver_uses_injected_systems(self):
        """VariableResolver 应使用注入的外部系统"""
        from neurova.collaboration.neurflow.variable_resolver import VariableResolver, ResolutionContext

        resolver = VariableResolver()
        mock_memory = Mock()
        mock_memory.search_memories.return_value = [{"content": "test memory"}]

        ctx = ResolutionContext(
            workflow_id="wf_1",
            execution_id="exec_1",
            memory_manager=mock_memory,
        )

        result = resolver.resolve("$memory.test_query", ctx)
        assert result.success is True
        mock_memory.search_memories.assert_called_once_with("test_query")

    def test_workflow_executor_passes_external_systems_to_context(self):
        """WorkflowExecutor.execute() 应将外部系统参数传递给 ResolutionContext 构造"""
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor

        executor = WorkflowExecutor()
        mock_memory = Mock()
        mock_context = Mock()
        mock_emotion = Mock()
        mock_crystal = Mock()

        # 直接检查 execute 方法的签名包含外部系统参数
        import inspect
        sig = inspect.signature(executor.execute)
        assert "memory_manager" in sig.parameters, "execute() 缺少 memory_manager 参数"
        assert "context_pool" in sig.parameters, "execute() 缺少 context_pool 参数"
        assert "emotion_module" in sig.parameters, "execute() 缺少 emotion_module 参数"
        assert "crystallizer" in sig.parameters, "execute() 缺少 crystallizer 参数"

    def test_neurflow_api_extracts_external_systems_from_agent(self):
        """neurflow_api 应从 Agent 提取外部系统"""
        from neurova.api.endpoints.neurflow_api import execute_workflow

        mock_agent = Mock()
        mock_agent.memory_manager = Mock()
        # 显式删除 context_pool，使 getattr 返回 None，触发 context_orchestrator 降级
        mock_agent.context_pool = None
        mock_agent.context_orchestrator = Mock()
        mock_agent.context_orchestrator.pool = Mock()
        mock_agent.crystallizer = Mock()
        mock_agent.memory_manager._emotion_module = Mock()

        with patch("neurova.api.endpoints.neurflow_api.get_agent_instance", return_value=mock_agent), \
             patch("neurova.api.endpoints.neurflow_api._get_storage") as mock_storage_fn:
            mock_storage = Mock()
            mock_storage_fn.return_value = mock_storage

            mock_workflow = Mock()
            mock_storage.get_workflow.return_value = mock_workflow

            mock_executor = AsyncMock()
            mock_instance = Mock()
            mock_instance.id = "exec_1"
            mock_instance.workflow_id = "wf_1"
            mock_instance.status = Mock()
            mock_instance.status.value = "completed"
            mock_instance.inputs = {}
            mock_instance.outputs = {}
            mock_instance.node_results = {}
            mock_instance.variables = {}
            mock_instance.started_at = 0
            mock_instance.finished_at = 1
            mock_instance.duration = 1
            mock_instance.error = None
            mock_executor.execute.return_value = mock_instance

            with patch("neurova.api.endpoints.neurflow_api.get_workflow_executor", return_value=mock_executor):
                asyncio.run(
                    execute_workflow(
                        workflow_id="wf_1",
                        inputs={},
                        user_id="user_1",
                        agent_id="agent_1",
                        current_user={"user_id": "user_1", "role": "admin"},
                    )
                )

                mock_executor.execute.assert_called_once()
                call_kwargs = mock_executor.execute.call_args[1]
                assert call_kwargs["memory_manager"] is mock_agent.memory_manager
                assert call_kwargs["context_pool"] is mock_agent.context_orchestrator.pool
                assert call_kwargs["emotion_module"] is mock_agent.memory_manager._emotion_module
                assert call_kwargs["crystallizer"] is mock_agent.crystallizer


class TestNeurflowApiFallback:
    """测试 neurflow_api 的降级逻辑（Agent 不可用时）"""

    def _run_execute(self, mock_agent=None):
        """辅助方法：执行 execute_workflow 并返回调用参数"""
        from neurova.api.endpoints.neurflow_api import execute_workflow

        with patch("neurova.api.endpoints.neurflow_api.get_agent_instance", return_value=mock_agent), \
             patch("neurova.api.endpoints.neurflow_api._get_storage") as mock_storage_fn:
            mock_storage = Mock()
            mock_storage_fn.return_value = mock_storage
            mock_storage.get_workflow.return_value = Mock()

            mock_executor = AsyncMock()
            mock_instance = Mock()
            mock_instance.id = "exec_1"
            mock_instance.workflow_id = "wf_1"
            mock_instance.status = Mock()
            mock_instance.status.value = "completed"
            mock_instance.inputs = {}
            mock_instance.outputs = {}
            mock_instance.node_results = {}
            mock_instance.variables = {}
            mock_instance.started_at = 0
            mock_instance.finished_at = 1
            mock_instance.duration = 1
            mock_instance.error = None
            mock_executor.execute.return_value = mock_instance

            with patch("neurova.api.endpoints.neurflow_api.get_workflow_executor", return_value=mock_executor):
                asyncio.run(
                    execute_workflow(
                        workflow_id="wf_1",
                        inputs={},
                        user_id="user_1",
                        agent_id="agent_1",
                        current_user={"user_id": "user_1", "role": "admin"},
                    )
                )
                return mock_executor.execute.call_args[1]

    def test_fallback_creates_all_systems_when_agent_unavailable(self):
        """当 Agent 不可用时，四个外部系统都不应为 None"""
        call_kwargs = self._run_execute(mock_agent=None)

        assert call_kwargs["memory_manager"] is not None, "memory_manager 降级失败"
        assert call_kwargs["context_pool"] is not None, "context_pool 降级失败"
        assert call_kwargs["emotion_module"] is not None, "emotion_module 降级失败"
        assert call_kwargs["crystallizer"] is not None, "crystallizer 降级失败"

    def test_fallback_memory_manager_is_correct_type(self):
        """降级创建的 memory_manager 应为 MemoryManager 类型"""
        call_kwargs = self._run_execute(mock_agent=None)

        from neurova.cognitive_layers.memory_layer.manager import MemoryManager
        assert isinstance(call_kwargs["memory_manager"], MemoryManager)

    def test_fallback_emotion_module_not_none(self):
        """降级创建的 emotion_module 应不为 None"""
        call_kwargs = self._run_execute(mock_agent=None)
        assert call_kwargs["emotion_module"] is not None

    def test_agent_available_uses_agent_systems(self):
        """当 Agent 可用时，应使用 Agent 的外部系统而非降级实例"""
        mock_agent = Mock()
        mock_agent.memory_manager = Mock()
        mock_agent.context_pool = None
        mock_agent.context_orchestrator = Mock()
        mock_agent.context_orchestrator.pool = Mock()
        mock_agent.crystallizer = Mock()
        mock_agent.memory_manager._emotion_module = Mock()

        call_kwargs = self._run_execute(mock_agent=mock_agent)

        assert call_kwargs["memory_manager"] is mock_agent.memory_manager
        assert call_kwargs["context_pool"] is mock_agent.context_orchestrator.pool
        assert call_kwargs["emotion_module"] is mock_agent.memory_manager._emotion_module
        assert call_kwargs["crystallizer"] is mock_agent.crystallizer


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
