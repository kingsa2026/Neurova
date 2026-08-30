"""
NeurFlow 遗留① — subflow 引擎接线测试

契约（WorkflowExecutor.execute 新增参数）：
- subflow_depth: int = 0 / subflow_chain: Optional[List[str]] = None /
  subflow_loader: Optional[Callable] = None
- 节点 ctx 注入 harness：
  - "_subflow_depth"（透传 depth）
  - "_subflow_chain"（chain + [当前 workflow_id]，含当前）
  - "subflow_loader"（显式传入优先，否则引擎默认 loader）
  - "subflow_executor"（闭包：递归 execute，depth+1、chain 透传）
- 显式 subflow_loader 优先于默认

TDD：先红后绿。子类覆盖 _execute_node 捕获 ctx（无 monkeypatch）。
"""
import pytest
from unittest.mock import MagicMock

from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
)


def _single_var_workflow(workflow_id="wf_main"):
    return WorkflowDefinition(
        id=workflow_id,
        name="harness",
        description="",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="v1", type="builtin:variable", position={"x": 50, "y": 0},
                         config={"name": "k", "value": "v"}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="v1"),
            WorkflowEdge(id="e2", source="v1", target="end"),
        ],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
    )


class CapturingExecutor(WorkflowExecutor):
    """捕获每次节点执行的 ctx（子类覆盖，不 monkeypatch）。"""

    def __init__(self):
        super().__init__()
        self.seen = []

    async def _execute_node(self, node, resolved_config, ctx):
        self.seen.append(dict(ctx))
        return {"status": "success", "output": "ok"}


class TestSubflowHarnessInjection:
    @pytest.mark.asyncio
    async def test_default_harness_injected(self):
        executor = CapturingExecutor()
        await executor.execute(workflow=_single_var_workflow(), inputs={})

        ctx = executor.seen[0]
        assert ctx["_subflow_depth"] == 0
        assert ctx["_subflow_chain"] == ["wf_main"]  # 含当前
        assert callable(ctx["subflow_loader"])
        assert callable(ctx["subflow_executor"])

    @pytest.mark.asyncio
    async def test_depth_and_chain_passed_through(self):
        executor = CapturingExecutor()
        await executor.execute(
            workflow=_single_var_workflow("wf_sub"),
            inputs={},
            subflow_depth=2,
            subflow_chain=["wf_root", "wf_mid"],
        )
        ctx = executor.seen[0]
        assert ctx["_subflow_depth"] == 2
        assert ctx["_subflow_chain"] == ["wf_root", "wf_mid", "wf_sub"]

    @pytest.mark.asyncio
    async def test_explicit_loader_wins(self):
        executor = CapturingExecutor()
        fake_loader = MagicMock(return_value=None)
        await executor.execute(
            workflow=_single_var_workflow(),
            inputs={},
            subflow_loader=fake_loader,
        )
        assert executor.seen[0]["subflow_loader"] is fake_loader

    @pytest.mark.asyncio
    async def test_subflow_executor_recurses_with_depth_plus_one(self):
        """subflow_executor 闭包递归 execute：depth+1 + chain 含目标"""
        executor = CapturingExecutor()

        fake_wf = _single_var_workflow("wf_child")
        fake_loader = MagicMock(return_value=fake_wf)

        await executor.execute(
            workflow=_single_var_workflow("wf_parent"),
            inputs={},
            subflow_loader=fake_loader,
        )

        parent_ctx = executor.seen[0]
        # 用主 ctx 的 subflow_executor 模拟 subflow 节点调用
        instance = await parent_ctx["subflow_executor"](
            fake_wf, {"k": "v"}, {"depth": 1, "chain": ["wf_parent"]}
        )
        assert instance is not None
        # 子执行 ctx（父流 3 节点后追加）：depth=1、chain=[wf_parent, wf_child]
        assert len(executor.seen) >= 6
        child_ctx = executor.seen[-1]
        assert child_ctx["_subflow_depth"] == 1
        assert child_ctx["_subflow_chain"] == ["wf_parent", "wf_child"]

    @pytest.mark.asyncio
    async def test_default_loader_returns_none_for_ghost(self):
        """默认 loader：不存在的工作流返回 None（不抛异常）"""
        executor = CapturingExecutor()
        await executor.execute(workflow=_single_var_workflow(), inputs={})
        loader = executor.seen[0]["subflow_loader"]
        assert loader("wf_ghost_does_not_exist_9x7y") is None