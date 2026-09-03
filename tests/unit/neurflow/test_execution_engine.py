"""
Neurflow 执行引擎测试 — 垂直切片 6
测试工作流执行、节点调度、变量传递
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from neurova.collaboration.neurflow.execution_engine import (
    WorkflowExecutor, ExecutionStatus, ExecutionEventType, ExecutionEvent,
    get_workflow_executor
)
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge,
    WorkflowVariable, WorkflowStatus, NodeDefinition,
    ExecutionInstance, NodeExecutionResult
)


class TestWorkflowExecutor:
    """工作流执行器测试"""

    @pytest.fixture
    def executor(self):
        return WorkflowExecutor()

    @pytest.fixture
    def simple_workflow(self):
        """简单线性工作流"""
        return WorkflowDefinition(
            id="wf_test",
            name="测试工作流",
            description="用于测试的简单工作流",
            version="1.0.0",
            nodes=[
                WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
                WorkflowNode(id="llm1", type="builtin:llm", position={"x": 100, "y": 0}, config={"prompt": "Hello"}),
                WorkflowNode(id="end", type="builtin:end", position={"x": 200, "y": 0}, config={}),
            ],
            edges=[
                WorkflowEdge(id="e1", source="start", target="llm1"),
                WorkflowEdge(id="e2", source="llm1", target="end"),
            ],
            variables=[],
            tags=["test"],
            category="test",
            author="test",
            created_at=0,
            updated_at=0,
            status=WorkflowStatus.PUBLISHED
        )

    def test_create_execution_instance(self, executor, simple_workflow):
        """创建执行实例"""
        instance = executor.create_instance(
            workflow=simple_workflow,
            inputs={"query": "test"},
            user_id="user_001"
        )
        assert instance.id is not None
        assert instance.workflow_id == "wf_test"
        assert instance.inputs == {"query": "test"}
        assert instance.user_id == "user_001"
        assert instance.status == WorkflowStatus.DRAFT

    def test_get_execution_status(self, executor, simple_workflow):
        """获取执行状态"""
        instance = executor.create_instance(simple_workflow, inputs={})
        status = executor.get_status(instance.id)
        assert status == ExecutionStatus.PENDING

    def test_validate_workflow(self, executor, simple_workflow):
        """验证工作流"""
        result = executor.validate_workflow(simple_workflow)
        assert result.is_valid is True

    def test_validate_invalid_workflow(self, executor):
        """验证无效工作流"""
        bad_workflow = WorkflowDefinition(
            id="wf_bad",
            name="坏工作流",
            description="",
            version="1.0.0",
            nodes=[],  # 空节点
            edges=[],
            variables=[],
            tags=[],
            category="test",
            author="test",
            created_at=0,
            updated_at=0,
            status=WorkflowStatus.DRAFT
        )
        result = executor.validate_workflow(bad_workflow)
        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_execute_simple_workflow(self, executor, simple_workflow):
        """执行简单工作流（模拟节点执行）"""
        # Mock 节点执行
        async def mock_execute_node(node, config, context):
            if node.type == "builtin:start":
                return {"output": context.get("inputs", {})}
            elif node.type == "builtin:llm":
                return {"output": f"LLM 输出: {config.get('prompt', '')}"}
            elif node.type == "builtin:end":
                return {"output": "完成"}
            return {"output": None}

        executor._execute_node = mock_execute_node

        instance = await executor.execute(
            workflow=simple_workflow,
            inputs={"query": "test"}
        )

        assert instance.status == WorkflowStatus.COMPLETED
        assert instance.finished_at is not None
        assert len(instance.node_results) == 3  # start + llm + end

    @pytest.mark.asyncio
    async def test_execute_with_variables(self, executor):
        """执行带变量的工作流"""
        workflow = WorkflowDefinition(
            id="wf_vars",
            name="变量工作流",
            description="",
            version="1.0.0",
            nodes=[
                WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
                WorkflowNode(id="var_set", type="builtin:variable", position={"x": 100, "y": 0},
                            config={"name": "my_var", "value": "$input.query"}),
                WorkflowNode(id="end", type="builtin:end", position={"x": 200, "y": 0}, config={}),
            ],
            edges=[
                WorkflowEdge(id="e1", source="start", target="var_set"),
                WorkflowEdge(id="e2", source="var_set", target="end"),
            ],
            variables=[
                WorkflowVariable(name="my_var", type="string")
            ],
            tags=[],
            category="test",
            author="test",
            created_at=0,
            updated_at=0,
            status=WorkflowStatus.PUBLISHED
        )

        async def mock_execute_node(node, config, context):
            return {"output": config}

        executor._execute_node = mock_execute_node

        instance = await executor.execute(workflow=workflow, inputs={"query": "hello"})
        assert instance.status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_node_failure(self, executor, simple_workflow):
        """节点执行失败"""
        call_count = 0

        async def mock_execute_node(node, config, context):
            nonlocal call_count
            call_count += 1
            if node.type == "builtin:llm":
                raise RuntimeError("LLM 调用失败")
            return {"output": None}

        executor._execute_node = mock_execute_node

        instance = await executor.execute(
            workflow=simple_workflow,
            inputs={}
        )

        assert instance.status == WorkflowStatus.FAILED
        assert instance.error is not None

    @pytest.mark.asyncio
    async def test_execution_events(self, executor, simple_workflow):
        """执行事件触发"""
        events = []

        def on_event(event: ExecutionEvent):
            events.append(event)

        executor.on_event(on_event)

        async def mock_execute_node(node, config, context):
            return {"output": None}

        executor._execute_node = mock_execute_node

        await executor.execute(workflow=simple_workflow, inputs={})

        # 应有开始、节点开始/完成、结束事件
        assert len(events) >= 3
        event_types = [e.type for e in events]
        assert ExecutionEventType.WORKFLOW_STARTED in event_types
        assert ExecutionEventType.WORKFLOW_COMPLETED in event_types


class TestExecutionStatus:
    """执行状态枚举测试"""

    def test_status_values(self):
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.COMPLETED.value == "completed"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.CANCELLED.value == "cancelled"
        assert ExecutionStatus.PAUSED.value == "paused"


class TestSingleton:
    def test_get_executor(self):
        e1 = get_workflow_executor()
        e2 = get_workflow_executor()
        assert e1 is e2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])