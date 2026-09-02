"""
Checkpoint/Probe/Resume 测试（借鉴 langflow lfx/graph/checkpoint）

契约：
- execute(instance=..., resume=True)：续跑同一实例——
  已 success 节点不重跑（executor 记录只执行未完成节点），
  variables 从 instance 恢复，skipped 集从 node_results 重建
- 节点级增量落盘：execute 完成后 checkpoint_store.get_execution 可见
  node_results/variables（注入 tmp store 断言）
- probe：execution_checkpoint_summary(instance) 纯函数输出
  {completed:[], pending:[], failed:[], variables:{}} 摘要
TDD：先红后绿（引擎当前无 resume 语义）。
"""
import pytest

from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
    ExecutionInstance,
    NodeExecutionResult,
)


def _linear(workflow_id="wf_ckpt"):
    return WorkflowDefinition(
        id=workflow_id,
        name="ckpt",
        description="",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="llm1", type="builtin:llm", position={"x": 50, "y": 0}, config={"prompt": "hi"}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="llm1"),
            WorkflowEdge(id="e2", source="llm1", target="end"),
        ],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
    )


class TrackExecutor(WorkflowExecutor):
    """记录执行过的节点（跳过语义验证）"""

    def __init__(self):
        super().__init__()
        self.executed: list[str] = []

    async def _execute_node(self, node, resolved_config, ctx):
        self.executed.append(node.id)
        return {"status": "success", "output": f"out-{node.id}"}


class TestResumeSkipsCompleted:
    @pytest.mark.asyncio
    async def test_resume_keeps_completed_results(self, tmp_path):
        """先失败带部分成功 → resume：成功节点不重跑，变量/结果保留"""
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        store = NeurflowStorage(db_path=str(tmp_path / "ckpt.db"))
        executor = TrackExecutor()

        wf = _linear()
        # 模拟第一次执行到 llm1 失败：start 已成功
        instance = ExecutionInstance(
            id="exec_ckpt_1",
            workflow_id=wf.id,
            status=WorkflowStatus.FAILED,
            inputs={"query": "hello"},
            variables={"user_msg": "hello"},
            error="节点 llm1 失败",
        )
        instance.node_results["start"] = NodeExecutionResult(
            node_id="start", status="success", output={"ok": True},
            started_at=0, finished_at=1, duration=1,
        )

        await executor.execute(workflow=wf, inputs={"query": "hello"},
                               instance=instance, resume=True)

        assert instance.status.value == "completed"
        # start 不重跑；仅 llm1、end 执行
        assert executor.executed == ["llm1", "end"]
        # 结果保留 + 新结果并入
        assert instance.node_results["start"].output == {"ok": True}
        assert instance.node_results["llm1"].output == "out-llm1"
        assert instance.variables["user_msg"] == "hello"

    @pytest.mark.asyncio
    async def test_without_resume_reruns_all(self, tmp_path):
        """无 resume 时按原语义全跑（向后兼容）"""
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        store = NeurflowStorage(db_path=str(tmp_path / "ckpt2.db"))
        executor = TrackExecutor()
        instance = ExecutionInstance(
            id="exec_ckpt_2", workflow_id="wf_ckpt",
            status=WorkflowStatus.FAILED, inputs={}, variables={},
        )
        instance.node_results["start"] = NodeExecutionResult(
            node_id="start", status="success", output={"ok": True},
            started_at=0, finished_at=1, duration=1,
        )
        await executor.execute(workflow=_linear(), inputs={}, instance=instance)

        assert executor.executed == ["start", "llm1", "end"]


class TestIncrementalCheckpoint:
    @pytest.mark.asyncio
    async def test_checkpoint_persists_node_results(self, tmp_path):
        """执行完成（或失败）后 checkpoint store 可见节点级结果与变量"""
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        store = NeurflowStorage(db_path=str(tmp_path / "ckpt3.db"))
        executor = TrackExecutor()
        instance = ExecutionInstance(
            id="exec_ckpt_3", workflow_id="wf_ckpt",
            status=WorkflowStatus.RUNNING, inputs={}, variables={},
        )
        await executor.execute(workflow=_linear(), inputs={}, instance=instance,
                               checkpoint_store=store)

        stored = store.get_checkpoint("exec_ckpt_3")
        assert stored is not None
        assert stored.status.value == "completed"
        assert "start" in stored.node_results and "llm1" in stored.node_results


class TestProbeSummary:
    def test_summary_pure_function(self):
        from neurova.collaboration.neurflow.checkpoint import execution_checkpoint_summary

        instance = ExecutionInstance(
            id="exec_probe", workflow_id="wf_ckpt", status=WorkflowStatus.FAILED,
            inputs={}, variables={"a": 1}, error="boom",
        )
        instance.node_results["start"] = NodeExecutionResult(
            node_id="start", status="success", output={"ok": 1},
            started_at=0, finished_at=1, duration=1,
        )
        instance.node_results["llm1"] = NodeExecutionResult(
            node_id="llm1", status="failed", output=None, error="boom",
            started_at=1, finished_at=2, duration=1,
        )

        s = execution_checkpoint_summary(instance, ["start", "llm1", "end"])
        assert s["completed"] == ["start"]
        assert s["failed"] == ["llm1"]
        assert s["pending"] == ["end"]
        assert s["variables"] == {"a": 1}
        assert s["error"] == "boom"