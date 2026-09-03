"""
测试 Agent-Neurflow 集成桥接

验证：
1. WorkflowExecutor.get_recent_executions() 正确过滤和返回执行实例
2. PostChatPipeline._step_record_workflow_experience() 正确记录工作流经验
3. 工作流经验正确存储到 MemoryManager
4. Agent 初始化时正确绑定 neurflow_executor
"""
import time
import uuid
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from typing import List, Optional

from neurova.collaboration.neurflow.execution_engine import ExecutionStatus
from neurova.collaboration.neurflow.models import (
    WorkflowStatus, ExecutionInstance, NodeExecutionResult,
    WorkflowDefinition, WorkflowNode
)


def _make_executor():
    """创建一个不触发 ensure_builtin 的 WorkflowExecutor mock 实例"""
    with patch("neurova.collaboration.neurflow.execution_engine.get_node_registry") as mock_nr, \
         patch("neurova.collaboration.neurflow.execution_engine.get_variable_resolver"), \
         patch("neurova.collaboration.neurflow.execution_engine.get_dag_validator"):
        mock_nr.return_value.ensure_builtin = MagicMock()
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        return WorkflowExecutor()


def _make_workflow_def(workflow_id: str = "wf_test") -> WorkflowDefinition:
    """创建完整 WorkflowDefinition，满足所有必填字段"""
    now = time.time()
    return WorkflowDefinition(
        id=workflow_id,
        name=f"Test Workflow {workflow_id}",
        description="Test workflow",
        version="1.0.0",
        nodes=[WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={})],
        edges=[],
        variables=[],
        tags=[],
        category="general",
        author="test",
        created_at=now,
        updated_at=now,
        status=WorkflowStatus.DRAFT,
    )


# ============================================================
# WorkflowExecutor.get_recent_executions 测试
# ============================================================

class TestGetRecentExecutions:
    """测试 WorkflowExecutor.get_recent_executions 方法"""

    def _create_execution(
        self,
        executor,
        workflow_id: str = "wf_test",
        agent_id: Optional[str] = "agent_1",
        user_id: Optional[str] = "user_1",
        status: ExecutionStatus = ExecutionStatus.COMPLETED,
        started_at: Optional[float] = None,
    ) -> ExecutionInstance:
        """辅助方法：创建并注册执行实例"""
        workflow = _make_workflow_def(workflow_id)
        instance = executor.create_instance(workflow, {}, user_id=user_id, agent_id=agent_id)
        if started_at is not None:
            instance.started_at = started_at
        executor._statuses[instance.id] = status
        return instance

    def test_empty_executions(self):
        """无执行记录时返回空列表"""
        executor = _make_executor()
        result = executor.get_recent_executions()
        assert result == []

    def test_returns_completed_executions(self):
        """只返回已完成的执行（completed + failed）"""
        executor = _make_executor()
        self._create_execution(executor, status=ExecutionStatus.COMPLETED)
        self._create_execution(executor, status=ExecutionStatus.RUNNING)
        self._create_execution(executor, status=ExecutionStatus.FAILED)

        result = executor.get_recent_executions()
        assert len(result) == 2  # COMPLETED + FAILED

    def test_filters_by_agent_id(self):
        """按 agent_id 过滤"""
        executor = _make_executor()
        self._create_execution(executor, agent_id="agent_1")
        self._create_execution(executor, agent_id="agent_2")
        self._create_execution(executor, agent_id="agent_1")

        result = executor.get_recent_executions(agent_id="agent_1")
        assert len(result) == 2
        assert all(i.agent_id == "agent_1" for i in result)

    def test_filters_by_user_id(self):
        """按 user_id 过滤"""
        executor = _make_executor()
        self._create_execution(executor, user_id="user_a")
        self._create_execution(executor, user_id="user_b")

        result = executor.get_recent_executions(user_id="user_a")
        assert len(result) == 1
        assert result[0].user_id == "user_a"

    def test_filters_by_since_timestamp(self):
        """按时间戳过滤"""
        executor = _make_executor()
        now = time.time()
        self._create_execution(executor, started_at=now - 600)  # 10分钟前
        self._create_execution(executor, started_at=now - 60)   # 1分钟前

        result = executor.get_recent_executions(since_timestamp=now - 300)
        assert len(result) == 1

    def test_limit(self):
        """限制返回数量"""
        executor = _make_executor()
        for i in range(10):
            self._create_execution(executor, workflow_id=f"wf_{i}")

        result = executor.get_recent_executions(limit=3)
        assert len(result) == 3

    def test_sorted_by_start_time_desc(self):
        """按开始时间降序排列"""
        executor = _make_executor()
        now = time.time()
        self._create_execution(executor, workflow_id="wf_old", started_at=now - 100)
        self._create_execution(executor, workflow_id="wf_new", started_at=now - 10)

        result = executor.get_recent_executions()
        assert result[0].workflow_id == "wf_new"
        assert result[1].workflow_id == "wf_old"


# ============================================================
# PostChatPipeline._step_record_workflow_experience 测试
# ============================================================

class TestRecordWorkflowExperience:
    """测试 PostChatPipeline._step_record_workflow_experience 方法"""

    def _make_pipeline(self):
        """创建带有 mock 依赖的 PostChatPipeline"""
        from neurova.post_chat_pipeline import PostChatPipeline

        agent_ref = MagicMock()
        agent_ref.config = MagicMock()
        agent_ref.config.agent_id = "test_agent"

        pipeline = PostChatPipeline(agent_ref)
        return pipeline

    @pytest.mark.asyncio
    async def test_skip_when_no_executor(self):
        """当 neurflow_executor 不可用时跳过"""
        pipeline = self._make_pipeline()
        # 不设置 neurflow_executor

        await pipeline._step_record_workflow_experience("test input", "test reply", "session_1")

        results = pipeline._step_results
        assert len(results) == 1
        assert results[0].step_name == "record_workflow_experience"
        assert results[0].status.value == "skipped"

    @pytest.mark.asyncio
    async def test_skip_when_no_memory_manager(self):
        """当 memory_manager 不可用时跳过"""
        pipeline = self._make_pipeline()
        pipeline._neurflow_executor = MagicMock()
        # 确保 memory_manager 为 None（包括 agent fallback）
        pipeline._memory_manager = None
        pipeline._agent.memory_manager = None

        await pipeline._step_record_workflow_experience("test input", "test reply", "session_1")

        results = pipeline._step_results
        assert len(results) == 1
        assert results[0].status.value == "skipped"
        assert "memory_manager" in results[0].message

    @pytest.mark.asyncio
    async def test_skip_when_no_recent_executions(self):
        """当没有最近执行记录时跳过"""
        pipeline = self._make_pipeline()
        pipeline._neurflow_executor = MagicMock()
        pipeline._neurflow_executor.get_recent_executions.return_value = []
        pipeline._memory_manager = MagicMock()

        await pipeline._step_record_workflow_experience("test input", "test reply", "session_1")

        results = pipeline._step_results
        assert len(results) == 1
        assert results[0].status.value == "skipped"
        assert "No recent" in results[0].message

    @pytest.mark.asyncio
    async def test_records_successful_execution(self):
        """成功记录工作流执行经验"""
        pipeline = self._make_pipeline()
        
        # 创建 mock 执行实例
        mock_execution = MagicMock()
        mock_execution.workflow_id = "wf_test_001"
        mock_execution.id = "exec_001"
        mock_execution.status.value = "completed"
        mock_execution.duration = 5.5
        mock_execution.outputs = {"result": "success"}
        mock_execution.started_at = time.time() - 10
        mock_execution.finished_at = time.time()
        mock_execution.node_results = {
            "node1": MagicMock(status="success"),
            "node2": MagicMock(status="success"),
        }
        
        pipeline._neurflow_executor = MagicMock()
        pipeline._neurflow_executor.get_recent_executions.return_value = [mock_execution]
        
        pipeline._memory_manager = MagicMock()
        pipeline._memory_manager.remember.return_value = "mem_001"

        await pipeline._step_record_workflow_experience("test input", "test reply", "session_1")

        # 验证记忆存储调用
        pipeline._memory_manager.remember.assert_called_once()
        call_args = pipeline._memory_manager.remember.call_args
        assert call_args.kwargs["memory_type"] == "workflow_experience"
        assert "wf_test_001" in call_args.kwargs["content"]
        assert call_args.kwargs["metadata"]["workflow_id"] == "wf_test_001"
        
        # 验证步骤结果
        results = pipeline._step_results
        assert len(results) == 1
        assert results[0].status.value == "executed"
        assert results[0].data["recorded_count"] == 1

    @pytest.mark.asyncio
    async def test_skip_failed_execution(self):
        """跳过失败的执行记录"""
        pipeline = self._make_pipeline()
        
        mock_execution = MagicMock()
        mock_execution.status.value = "failed"
        
        pipeline._neurflow_executor = MagicMock()
        pipeline._neurflow_executor.get_recent_executions.return_value = [mock_execution]
        pipeline._memory_manager = MagicMock()

        await pipeline._step_record_workflow_experience("test input", "test reply", "session_1")

        pipeline._memory_manager.remember.assert_not_called()
        results = pipeline._step_results
        assert len(results) == 1
        assert results[0].status.value == "skipped"

    @pytest.mark.asyncio
    async def test_handles_exception(self):
        """异常处理"""
        pipeline = self._make_pipeline()
        pipeline._neurflow_executor = MagicMock()
        pipeline._neurflow_executor.get_recent_executions.side_effect = RuntimeError("boom")

        await pipeline._step_record_workflow_experience("test input", "test reply", "session_1")

        results = pipeline._step_results
        assert len(results) == 1
        assert results[0].status.value == "failed"

    @pytest.mark.asyncio
    async def test_multiple_executions_recorded(self):
        """多个执行记录"""
        pipeline = self._make_pipeline()
        
        executions = []
        for i in range(3):
            mock_exec = MagicMock()
            mock_exec.workflow_id = f"wf_{i}"
            mock_exec.id = f"exec_{i}"
            mock_exec.status.value = "completed"
            mock_exec.duration = float(i + 1)
            mock_exec.outputs = {"result": f"output_{i}"}
            mock_exec.started_at = time.time() - (i * 10)
            mock_exec.finished_at = time.time()
            mock_exec.node_results = {"n1": MagicMock(status="success")}
            executions.append(mock_exec)
        
        pipeline._neurflow_executor = MagicMock()
        pipeline._neurflow_executor.get_recent_executions.return_value = executions
        pipeline._memory_manager = MagicMock()
        pipeline._memory_manager.remember.return_value = "mem_id"

        await pipeline._step_record_workflow_experience("test input", "test reply", "session_1")

        assert pipeline._memory_manager.remember.call_count == 3
        results = pipeline._step_results
        assert results[0].data["recorded_count"] == 3
