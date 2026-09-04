"""P1-7 双轨引擎收敛（TDD — Dify 对比报告 §3.1/§4 P1-7）。

背景：execution_engine/workflow_engine.py（CogArch 1.0 任务型线性链）
与 collaboration/neurflow/（真 DAG 引擎）双轨并存。审计结论：旧引擎的
唯一活跃消费路径是 shared_core.ExecutionEngine.execute_workflow——
生产侧零注册者（模板/测试自产自销），属"空转双轨"。

收敛契约：
1. ExecutionEngine.execute_workflow 转发 neurflow 唯一引擎：
   按 workflow_id 从 neurflow storage 加载已发布工作流执行；
   neurflow 不可用/工作流不存在时回退旧引擎（兼容期，不删旧代码）
2. 旧 WorkflowEngine 冻结声明：模块 docstring 明确 deprecated 指向
   neurflow；API 冻结不再扩展（防误用扩散）
3. 转发结果可区分（metadata.source="neurflow"/"legacy"），可观测
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


class TestForwarding:
    @pytest.mark.asyncio
    async def test_execute_workflow_forwards_to_neurflow(self, tmp_path):
        """注册在 neurflow storage 的工作流经 shared_core 入口执行成功"""
        import time as _time

        from neurova.collaboration.neurflow.storage import NeurflowStorage
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
        )
        from neurova.shared_core.execution_engine import ExecutionEngine

        storage = NeurflowStorage(str(tmp_path / "neurflow.db"))
        wf = WorkflowDefinition(
            id="wf_conv_1", name="收敛样例", description="", version="1.0.0",
            nodes=[
                WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0}, config={"fields": []}),
                WorkflowNode(id="e", type="builtin:end", position={"x": 100, "y": 0}, config={}),
            ],
            edges=[WorkflowEdge(id="e1", source="s", target="e")],
            variables=[], tags=[], category="general", author="t",
            created_at=_time.time(), updated_at=_time.time(),
            status=WorkflowStatus.PUBLISHED,
        )
        storage.save_workflow(wf)

        engine = ExecutionEngine()
        result, meta = await engine.execute_workflow("wf_conv_1", {"q": 1}, storage=storage)
        assert meta["source"] == "neurflow"
        assert meta["status"] == "completed"

    @pytest.mark.asyncio
    async def test_forward_falls_back_to_legacy_when_not_in_neurflow(self):
        """neurflow 无此工作流 → 回退旧引擎（兼容期语义）"""
        from neurova.shared_core.execution_engine import ExecutionEngine
        from neurova.execution_engine.workflow_engine import (
            WorkflowDefinition as LegacyDef,
            WorkflowNode as LegacyNode,
            NodeType,
        )

        engine = ExecutionEngine()
        # 旧引擎注册一个可执行工作流（task 节点挂同步 handler）
        node = LegacyNode(node_id="n1", name="t", node_type=NodeType.TASK, action="noop_tool")
        legacy_wf = LegacyDef(
            workflow_id="wf_legacy_1", name="legacy",
            nodes={"n1": node}, start_node="n1",
        )
        engine._workflow_engine.register_workflow(legacy_wf)

        async def _noop(**params):
            return "ok"

        engine._workflow_engine.register_action("noop_tool", _noop)

        with patch(
            "neurova.shared_core.execution_engine._load_neurflow_workflow",
            return_value=None,
        ):
            result, meta = await engine.execute_workflow("wf_legacy_1", {})
        assert meta["source"] == "legacy"
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_neurflow_missing_workflow_and_no_legacy(self):
        """两边都没有 → 明确报错（不再静默空转）"""
        from neurova.shared_core.execution_engine import ExecutionEngine

        engine = ExecutionEngine()
        with patch(
            "neurova.shared_core.execution_engine._load_neurflow_workflow",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="未注册|not found|不存在"):
                await engine.execute_workflow("ghost_wf", {})


class TestFreezeDeclaration:
    def test_legacy_engine_marked_deprecated(self):
        """旧引擎模块有冻结声明（docstring 指向 neurflow）"""
        import neurova.execution_engine.workflow_engine as legacy_mod

        assert "deprecated" in (legacy_mod.__doc__ or "").lower() or "冻结" in (legacy_mod.__doc__ or "")
        assert "neurflow" in (legacy_mod.__doc__ or "")

    def test_shared_core_docstring_declares_forwarding(self):
        """shared_core 入口 docstring 声明转发语义"""
        import inspect

        from neurova.shared_core.execution_engine import ExecutionEngine

        doc = inspect.getdoc(ExecutionEngine.execute_workflow) or ""
        assert "neurflow" in doc.lower()
