"""§12.13 残余风险：构建批次跨 surface 补偿日志与回滚。"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from neurova.build_mode import build_session as bs
from neurova.build_mode.batch_compensate import compensateBuildBatch
from neurova.build_mode.batch_journal import listCompensations, recordCompensation
from neurova.collaboration.canvas_ops import CanvasOpService
from neurova.collaboration.canvas_store import CanvasStore
from neurova.collaboration.neurflow.custom_nodes import CustomNodeService
from neurova.core.build_context import (
    resetCurrentBuildSessionId,
    setCurrentBuildSessionId,
)
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)
from neurova.collaboration.neurflow.node_registry import (
    get_node_registry,
    reset_node_registry,
)
from neurova.collaboration.neurflow.storage import NeurflowStorage
from neurova.collaboration.neurflow.workflow_definition_editor import (
    updateWorkflowDefinition,
)
from neurova.tool_executor import ToolExecutor


async def _noopBroadcast(*args, **kwargs):
    return None


def _node(node_id: str, node_type: str, label: str = ""):
    return WorkflowNode(
        id=node_id,
        type=node_type,
        position={"x": 0, "y": 0},
        config={},
        label=label or node_id,
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "NEUROVA_BUILD_BATCH_JOURNAL_DIR", str(tmp_path / "batch_journal")
    )
    reset_node_registry()
    storage = NeurflowStorage(db_path=str(tmp_path / "neurflow.db"))
    canvas_store = CanvasStore(base_dir=tmp_path / "collaboration")
    canvas_ops = CanvasOpService(store=canvas_store, broadcaster=_noopBroadcast)
    custom_nodes = CustomNodeService(storage=storage, registry=get_node_registry())
    yield {
        "storage": storage,
        "canvas_store": canvas_store,
        "canvas_ops": canvas_ops,
        "custom_nodes": custom_nodes,
        "tmp": tmp_path,
    }
    storage.close()
    reset_node_registry()


def _compensate(env, batch_id: str):
    return compensateBuildBatch(
        batch_id,
        actorId="u1",
        storage=env["storage"],
        canvasStore=env["canvas_store"],
        canvasOpService=env["canvas_ops"],
        customNodeService=env["custom_nodes"],
    )


class TestBatchCompensation:
    @pytest.mark.asyncio
    async def testCompensatesCanvasNodeAndWorkflowInReverseOrder(self, env):
        batch_id = "batch-comp-1"
        canvas = env["canvas_store"].create(
            {
                "name": "补偿画布",
                "nodes": [
                    {"id": "start", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}},
                    {"id": "end", "type": "builtin:end", "position": {"x": 200, "y": 0}, "config": {}},
                ],
                "edges": [
                    {"id": "e1", "source": {"nodeId": "start"}, "target": {"nodeId": "end"}}
                ],
            },
            user_id="u1",
        )
        original = env["canvas_store"].get(canvas["id"])
        recordCompensation(
            batch_id,
            surface="canvas",
            action="restore_canvas",
            payload={
                "canvas_id": canvas["id"],
                "nodes": original["nodes"],
                "edges": original["edges"],
            },
            actor="u1",
        )
        await env["canvas_ops"].apply_batch(
            canvas["id"],
            [
                {"op": "add_node", "id": "llm", "node_type": "builtin:llm"},
                {"op": "connect", "source_node": "start", "target_node": "llm"},
            ],
            session_id="s1",
        )

        node = env["custom_nodes"].create_node(
            {
                "type": "custom:comp_probe",
                "label": "补偿节点",
                "tier": "declarative",
                "executor_body": {"template": "x"},
            },
            status="draft",
            batch_id=batch_id,
            created_by="u1",
        )
        env["custom_nodes"].activate_node(node.type)
        recordCompensation(
            batch_id,
            surface="node",
            action="deactivate_node",
            payload={"node_type": node.type},
            actor="u1",
        )

        workflow = WorkflowDefinition(
            id="wf_comp",
            name="补偿工作流",
            description="",
            version="1.0.0",
            nodes=[_node("start", "builtin:start"), _node("end", "builtin:end", "原结束")],
            edges=[WorkflowEdge(id="we1", source="start", target="end")],
            variables=[],
            tags=[],
            category="test",
            author="u1",
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.DRAFT,
        )
        env["storage"].save_workflow(workflow, user_id="u1")
        oldVersion = env["storage"].get_workflow_version_number("wf_comp")
        updateWorkflowDefinition(
            "wf_comp",
            nodes=[_node("start", "builtin:start"), _node("end", "builtin:end", "改后结束")],
            edges=[WorkflowEdge(id="we1", source="start", target="end")],
            baseVersion=oldVersion,
            actorId="u1",
            storage=env["storage"],
        )
        recordCompensation(
            batch_id,
            surface="workflow",
            action="rollback_workflow",
            payload={"workflow_id": "wf_comp", "target_version": oldVersion, "batch_id": batch_id},
            actor="u1",
        )

        result = await _compensate(env, batch_id)
        assert result["success"] is True, result
        assert result["compensated"] == 3

        restored = env["canvas_store"].get(canvas["id"])
        assert [node["id"] for node in restored["nodes"]] == ["start", "end"]
        assert restored["version"] == 3

        assert env["custom_nodes"].get_node("custom:comp_probe").status == "draft"
        assert get_node_registry().get("custom:comp_probe") is None

        current = env["storage"].get_workflow("wf_comp")
        assert current.nodes[1].label == "原结束"
        assert env["storage"].get_workflow_version_number("wf_comp") == 3

        again = await _compensate(env, batch_id)
        assert again["success"] is True
        assert again["compensated"] == 0
        assert env["canvas_store"].get(canvas["id"])["version"] == 3

    @pytest.mark.asyncio
    async def testCreatedCanvasIsDeletedOnCompensation(self, env):
        batch_id = "batch-comp-2"
        canvas = env["canvas_store"].create(
            {"name": "待删画布", "nodes": [], "edges": []}, user_id="u1"
        )
        recordCompensation(
            batch_id,
            surface="canvas",
            action="delete_canvas",
            payload={"canvas_id": canvas["id"]},
            actor="u1",
        )
        result = await _compensate(env, batch_id)
        assert result["success"] is True
        assert env["canvas_store"].get(canvas["id"]) is None

    @pytest.mark.asyncio
    async def testUnknownActionStopsAndStaysPending(self, env):
        batch_id = "batch-comp-3"
        recordCompensation(
            batch_id,
            surface="unknown",
            action="not_supported",
            payload={},
            actor="u1",
        )
        result = await _compensate(env, batch_id)
        assert result["success"] is False
        assert "not_supported" in result["error"]
        pending = [entry for entry in listCompensations(batch_id) if not entry.get("compensated_at")]
        assert len(pending) == 1

    def testJournalDedupesPendingEntries(self, env):
        batch_id = "batch-comp-4"
        payload = {"canvas_id": "canvas-1", "nodes": [], "edges": []}
        assert recordCompensation(
            batch_id, surface="canvas", action="restore_canvas", payload=payload
        ) is True
        assert recordCompensation(
            batch_id, surface="canvas", action="restore_canvas", payload=payload
        ) is False
        assert len(listCompensations(batch_id)) == 1

    def testToolRegisteredGatedAndNonReproducible(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, _NON_REPRODUCIBLE_TOOLS

        assert "build_batch_compensate" in _BUILTIN_SCHEMAS
        assert "build_batch_compensate" in ToolExecutor._builtin_dispatch
        assert "build_batch_compensate" in ToolExecutor._BUILD_GATED_TOOLS
        assert "build_batch_compensate" in _NON_REPRODUCIBLE_TOOLS

    @pytest.mark.asyncio
    async def testNodeAndWorkflowToolsWriteCompensationEntries(self, env, monkeypatch):
        manager = bs.BuildSessionManager(
            store_path=str(env["tmp"] / "build2.json"),
            llm_call=lambda prompt: json.dumps(
                {
                    "ready": True,
                    "checklist": {
                        "goal": True,
                        "target": True,
                        "nodes": True,
                        "params": True,
                        "env": True,
                        "permissions": True,
                        "budget": True,
                        "safe_version": True,
                    },
                    "build_plan": {"summary": "节点/定义补偿"},
                    "questions": [],
                },
                ensure_ascii=False,
            ),
        )
        monkeypatch.setattr(
            "neurova.build_mode.get_build_session_manager", lambda: manager
        )
        monkeypatch.setattr(
            "neurova.collaboration.neurflow.custom_nodes.get_custom_node_service",
            lambda: env["custom_nodes"],
        )
        monkeypatch.setattr(
            "neurova.collaboration.neurflow.workflow_definition_editor.getWorkflowDefinitionStorage",
            lambda: env["storage"],
        )
        session = await manager.create("建节点与流程", "agent-x", "u1")
        manager.approve(session.session_id, "u1")
        manager.markBuilding(session.session_id)
        setCurrentBuildSessionId(session.session_id)
        try:
            node = env["custom_nodes"].create_node(
                {
                    "type": "custom:comp_tool",
                    "label": "工具补偿节点",
                    "tier": "declarative",
                    "executor_body": {"template": "x"},
                },
                status="draft",
                batch_id=session.batch_id,
                created_by="u1",
            )
            executor = ToolExecutor(
                SimpleNamespace(
                    _current_user_id="u1",
                    config=SimpleNamespace(agent_id="agent-x", user_id="u1"),
                )
            )
            activated = await executor._execute_builtin_tool(
                "custom_node_activate", {"node_type": node.type}
            )
            assert activated["success"] is True, activated

            workflow = WorkflowDefinition(
                id="wf_comp_tool",
                name="工具补偿流程",
                description="",
                version="1.0.0",
                nodes=[
                    _node("start", "builtin:start"),
                    _node("end", "builtin:end", "原结束"),
                ],
                edges=[WorkflowEdge(id="we1", source="start", target="end")],
                variables=[],
                tags=[],
                category="test",
                author="u1",
                created_at=time.time(),
                updated_at=time.time(),
                status=WorkflowStatus.DRAFT,
            )
            env["storage"].save_workflow(workflow, user_id="u1")
            updated = await executor._execute_builtin_tool(
                "workflow_definition_update",
                {
                    "workflow_id": "wf_comp_tool",
                    "base_version": 1,
                    "nodes": [
                        {"id": "start", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}, "label": "start"},
                        {"id": "end", "type": "builtin:end", "position": {"x": 200, "y": 0}, "config": {}, "label": "改后结束"},
                    ],
                    "edges": [{"id": "we1", "source": "start", "target": "end"}],
                },
            )
            assert updated["success"] is True, updated

            actions = {entry["action"] for entry in listCompensations(session.batch_id)}
            assert "deactivate_node" in actions
            assert "rollback_workflow" in actions

            compensated = await _compensate(env, session.batch_id)
            assert compensated["success"] is True, compensated
            assert env["custom_nodes"].get_node(node.type).status == "draft"
            restored = env["storage"].get_workflow("wf_comp_tool")
            assert restored.nodes[1].label == "原结束"
        finally:
            resetCurrentBuildSessionId()

    @pytest.mark.asyncio
    async def testCanvasToolWritesCompensationEntry(self, env, monkeypatch):
        monkeypatch.setattr(
            "neurova.tool_executor.get_canvas_op_service",
            lambda: env["canvas_ops"],
        )
        monkeypatch.setattr(
            "neurova.collaboration.canvas_store.get_canvas_store",
            lambda: env["canvas_store"],
        )
        manager = bs.BuildSessionManager(
            store_path=str(env["tmp"] / "build.json"),
            llm_call=lambda prompt: json.dumps(
                {
                    "ready": True,
                    "checklist": {
                        "goal": True,
                        "target": True,
                        "nodes": True,
                        "params": True,
                        "env": True,
                        "permissions": True,
                        "budget": True,
                        "safe_version": True,
                    },
                    "build_plan": {"summary": "画布补偿"},
                    "questions": [],
                },
                ensure_ascii=False,
            ),
        )
        monkeypatch.setattr(
            "neurova.build_mode.get_build_session_manager", lambda: manager
        )
        session = await manager.create("建画布", "agent-x", "u1")
        manager.approve(session.session_id, "u1")
        manager.markBuilding(session.session_id)
        setCurrentBuildSessionId(session.session_id)
        try:
            canvas = env["canvas_store"].create(
                {"name": "工具补偿", "nodes": [], "edges": []}, user_id="u1"
            )
            executor = ToolExecutor(
                SimpleNamespace(
                    _current_user_id="u1",
                    config=SimpleNamespace(agent_id="agent-x", user_id="u1"),
                )
            )
            result = await executor._execute_builtin_tool(
                "canvas_apply_batch",
                {
                    "canvas_id": canvas["id"],
                    "operations": [
                        {"op": "add_node", "id": "start", "node_type": "builtin:start"}
                    ],
                    "base_version": 1,
                },
            )
            assert result["success"] is True, result

            entries = listCompensations(session.batch_id)
            assert any(
                entry["surface"] == "canvas"
                and entry["action"] == "restore_canvas"
                and entry["payload"]["canvas_id"] == canvas["id"]
                for entry in entries
            )

            compensated = await _compensate(env, session.batch_id)
            assert compensated["success"] is True, compensated
            restored = env["canvas_store"].get(canvas["id"])
            assert restored["nodes"] == []
        finally:
            resetCurrentBuildSessionId()
