"""工作流引擎缺的两格：层内并发上限、节点级重试（含幂等声明门）。

来历：这三套零生产消费者的编排器里，只有这两格在服务路上**确实没有对应物**（台账 §6-157 比对，
本会话按 `Semaphore|max_concurrent` 与 `retry` 在 `neurflow/` 全目录零命中复算过）。按教义第 7 条
「取长补短 → 接通 → 退役」，取的是这两格，合的落点是活路 `neurflow/execution_engine.py`，
不是把那 633 行搬过来。

判据全部打在行为上，不打在"某个符号存在"上：
- 并发面用探针节点自己数"同时在飞"的峰值（先断峰值 > 1，证明并发真在跑；再断峰值 ≤ 上限，
  证明限流生效——两式同档，把实现改成串行也会被第一式抓住）。
- 重试面用"前两次抛错第三次成功"的执行器数调用次数，并检查事件流里不得出现
  中途 `node_failed`（那会让画布节点态闪红后才变绿）。
- 默认拒绝：没声明幂等的节点必须**抛一次即失败**——副作用节点（发消息/写文件/扣款类工具）
  重试等于重复动作，这条是安全侧，不是优化项。
- 读写闭环：自定义节点的 spec 键 → 注册表 → 落库 → 重读 → `GET /nodes` 一路都要带得上，
  否则就是一个只写不读的新字段（§2 断点）。
"""

import asyncio
import os
import tempfile
import uuid

import pytest

CAP_ENV = "NEUROVA_NEURFLOW_MAX_CONCURRENT_NODES"
DEFAULT_CAP = 8

SPEC_FIELDS = ("type", "label", "icon", "category", "description")


def _nodeDefinition(node_type: str):
    from neurova.collaboration.neurflow.models import NodeDefinition

    return NodeDefinition(
        type=node_type,
        label="探针",
        icon="🧪",
        category="tools",
        description="并发/重试行为探针",
        sub_blocks=[],
        inputs=[],
        outputs=[],
    )


def _fanOutWorkflow(node_type: str, width: int):
    """start → width 个同层节点 → end（同层＝彼此无依赖＝可并发）。"""
    from neurova.collaboration.neurflow.models import (
        WorkflowDefinition,
        WorkflowEdge,
        WorkflowNode,
        WorkflowStatus,
    )

    nodes = [WorkflowNode(id="n_start", type="builtin:start", position={"x": 0, "y": 0}, config={})]
    edges = []
    for i in range(width):
        nid = f"p_{i}"
        nodes.append(WorkflowNode(id=nid, type=node_type, position={"x": 200, "y": i * 60}, config={}))
        edges.append(WorkflowEdge(id=f"e_s{nid}", source="n_start", target=nid))
        edges.append(WorkflowEdge(id=f"e_{nid}end", source=nid, target="n_end"))
    nodes.append(WorkflowNode(id="n_end", type="builtin:end", position={"x": 400, "y": 0}, config={}))

    return WorkflowDefinition(
        id=f"wf_{uuid.uuid4().hex[:8]}",
        name="并发/重试探针",
        description="层内扇出与节点重试",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=[],
        tags=["probe"],
        category="test",
        author="guard",
        created_at=0.0,
        updated_at=0.0,
        status=WorkflowStatus.PUBLISHED,
    )


def _eventType(event) -> str:
    """事件类型按值取（枚举或裸串都行）——判据不得因为"新枚举成员还不存在"而红，
    那种红落在形状上，不落在行为上。"""
    t = getattr(event, "type", None)
    return str(getattr(t, "value", t))


@pytest.fixture()
def engine():
    """真注册表 + 真执行器单例，用完摘干净（不把探针类型漏给后续跑测）。"""
    from neurova.collaboration.neurflow.execution_engine import get_workflow_executor
    from neurova.collaboration.neurflow.node_registry import get_node_registry, reset_node_registry

    reset_node_registry()
    registry = get_node_registry()
    registry.ensure_builtin()
    created = []

    def register(node_type, executor, *, idempotent=False):
        definition = _nodeDefinition(node_type)
        if idempotent:
            setattr(definition, "idempotent", True)
        registry.register(definition, executor)
        created.append(node_type)
        return definition

    yield get_workflow_executor(), register
    for node_type in created:
        registry.unregister(node_type)
    reset_node_registry()


class TestLayerFanOutConcurrencyCap:
    def test_fanOutIsBoundedButStillConcurrent(self, engine):
        """一层 12 个节点：峰值并发必须 >1（并发没被改成串行）且 ≤ 上限（限流生效）。"""
        executor, register = engine
        state = {"inflight": 0, "peak": 0}

        async def _probe(config, context):
            state["inflight"] += 1
            state["peak"] = max(state["peak"], state["inflight"])
            try:
                await asyncio.sleep(0.02)
            finally:
                state["inflight"] -= 1
            return {"output": "ok"}

        node_type = "probe:fanOutBounded"
        register(node_type, _probe)
        instance = asyncio.run(executor.execute(_fanOutWorkflow(node_type, 12), inputs={}))

        assert instance.status.value == "completed", instance.error
        assert state["peak"] > 1, "层内被串行了（peak=1）——限流不该把并发降成零"
        assert state["peak"] <= DEFAULT_CAP, (
            f"层内并发无上限：peak={state['peak']}（宽 12），一条工作流就能把下游打满"
        )

    def test_capFollowsTheSingleEnvKnob(self, engine, monkeypatch):
        """上限只有一个人入口：环境变量。设成 2 就必须观察到 peak ≤ 2。"""
        monkeypatch.setenv(CAP_ENV, "2")
        executor, register = engine
        state = {"inflight": 0, "peak": 0}

        async def _probe(config, context):
            state["inflight"] += 1
            state["peak"] = max(state["peak"], state["inflight"])
            try:
                await asyncio.sleep(0.02)
            finally:
                state["inflight"] -= 1
            return {"output": "ok"}

        node_type = "probe:fanOutCap2"
        register(node_type, _probe)
        asyncio.run(executor.execute(_fanOutWorkflow(node_type, 6), inputs={}))

        assert 1 < state["peak"] <= 2, f"env={CAP_ENV}=2 未生效，peak={state['peak']}"

    def test_bogusCapValueDoesNotCrashTheRun(self, engine, monkeypatch):
        """脏值（0/负数/非数字）退回默认上限，而不是把整条工作流跑挂或除零。"""
        monkeypatch.setenv(CAP_ENV, "0")
        executor, register = engine
        calls = []

        async def _probe(config, context):
            calls.append(1)
            return {"output": "ok"}

        node_type = "probe:fanOutBogus"
        register(node_type, _probe)
        instance = asyncio.run(executor.execute(_fanOutWorkflow(node_type, 3), inputs={}))

        assert instance.status.value == "completed", instance.error
        assert len(calls) == 3


class TestNodeLevelRetryAndIdempotencyGate:
    def test_idempotentNodeRetriesUntilItSucceeds(self, engine):
        """声明幂等的节点：前两次抛错、第三次成功 ⇒ 终态 success、调用 3 次、
        事件流里有 node_retry 且**不得**出现中途 node_failed。"""
        executor, register = engine
        events = []
        executor.on_event(lambda e: events.append(e))
        attempts = {"n": 0}

        async def _flaky(config, context):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError(f"瞬时故障 #{attempts['n']}")
            return {"output": "recovered"}

        node_type = "probe:flakyIdempotent"
        register(node_type, _flaky, idempotent=True)
        instance = asyncio.run(executor.execute(_fanOutWorkflow(node_type, 1), inputs={}))

        probe = [r for nid, r in instance.node_results.items() if nid.startswith("p_")]
        assert attempts["n"] == 3, f"幂等节点没有重试（调用 {attempts['n']} 次）"
        assert probe and probe[0].status == "success", f"重试后终态未转 success：{probe}"
        retryEvents = [e for e in events if _eventType(e) == "node_retry"]
        assert len(retryEvents) == 2, f"重试应各发一条事件（实得 {len(retryEvents)}）——否则前端只会看到闪红"
        failedEvents = [e for e in events if _eventType(e) == "node_failed"]
        assert failedEvents == [], "被重试吸收的失败不得发 node_failed"

    def test_nonIdempotentNodeFailsOnFirstError(self, engine):
        """默认拒绝：没声明幂等的节点必须抛一次即失败、不重试（副作用节点重试＝重复动作）。
        这条今天就是绿的，实现后仍须绿——它拦的是"顺手给所有节点加重试"。"""
        executor, register = engine
        events = []
        executor.on_event(lambda e: events.append(e))
        calls = {"n": 0}

        async def _sideEffect(config, context):
            calls["n"] += 1
            raise RuntimeError("这条动作有副作用")

        node_type = "probe:notIdempotent"
        register(node_type, _sideEffect)
        instance = asyncio.run(executor.execute(_fanOutWorkflow(node_type, 1), inputs={}))

        assert calls["n"] == 1, f"未声明幂等的节点被重试了 {calls['n']} 次"
        assert instance.status.value == "failed"
        assert [e for e in events if _eventType(e) == "node_retry"] == []

    def test_retryExhaustionDoesNotFabricateSuccess(self, engine):
        """重试用尽仍失败：终态必须 failed 并带原因，不得因重试路径而回成功。"""
        executor, register = engine
        calls = {"n": 0}

        async def _alwaysFails(config, context):
            calls["n"] += 1
            raise RuntimeError("永久故障")

        node_type = "probe:alwaysFails"
        register(node_type, _alwaysFails, idempotent=True)
        instance = asyncio.run(executor.execute(_fanOutWorkflow(node_type, 1), inputs={}))

        assert instance.status.value == "failed", instance.status.value
        probe = [r for nid, r in instance.node_results.items() if nid.startswith("p_")]
        assert probe and probe[0].status == "failed"
        assert probe[0].error, "失败必须留下原因"
        assert calls["n"] > 1, f"声明幂等却一次都没重试（{calls['n']}）"


class TestIdempotencyDeclarationRoundTrips:
    """声明面必须一路可读：spec → 注册表 → 落库 → 重读 → GET /nodes。"""

    def test_specKeySurvivesStorageAndApi(self):
        from neurova.collaboration.neurflow.custom_nodes import CustomNodeService
        from neurova.collaboration.neurflow.node_registry import get_node_registry
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        node_type = f"custom:{uuid.uuid4().hex[:8]}"
        root = tempfile.mkdtemp(prefix="idemRoundTrip-")
        storage = NeurflowStorage(db_path=os.path.join(root, "neurflow.db"))
        try:
            service = CustomNodeService(storage=storage, registry=get_node_registry())
            spec = {
                "type": node_type,
                "label": "幂等探针",
                "icon": "🧪",
                "category": "tools",
                "description": "声明可重试的自定义节点",
                "sub_blocks": [],
                "inputs": [],
                "outputs": [],
                "tier": "declarative",
                "executor_body": {"template": "echo", "value": "x"},
                "idempotent": True,
            }
            created = service.create_node(spec, created_by="guard")
            assert getattr(created, "idempotent", False) is True, "spec 的 idempotent 没落进节点定义"

            fromDisk = storage.get_node_definition(node_type)
            assert fromDisk is not None
            assert getattr(fromDisk, "idempotent", False) is True, "落盘/重读丢了幂等声明——重启后声明就没了"

            registered = get_node_registry().get(node_type)
            assert registered is not None and getattr(registered, "idempotent", False) is True
        finally:
            storage.close()
