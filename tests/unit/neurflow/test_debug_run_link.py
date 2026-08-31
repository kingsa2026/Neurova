"""
修复① — execute() 内置断点/单步测试（画布 run 链路复活）

契约：WorkflowExecutor.execute 新增 debug_session: Optional[DebugSession] = None
- 命中断点：节点执行前 emit BREAKPOINT_HIT 并阻塞至 resume
- 无 debug_session：零事件、零开销（行为与旧完全一致）
- step_mode：每节点完成后 emit BREAKPOINT_HIT 并等待 resume

TDD：先红后绿。RecordingExecutor 记录 _execute_node 调用顺序。
"""
import asyncio

import pytest

from neurova.collaboration.neurflow.execution_engine import (
    DebugSession,
    ExecutionEventType,
    WorkflowExecutor,
)
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
)


def _linear_workflow():
    return WorkflowDefinition(
        id="wf_dbg_run",
        name="debug run",
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


class RecordingExecutor(WorkflowExecutor):
    """记录 _execute_node 的节点顺序（验证断点阻塞语义）。"""

    def __init__(self):
        super().__init__()
        self.executed: list[str] = []

    async def _execute_node(self, node, resolved_config, ctx):
        self.executed.append(node.id)
        return {"status": "success", "output": "ok"}


class TestExecuteWithDebugSession:
    @pytest.mark.asyncio
    async def test_breakpoint_blocks_until_resume(self):
        executor = RecordingExecutor()
        events: list = []
        executor.on_event(events.append)

        ds = DebugSession(breakpoints={"llm1"})
        task = asyncio.create_task(
            executor.execute(workflow=_linear_workflow(), inputs={}, debug_session=ds)
        )

        # 给执行器时间推进到断点
        await asyncio.sleep(0.05)
        hits = [e for e in events if e.type == ExecutionEventType.BREAKPOINT_HIT]
        assert len(hits) == 1 and hits[0].node_id == "llm1"
        # 断点阻塞：llm1 尚未真实执行
        assert "llm1" not in executor.executed

        ds.resume()
        instance = await asyncio.wait_for(task, timeout=5)
        assert instance.status.value == "completed"
        assert executor.executed == ["start", "llm1", "end"]

    @pytest.mark.asyncio
    async def test_no_debug_session_no_breakpoint_events(self):
        executor = RecordingExecutor()
        events: list = []
        executor.on_event(events.append)

        instance = await executor.execute(workflow=_linear_workflow(), inputs={})
        assert instance.status.value == "completed"
        assert not [e for e in events if e.type == ExecutionEventType.BREAKPOINT_HIT]
        assert executor.executed == ["start", "llm1", "end"]

    @pytest.mark.asyncio
    async def test_step_mode_pauses_after_each_node(self):
        executor = RecordingExecutor()
        events: list = []
        executor.on_event(events.append)

        ds = DebugSession(step_mode="over")
        task = asyncio.create_task(
            executor.execute(workflow=_linear_workflow(), inputs={}, debug_session=ds)
        )

        # 逐节点放行：每收到一个 BREAKPOINT_HIT 就 resume
        for _ in range(6):
            await asyncio.sleep(0.05)
            hits = [e for e in events if e.type == ExecutionEventType.BREAKPOINT_HIT]
            if len(hits) >= 3:
                break
            if hits:
                ds.resume()

        # 兜底再 resume 一次防悬挂
        ds.resume()
        instance = await asyncio.wait_for(task, timeout=5)
        assert instance.status.value == "completed"
        assert executor.executed == ["start", "llm1", "end"]
        assert len([e for e in events if e.type == ExecutionEventType.BREAKPOINT_HIT]) >= 3
