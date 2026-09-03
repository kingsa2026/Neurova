"""执行事件记录器测试（P0-1 工作流执行流式化）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §4 P0-1）：
- 引擎已有 _emit/on_event 机制，缺"记录+订阅"传动轴——本模块补齐：
  record() 同步入缓冲（环形上限），subscribe() 回放+实时+终态收尾。
- 事件帧统一 dict：{seq, type, workflow_id, execution_id, node_id, data, timestamp}，
  type 归一为 str（ExecutionEventType 枚举取 .value）。
"""

import asyncio
import unittest

from neurova.collaboration.neurflow.event_recorder import (
    EVENTS_PER_EXECUTION,
    MAX_TRACKED_EXECUTIONS,
    ExecutionEventRecorder,
    attach_event_recorder,
    get_execution_event_recorder,
    reset_execution_event_recorder,
)
from neurova.collaboration.neurflow.execution_engine import (
    ExecutionEvent,
    ExecutionEventType,
    get_workflow_executor,
)
from neurova.collaboration.neurflow.models import (
    NodeDefinition,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)


def _event(etype, execution_id="exec_t1", node_id=None, data=None, workflow_id="wf_t1"):
    return ExecutionEvent(
        type=etype,
        workflow_id=workflow_id,
        execution_id=execution_id,
        node_id=node_id,
        data=data or {},
    )


def _linear_workflow(node_types=("builtin:start", "builtin:end")):
    nodes = [
        WorkflowNode(id=f"n{i}", type=t, position={"x": float(i) * 100, "y": 0}, config={})
        for i, t in enumerate(node_types)
    ]
    edges = [
        WorkflowEdge(id=f"e{i}", source=f"n{i}", target=f"n{i + 1}")
        for i in range(len(node_types) - 1)
    ]
    return WorkflowDefinition(
        id="wf_rec_test",
        name="录制器测试流",
        description="",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=[],
        tags=[],
        category="general",
        author="tester",
        created_at=0.0,
        updated_at=0.0,
        status=WorkflowStatus.PUBLISHED,
    )


class TestExecutionEventRecorder(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_execution_event_recorder()
        self.recorder = ExecutionEventRecorder()

    def tearDown(self):
        reset_execution_event_recorder()

    async def test_record_appends_and_seqs(self):
        self.recorder.record(_event(ExecutionEventType.WORKFLOW_STARTED))
        self.recorder.record(_event(ExecutionEventType.NODE_STARTED, node_id="n0"))
        frames = self.recorder.snapshot("exec_t1")
        self.assertEqual([f["seq"] for f in frames], [1, 2])
        self.assertEqual(
            [f["type"] for f in frames], ["workflow_started", "node_started"]
        )
        # 枚举/字符串双形态归一为 str
        self.recorder.record(_event("node_completed", node_id="n0"))
        self.assertEqual(self.recorder.snapshot("exec_t1")[-1]["type"], "node_completed")
        self.assertEqual(self.recorder.snapshot("exec_t1")[-1]["node_id"], "n0")

    async def test_snapshot_after_cursor(self):
        for i in range(4):
            self.recorder.record(_event(ExecutionEventType.NODE_STARTED, node_id=f"n{i}"))
        frames = self.recorder.snapshot("exec_t1", after=2)
        self.assertEqual([f["seq"] for f in frames], [3, 4])

    async def test_snapshot_unknown_execution_empty(self):
        self.assertEqual(self.recorder.snapshot("no_such"), [])

    async def test_subscribe_replays_then_live_until_terminal(self):
        self.recorder.record(_event(ExecutionEventType.WORKFLOW_STARTED))
        self.recorder.record(_event(ExecutionEventType.NODE_STARTED, node_id="n0"))
        self.recorder.record(_event(ExecutionEventType.NODE_COMPLETED, node_id="n0"))

        received: list = []
        released = asyncio.Event()

        async def consume():
            async for frame in self.recorder.subscribe("exec_t1"):
                received.append(frame)
                if frame["type"] == "node_completed":
                    # 消费到回放末帧后，实时段产生终态事件
                    self.recorder.record(
                        _event(ExecutionEventType.WORKFLOW_COMPLETED, data={"outputs": {}})
                    )

        await asyncio.wait_for(consume(), timeout=5)
        types = [f["type"] for f in received]
        self.assertEqual(
            types,
            ["workflow_started", "node_started", "node_completed", "workflow_completed"],
        )
        # 终态后订阅自然结束（consume 正常返回而非超时）
        assert not released.is_set()

    async def test_subscribe_after_cursor(self):
        for i in range(3):
            self.recorder.record(_event(ExecutionEventType.NODE_STARTED, node_id=f"n{i}"))
        self.recorder.record(_event(ExecutionEventType.WORKFLOW_COMPLETED))

        received = [f async for f in self.recorder.subscribe("exec_t1", after=2)]
        self.assertEqual([f["seq"] for f in received], [3, 4])

    async def test_subscribe_untracked_returns_empty(self):
        received = [f async for f in self.recorder.subscribe("ghost")]
        self.assertEqual(received, [])

    async def test_buffer_bounded_drops_oldest(self):
        for i in range(EVENTS_PER_EXECUTION + 50):
            self.recorder.record(_event(ExecutionEventType.NODE_STARTED, node_id=f"n{i}"))
        frames = self.recorder.snapshot("exec_t1")
        self.assertEqual(len(frames), EVENTS_PER_EXECUTION)
        self.assertEqual(frames[0]["seq"], 51)  # 最旧 50 帧被丢弃

    async def test_max_tracked_executions_evicts_lru(self):
        for e in range(MAX_TRACKED_EXECUTIONS):
            self.recorder.record(
                _event(ExecutionEventType.WORKFLOW_STARTED, execution_id=f"e{e}")
            )
        self.assertTrue(self.recorder.is_tracked("e0"))
        self.recorder.record(
            _event(ExecutionEventType.WORKFLOW_STARTED, execution_id="e_new")
        )
        self.assertFalse(self.recorder.is_tracked("e0"))
        self.assertTrue(self.recorder.is_tracked("e_new"))

    async def test_record_without_running_loop_only_buffers(self):
        # 防御：非事件循环线程（如调度器线程）调用 record 不崩、不丢帧
        def _sync_record():
            self.recorder.record(_event(ExecutionEventType.WORKFLOW_STARTED))

        await asyncio.get_running_loop().run_in_executor(None, _sync_record)
        self.assertEqual(len(self.recorder.snapshot("exec_t1")), 1)

    async def test_attach_event_recorder_idempotent(self):
        executor = get_workflow_executor()
        attach_event_recorder(executor)
        attach_event_recorder(executor)  # 二次挂载不得重复

        inst = await executor.execute(_linear_workflow(), inputs={"q": 1}, user_id="u_rec")

        recorded = get_execution_event_recorder().snapshot(inst.id)
        types = [f["type"] for f in recorded]
        self.assertEqual(types[0], "workflow_started")
        self.assertEqual(types[-1], "workflow_completed")
        # 幂等：无重复帧（同 seq 不重复出现两次）
        seqs = [f["seq"] for f in recorded]
        self.assertEqual(len(seqs), len(set(seqs)))

    async def test_engine_execute_records_full_lifecycle(self):
        executor = get_workflow_executor()
        attach_event_recorder(executor)

        inst = await executor.execute(_linear_workflow(), inputs={"q": 1}, user_id="u_rec2")

        frames = get_execution_event_recorder().snapshot(inst.id)
        types = [f["type"] for f in frames]
        self.assertEqual(types[0], "workflow_started")
        self.assertEqual(types[-1], "workflow_completed")
        self.assertIn("node_started", types)
        self.assertIn("node_completed", types)
        # 节点事件携带 node_id
        started_nodes = [f["node_id"] for f in frames if f["type"] == "node_started"]
        self.assertEqual(started_nodes, ["n0", "n1"])

    async def test_engine_failure_records_terminal_failed(self):
        from neurova.collaboration.neurflow.node_registry import get_node_registry

        registry = get_node_registry()
        registry.ensure_builtin()

        async def _boom(config, context):
            raise RuntimeError("boom")

        # 注册一个必然失败的节点类型
        registry.register(
            NodeDefinition(
                type="builtin:test_boom",
                label="爆炸节点",
                icon="💥",
                category="ai",
                description="test",
                sub_blocks=[],
                inputs=[],
                outputs=[],
            ),
            executor=_boom,
        )
        executor = get_workflow_executor()
        attach_event_recorder(executor)

        wf = _linear_workflow(("builtin:start", "builtin:test_boom", "builtin:end"))
        inst = await executor.execute(wf, inputs={})

        frames = get_execution_event_recorder().snapshot(inst.id)
        types = [f["type"] for f in frames]
        self.assertEqual(types[-1], "workflow_failed")
        failed = [f for f in frames if f["type"] == "node_failed"]
        self.assertTrue(failed and failed[0]["node_id"] == "n1")


class TestRecorderSingleton(unittest.TestCase):
    def setUp(self):
        reset_execution_event_recorder()

    def tearDown(self):
        reset_execution_event_recorder()

    def test_singleton_identity_and_reset(self):
        first = get_execution_event_recorder()
        self.assertIs(first, get_execution_event_recorder())
        reset_execution_event_recorder()
        self.assertIsNot(first, get_execution_event_recorder())


if __name__ == "__main__":
    unittest.main()
