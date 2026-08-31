"""
遗留② — 执行引擎从节点 config 提取 mock_output 测试

契约：WorkflowExecutor._execute_single_node
- 节点 config["mock_output"] 存在（非 None）→ 直接短路返回，不调真实 executor
- WorkflowNode.mock_output 字段优先于 config 提取（两者兼容）
- mock 值可为 0/""/False/{}（is not None 判定，非 truthy）

TDD：先红后绿。CountingExecutor 记录 _execute_node 调用次数。
"""
import pytest

from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
)


def _llm_workflow(mock_config=None):
    config = {"prompt": "hi"}
    if mock_config is not None:
        config["mock_output"] = mock_config
    return WorkflowDefinition(
        id="wf_mock_cfg",
        name="mock via config",
        description="",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="llm1", type="builtin:llm", position={"x": 50, "y": 0}, config=config),
            WorkflowNode(id="end", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="llm1"),
            WorkflowEdge(id="e2", source="llm1", target="end"),
        ],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
    )


class CountingExecutor(WorkflowExecutor):
    def __init__(self):
        super().__init__()
        self.node_calls = 0

    async def _execute_node(self, node, resolved_config, ctx):
        self.node_calls += 1
        return {"status": "success", "output": "REAL_EXECUTED"}


class TestMockFromConfig:
    @pytest.mark.asyncio
    async def test_mock_in_config_short_circuits(self):
        """config.mock_output 存在 → llm1 短路；start/end 正常执行（共 2 次）"""
        executor = CountingExecutor()
        instance = await executor.execute(
            workflow=_llm_workflow(mock_config={"answer": "MOCKED"}), inputs={}
        )
        assert instance.status.value == "completed"
        assert executor.node_calls == 2  # start + end（llm1 被短路）
        assert instance.node_results["llm1"].output == {"answer": "MOCKED"}

    @pytest.mark.asyncio
    async def test_falsy_mock_values_still_short_circuit(self):
        executor = CountingExecutor()
        instance = await executor.execute(
            workflow=_llm_workflow(mock_config=0), inputs={}
        )
        assert executor.node_calls == 2  # llm1 短路
        assert instance.node_results["llm1"].output == 0

    @pytest.mark.asyncio
    async def test_no_mock_calls_real_executor(self):
        executor = CountingExecutor()
        instance = await executor.execute(workflow=_llm_workflow(), inputs={})
        assert executor.node_calls == 3  # start + llm1 + end 全部真实执行
        assert instance.node_results["llm1"].output == "REAL_EXECUTED"

    @pytest.mark.asyncio
    async def test_node_field_mock_takes_precedence(self):
        """WorkflowNode.mock_output 字段优先（config 无 mock 也短路）"""
        executor = CountingExecutor()
        wf = _llm_workflow()
        wf.nodes[1].mock_output = "FIELD_MOCK"
        instance = await executor.execute(workflow=wf, inputs={})
        assert executor.node_calls == 2  # llm1 短路
        assert instance.node_results["llm1"].output == "FIELD_MOCK"