"""
Neurflow 执行引擎修复测试
测试 ExecutionEvent 重构和公共 API 使用
"""
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

from neurova.collaboration.neurflow.execution_engine import (
    ExecutionStatus, ExecutionEventType, ExecutionEvent,
    WorkflowExecutor, get_workflow_executor
)
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge,
    WorkflowStatus, NodeDefinition
)


class TestExecutionEventType:
    """ExecutionEventType 枚举测试"""

    def test_enum_values(self):
        """测试枚举值"""
        assert ExecutionEventType.WORKFLOW_STARTED.value == "workflow_started"
        assert ExecutionEventType.WORKFLOW_COMPLETED.value == "workflow_completed"
        assert ExecutionEventType.WORKFLOW_FAILED.value == "workflow_failed"
        assert ExecutionEventType.NODE_STARTED.value == "node_started"
        assert ExecutionEventType.NODE_COMPLETED.value == "node_completed"
        assert ExecutionEventType.NODE_FAILED.value == "node_failed"
        assert ExecutionEventType.VARIABLE_SET.value == "variable_set"
        assert ExecutionEventType.PAUSED.value == "paused"
        assert ExecutionEventType.RESUMED.value == "resumed"

    def test_enum_members(self):
        """测试枚举成员数量"""
        assert len(ExecutionEventType) == 13  # 10 + P0 调试事件 3 个（BREAKPOINT_HIT/STEP_ADVANCED/VARIABLE_SCOPED）

    def test_enum_is_string(self):
        """测试枚举值是字符串"""
        for event_type in ExecutionEventType:
            assert isinstance(event_type.value, str)


class TestExecutionEvent:
    """ExecutionEvent 数据类测试"""

    def test_create_with_enum(self):
        """测试使用枚举创建事件"""
        event = ExecutionEvent(
            type=ExecutionEventType.WORKFLOW_STARTED,
            workflow_id="wf_1",
            execution_id="exec_1"
        )

        assert event.type == ExecutionEventType.WORKFLOW_STARTED
        assert event.workflow_id == "wf_1"
        assert event.execution_id == "exec_1"
        assert event.node_id is None
        assert event.data == {}
        assert event.timestamp > 0

    def test_create_with_string(self):
        """测试使用字符串创建事件（向后兼容）"""
        event = ExecutionEvent(
            type="workflow_started",
            workflow_id="wf_1",
            execution_id="exec_1"
        )

        assert event.type == "workflow_started"

    def test_create_with_all_fields(self):
        """测试所有字段"""
        event = ExecutionEvent(
            type=ExecutionEventType.NODE_COMPLETED,
            workflow_id="wf_1",
            execution_id="exec_1",
            node_id="node_1",
            data={"result": "success"},
            timestamp=1234567890.0
        )

        assert event.node_id == "node_1"
        assert event.data == {"result": "success"}
        assert event.timestamp == 1234567890.0


class TestExecutionStatus:
    """ExecutionStatus 枚举测试"""

    def test_enum_values(self):
        """测试枚举值"""
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.COMPLETED.value == "completed"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.CANCELLED.value == "cancelled"
        assert ExecutionStatus.PAUSED.value == "paused"


class TestWorkflowExecutorPublicAPI:
    """测试 WorkflowExecutor 使用公共 API"""

    @pytest.fixture
    def executor(self):
        """创建执行器实例"""
        return WorkflowExecutor()

    @pytest.fixture
    def simple_workflow(self):
        """简单工作流"""
        import time
        return WorkflowDefinition(
            id="wf_1",
            name="测试工作流",
            description="简单测试工作流",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="start",
                    type="builtin:start",
                    label="开始",
                    position={"x": 0, "y": 0},
                    config={}
                ),
                WorkflowNode(
                    id="end",
                    type="builtin:end",
                    label="结束",
                    position={"x": 200, "y": 0},
                    config={}
                )
            ],
            edges=[
                WorkflowEdge(
                    id="e1",
                    source="start",
                    target="end"
                )
            ],
            variables=[],
            tags=["test"],
            category="testing",
            author="test_user",
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.DRAFT
        )

    @pytest.mark.asyncio
    async def test_execute_uses_public_api(self, executor, simple_workflow):
        """测试 execute 使用公共 API 而非私有属性"""
        with patch.object(executor._dag_validator, 'get_execution_path') as mock_get_path:
            mock_get_path.return_value = ["start", "end"]

            instance = await executor.execute(
                workflow=simple_workflow,
                inputs={"query": "test"}
            )

            # 验证调用了公共方法而非私有属性
            mock_get_path.assert_called_once()
            assert instance.status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_handles_sort_failure(self, executor, simple_workflow):
        """测试拓扑排序失败处理"""
        with patch.object(executor._dag_validator, 'get_execution_path') as mock_get_path:
            mock_get_path.return_value = []  # 返回空列表表示失败

            instance = await executor.execute(
                workflow=simple_workflow,
                inputs={"query": "test"}
            )

            # 工作流应该验证失败（因为有环）
            assert instance.status == WorkflowStatus.FAILED

    def test_emit_uses_enum(self, executor):
        """测试事件发射使用枚举"""
        received_events = []

        def handler(event):
            received_events.append(event)

        executor.on_event(handler)

        # 发射事件
        executor._emit(ExecutionEvent(
            type=ExecutionEventType.WORKFLOW_STARTED,
            workflow_id="wf_1",
            execution_id="exec_1"
        ))

        assert len(received_events) == 1
        assert received_events[0].type == ExecutionEventType.WORKFLOW_STARTED

    def test_emit_backward_compatible(self, executor):
        """测试事件发射向后兼容字符串"""
        received_events = []

        def handler(event):
            received_events.append(event)

        executor.on_event(handler)

        # 使用字符串发射事件
        executor._emit(ExecutionEvent(
            type="workflow_started",
            workflow_id="wf_1",
            execution_id="exec_1"
        ))

        assert len(received_events) == 1
        assert received_events[0].type == "workflow_started"


class TestWorkflowExecutorIntegration:
    """执行器集成测试"""

    @pytest.fixture
    def executor(self):
        """创建执行器实例"""
        return WorkflowExecutor()

    @pytest.fixture
    def llm_workflow(self):
        """LLM 节点工作流"""
        import time
        return WorkflowDefinition(
            id="wf_llm",
            name="LLM 工作流",
            description="LLM 测试工作流",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="start",
                    type="builtin:start",
                    label="开始",
                    position={"x": 0, "y": 0},
                    config={}
                ),
                WorkflowNode(
                    id="llm",
                    type="builtin:llm",
                    label="LLM",
                    position={"x": 100, "y": 0},
                    config={
                        "prompt": "处理: $input.query",
                        "model": "gpt-4"
                    }
                ),
                WorkflowNode(
                    id="end",
                    type="builtin:end",
                    label="结束",
                    position={"x": 200, "y": 0},
                    config={}
                )
            ],
            edges=[
                WorkflowEdge(id="e1", source="start", target="llm"),
                WorkflowEdge(id="e2", source="llm", target="end")
            ],
            variables=[],
            tags=["test", "llm"],
            category="testing",
            author="test_user",
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.DRAFT
        )

    @pytest.mark.asyncio
    async def test_workflow_events_emitted(self, executor, llm_workflow):
        """测试工作流事件正确发射"""
        received_events = []

        def handler(event):
            received_events.append(event.type if isinstance(event.type, str) else event.type.value)

        executor.on_event(handler)

        with patch.object(executor, '_execute_node', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {"output": "LLM 结果"}

            await executor.execute(
                workflow=llm_workflow,
                inputs={"query": "测试"}
            )

        # 验证事件序列
        assert "workflow_started" in received_events
        assert "node_started" in received_events
        assert "node_completed" in received_events
        assert "workflow_completed" in received_events

    @pytest.mark.asyncio
    async def test_node_failure_stops_workflow(self, executor, llm_workflow):
        """测试节点失败停止工作流"""
        received_events = []

        def handler(event):
            received_events.append(event)

        executor.on_event(handler)

        with patch.object(executor, '_execute_node', new_callable=AsyncMock) as mock_execute:
            mock_execute.side_effect = RuntimeError("LLM 调用失败")

            instance = await executor.execute(
                workflow=llm_workflow,
                inputs={"query": "测试"}
            )

        assert instance.status == WorkflowStatus.FAILED
        assert "LLM 调用失败" in instance.error

        # 验证失败事件
        failed_events = [e for e in received_events if e.type in [
            ExecutionEventType.WORKFLOW_FAILED,
            ExecutionEventType.NODE_FAILED
        ]]
        assert len(failed_events) >= 1


class TestWorkflowExecutorSingleton:
    """单例测试"""

    def test_singleton_pattern(self):
        """测试单例模式"""
        executor1 = get_workflow_executor()
        executor2 = get_workflow_executor()
        assert executor1 is executor2

    def test_reset_singleton(self):
        """测试重置单例"""
        from neurova.collaboration.neurflow.execution_engine import _workflow_executor

        # 重置全局变量
        import neurova.collaboration.neurflow.execution_engine as module
        module._workflow_executor = None

        executor1 = get_workflow_executor()
        executor2 = get_workflow_executor()
        assert executor1 is executor2

        # 清理
        module._workflow_executor = None
