"""N4：工作流定义读取/修改/回滚/发布 + safe_version + DRAFT 暂存与草稿执行。"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from neurova.build_mode import build_session as bs
from neurova.collaboration.neurflow.custom_nodes import CustomNodeService
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
    duplicateWorkflowDefinition,
    executeWorkflowDefinition,
    getWorkflowDefinition,
    publishWorkflowDefinition,
    rollbackWorkflowDefinition,
    updateWorkflowDefinition,
    validateWorkflowDefinition,
)
from neurova.core.build_context import (
    resetCurrentBuildSessionId,
    setCurrentBuildSessionId,
)
from neurova.tool_executor import ToolExecutor


def _node(node_id: str, node_type: str, label: str = "", config=None):
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0, "y": 0},
        "config": dict(config or {}),
        "label": label or node_id,
    }


def _edge(edge_id: str, source: str, target: str, source_handle=None):
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "source_handle": source_handle,
        "target_handle": None,
        "label": None,
        "condition": None,
    }


def _start_end_nodes():
    return [_node("start", "builtin:start"), _node("end", "builtin:end")]


def _start_end_edges():
    return [_edge("e1", "start", "end")]


def _workflow(
    workflow_id: str = "wf_n4",
    status: WorkflowStatus = WorkflowStatus.PUBLISHED,
    nodes=None,
    edges=None,
):
    return WorkflowDefinition(
        id=workflow_id,
        name="N4 流程",
        description="判据用流程",
        version="1.0.0",
        nodes=[WorkflowNode(**n) for n in (nodes or _start_end_nodes())],
        edges=[WorkflowEdge(**e) for e in (edges or _start_end_edges())],
        variables=[],
        tags=[],
        category="test",
        author="u1",
        created_at=time.time(),
        updated_at=time.time(),
        status=status,
    )


def _save(storage, workflow_id="wf_n4", **kwargs):
    wf = _workflow(workflow_id, **kwargs)
    storage.save_workflow(wf, user_id="u1")
    return wf


@pytest.fixture
def storage(tmp_path):
    store = NeurflowStorage(db_path=str(tmp_path / "neurflow.db"))
    yield store
    store.close()


@pytest.fixture
def definition_env(tmp_path, monkeypatch, storage):
    monkeypatch.setenv(
        "NEUROVA_WORKFLOW_DEFINITION_AUDIT", str(tmp_path / "wf_audit.jsonl")
    )
    monkeypatch.setattr(
        "neurova.collaboration.neurflow.workflow_definition_editor.getWorkflowDefinitionStorage",
        lambda: storage,
    )
    reset_node_registry()
    yield storage
    reset_node_registry()


def _audit_entries(tmp_path):
    path = tmp_path / "wf_audit.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _assessment(ready: bool):
    return json.dumps(
        {
            "ready": ready,
            "checklist": {
                "goal": ready,
                "target": ready,
                "nodes": ready,
                "params": ready,
                "env": ready,
                "permissions": ready,
                "budget": ready,
                "safe_version": True,
            },
            "build_plan": {"summary": "修改已发布工作流"},
            "questions": [] if ready else [
                {"id": "q1", "question": "改哪条？", "kind": "text", "why": "目标不明", "impact": "决定定义"}
            ],
        },
        ensure_ascii=False,
    )


@pytest.fixture
def approved_session(tmp_path, monkeypatch, definition_env):
    manager = bs.BuildSessionManager(
        store_path=str(tmp_path / "build.json"),
        llm_call=lambda prompt: _assessment(True),
    )
    monkeypatch.setattr("neurova.build_mode.get_build_session_manager", lambda: manager)
    yield manager
    resetCurrentBuildSessionId()


async def _approved(manager):
    session = await manager.create("改一条已发布工作流", "agent-x", "u1")
    manager.approve(session.session_id, "u1")
    manager.markBuilding(session.session_id)
    setCurrentBuildSessionId(session.session_id)
    return session


def _executor():
    return ToolExecutor(
        SimpleNamespace(
            _current_user_id="u1",
            config=SimpleNamespace(agent_id="agent-x", user_id="u1"),
        )
    )


class TestSafeVersionStorage:
    def testEnsureBaselineCreatesAndIsIdempotent(self, storage):
        _save(storage)
        assert storage.getSafeVersion("wf_n4") is None

        first = storage.ensureSafeVersion("wf_n4", reason="baseline")
        assert first["created"] is True
        assert first["version"] == 1
        assert first["valid"] is True

        second = storage.ensureSafeVersion("wf_n4", reason="again")
        assert second["created"] is False
        assert second["version"] == 1

    def testSaveWorkflowPreservesSafeVersion(self, storage):
        _save(storage)
        storage.ensureSafeVersion("wf_n4", reason="baseline")

        changed_nodes = _start_end_nodes()
        changed_nodes[1]["label"] = "改后的结束"
        wf = storage.get_workflow("wf_n4")
        wf.nodes = [WorkflowNode(**n) for n in changed_nodes]
        wf.updated_at = time.time()
        storage.save_workflow(wf)

        safe = storage.getSafeVersion("wf_n4")
        assert safe is not None
        assert safe["version"] == 1
        assert safe["valid"] is True
        assert storage.get_workflow_version_number("wf_n4") == 2

    def testBackfillPublishedWorkflowOnReopen(self, tmp_path):
        db_path = str(tmp_path / "neurflow.db")
        first = NeurflowStorage(db_path=db_path)
        _save(first)
        assert first.getSafeVersion("wf_n4") is None
        first.close()

        second = NeurflowStorage(db_path=db_path)
        try:
            safe = second.getSafeVersion("wf_n4")
            assert safe is not None
            assert safe["reason"] == "migration_baseline"
            assert safe["version"] == 1
        finally:
            second.close()

    def testSafeVersionSnapshotOutlivesCapacityPruning(self, storage):
        _save(storage)
        safe = storage.ensureSafeVersion("wf_n4", reason="baseline")
        assert safe["version"] == 1

        for index in range(25):
            wf = storage.get_workflow("wf_n4")
            wf.nodes[1].label = f"第 {index} 版"
            wf.updated_at = time.time()
            storage.save_workflow(wf)

        versions = [item["version"] for item in storage.list_workflow_versions("wf_n4")]
        assert 1 in versions
        assert storage.getSafeVersion("wf_n4")["valid"] is True

    def testSetSafeVersionRejectsMissingSnapshot(self, storage):
        _save(storage)
        with pytest.raises(ValueError):
            storage.setSafeVersion("wf_n4", 99, reason="bad")


class TestDefinitionValidation:
    def testValidDefinition(self):
        result = validateWorkflowDefinition(_start_end_nodes(), _start_end_edges())
        assert result["is_valid"] is True
        assert result["errors"] == []

    def testUnknownNodeType(self):
        nodes = [_node("start", "builtin:start"), _node("x", "custom:nope"), _node("end", "builtin:end")]
        edges = [_edge("e1", "start", "x"), _edge("e2", "x", "end")]
        result = validateWorkflowDefinition(nodes, edges)
        assert result["is_valid"] is False
        assert any("custom:nope" in err for err in result["errors"])

    def testCycleRejected(self):
        nodes = [
            _node("start", "builtin:start"),
            _node("a", "builtin:delay", config={"seconds": 0}),
            _node("end", "builtin:end"),
        ]
        edges = [
            _edge("e1", "start", "a"),
            _edge("e2", "a", "end"),
            _edge("e3", "end", "a"),
        ]
        result = validateWorkflowDefinition(nodes, edges)
        assert result["is_valid"] is False
        assert any("环" in err for err in result["errors"])

    def testMissingEndRejected(self):
        nodes = [_node("start", "builtin:start")]
        result = validateWorkflowDefinition(nodes, [])
        assert result["is_valid"] is False
        assert any("结束" in err for err in result["errors"])


class TestDefinitionTools:
    def testToolsRegisteredGatedAndNonReproducible(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, _NON_REPRODUCIBLE_TOOLS

        names = (
            "workflow_definition_get",
            "workflow_definition_update",
            "workflow_definition_duplicate",
            "workflow_rollback",
            "workflow_publish",
            "workflow_execute",
        )
        for name in names:
            assert name in _BUILTIN_SCHEMAS
            assert name in ToolExecutor._builtin_dispatch
        for name in names[1:]:
            assert name in ToolExecutor._BUILD_GATED_TOOLS
            assert name in _NON_REPRODUCIBLE_TOOLS

    @pytest.mark.asyncio
    async def testGateBlocksBeforeApproval(self, tmp_path, monkeypatch, definition_env):
        _save(definition_env)
        manager = bs.BuildSessionManager(
            store_path=str(tmp_path / "build.json"),
            llm_call=lambda prompt: _assessment(False),
        )
        monkeypatch.setattr("neurova.build_mode.get_build_session_manager", lambda: manager)
        session = await manager.create("改一条已发布工作流", "agent-x", "u1")
        setCurrentBuildSessionId(session.session_id)

        result = await _executor()._execute_builtin_tool(
            "workflow_definition_update",
            {
                "workflow_id": "wf_n4",
                "base_version": 1,
                "nodes": _start_end_nodes(),
                "edges": _start_end_edges(),
            },
        )
        assert result["success"] is False
        assert result["status"] == "clarification_required"
        assert definition_env.get_workflow_version_number("wf_n4") == 1

    def testGetCreatesBaselineForPublished(self, definition_env):
        _save(definition_env)
        result = getWorkflowDefinition("wf_n4", actorId="u1")
        assert result["success"] is True
        assert result["status"] == "published"
        assert result["safe_version"] == 1
        assert result["safe_created"] is True
        assert result["definition"]["id"] == "wf_n4"

    def testUpdateRequiresBaseVersion(self, definition_env):
        _save(definition_env)
        result = updateWorkflowDefinition(
            "wf_n4",
            nodes=_start_end_nodes(),
            edges=_start_end_edges(),
            baseVersion=None,
            actorId="u1",
        )
        assert result["success"] is False
        assert result["code"] == "base_version_required"

    def testUpdateConflictLeavesContentUntouched(self, definition_env):
        _save(definition_env)
        result = updateWorkflowDefinition(
            "wf_n4",
            nodes=_start_end_nodes(),
            edges=_start_end_edges(),
            baseVersion=99,
            actorId="u1",
        )
        assert result["success"] is False
        assert result["code"] == "version_conflict"
        assert result["current_version"] == 1
        assert definition_env.get_workflow_version_number("wf_n4") == 1

    def testUpdateRejectsDraftCustomNode(self, definition_env, tmp_path, monkeypatch):
        _save(definition_env)
        service = CustomNodeService(
            storage=definition_env, registry=get_node_registry()
        )
        monkeypatch.setattr(
            "neurova.collaboration.neurflow.custom_nodes.get_custom_node_service",
            lambda: service,
        )
        service.create_node(
            {
                "type": "custom:n4_draft",
                "label": "草稿节点",
                "tier": "declarative",
                "executor_body": {"template": "草稿"},
                "form_schema": [{"id": "input", "type": "text"}],
            },
            status="draft",
            batch_id="batch-n4",
        )
        nodes = [
            _node("start", "builtin:start"),
            _node("d", "custom:n4_draft"),
            _node("end", "builtin:end"),
        ]
        edges = [_edge("e1", "start", "d"), _edge("e2", "d", "end")]
        result = updateWorkflowDefinition(
            "wf_n4", nodes=nodes, edges=edges, baseVersion=1, actorId="u1"
        )
        assert result["success"] is False
        assert result["code"] == "validation_failed"
        assert any("draft" in err or "草稿" in err for err in result["errors"])
        assert definition_env.get_workflow_version_number("wf_n4") == 1

    def testDraftCustomNodeNotInRegistryUntilActivated(self, definition_env, monkeypatch):
        service = CustomNodeService(
            storage=definition_env, registry=get_node_registry()
        )
        monkeypatch.setattr(
            "neurova.collaboration.neurflow.custom_nodes.get_custom_node_service",
            lambda: service,
        )
        service.create_node(
            {
                "type": "custom:n4_hidden",
                "label": "不可见草稿",
                "tier": "declarative",
                "executor_body": {"template": "草稿"},
            },
            status="draft",
            batch_id="batch-n4",
        )
        assert get_node_registry().get("custom:n4_hidden") is None

        service.activate_node("custom:n4_hidden")
        assert get_node_registry().get("custom:n4_hidden") is not None

    def testUpdateValidationFailureLeavesVersionAndAudits(
        self, definition_env, tmp_path
    ):
        _save(definition_env)
        getWorkflowDefinition("wf_n4", actorId="u1")

        result = updateWorkflowDefinition(
            "wf_n4",
            nodes=[_node("start", "builtin:start")],
            edges=[],
            baseVersion=1,
            actorId="u1",
            batchId="batch-1",
        )
        assert result["success"] is False
        assert result["code"] == "validation_failed"
        assert definition_env.get_workflow_version_number("wf_n4") == 1

        entries = _audit_entries(tmp_path)
        assert any(
            item.get("action") == "update_refused"
            and item.get("workflow_id") == "wf_n4"
            and item.get("batch_id") == "batch-1"
            for item in entries
        )

    def testUpdateSuccessIncrementsAndAudits(self, definition_env, tmp_path):
        _save(definition_env)
        getWorkflowDefinition("wf_n4", actorId="u1")

        nodes = _start_end_nodes()
        nodes[1]["label"] = "更新后的结束"
        result = updateWorkflowDefinition(
            "wf_n4",
            nodes=nodes,
            edges=_start_end_edges(),
            baseVersion=1,
            actorId="u1",
            batchId="batch-2",
            note="改标签",
        )
        assert result["success"] is True
        assert result["version"] == 2
        assert result["safe_version"] == 1

        entries = _audit_entries(tmp_path)
        assert any(
            item.get("action") == "update"
            and item.get("old_version") == 1
            and item.get("new_version") == 2
            and item.get("batch_id") == "batch-2"
            for item in entries
        )

    def testRollbackDefaultsToSafeVersion(self, definition_env):
        _save(definition_env)
        getWorkflowDefinition("wf_n4", actorId="u1")

        nodes = _start_end_nodes()
        nodes[1]["label"] = "待回滚结束"
        updateWorkflowDefinition(
            "wf_n4", nodes=nodes, edges=_start_end_edges(), baseVersion=1, actorId="u1"
        )

        result = rollbackWorkflowDefinition("wf_n4", actorId="u1", batchId="batch-3")
        assert result["success"] is True
        assert result["restored_from"] == 1
        assert result["version"] == 3

        current = definition_env.get_workflow("wf_n4")
        assert current.nodes[1].label == "end"
        assert definition_env.getSafeVersion("wf_n4")["version"] == 1

    def testRollbackWithoutSafeVersionRefused(self, definition_env):
        _save(definition_env, status=WorkflowStatus.DRAFT)
        result = rollbackWorkflowDefinition("wf_n4", actorId="u1")
        assert result["success"] is False
        assert result["code"] == "no_safe_version"

    def testPublishDraftPromotesSafeVersion(self, definition_env, monkeypatch):
        _save(definition_env, status=WorkflowStatus.DRAFT, workflow_id="wf_pub")
        result = publishWorkflowDefinition(
            "wf_pub", actorId="u1", batchId="batch-4", note="首发"
        )
        assert result["success"] is True
        assert result["status"] == "published"
        assert result["safe_version"] == 1

    def testPublishRejectsInvalidDefinition(self, definition_env):
        _save(
            definition_env,
            status=WorkflowStatus.DRAFT,
            workflow_id="wf_bad",
            nodes=[_node("start", "builtin:start")],
            edges=[],
        )
        result = publishWorkflowDefinition("wf_bad", actorId="u1")
        assert result["success"] is False
        assert result["code"] == "validation_failed"
        assert definition_env.get_workflow("wf_bad").status == WorkflowStatus.DRAFT

    @pytest.mark.asyncio
    async def testDuplicateCreatesDraftCopy(self, definition_env):
        _save(definition_env)
        getWorkflowDefinition("wf_n4", actorId="u1")

        result = duplicateWorkflowDefinition(
            "wf_n4", name="修复草稿", actorId="u1", batchId="batch-5"
        )
        assert result["success"] is True
        assert result["status"] == "draft"
        copy = definition_env.get_workflow(result["workflow_id"])
        assert copy is not None
        assert copy.status == WorkflowStatus.DRAFT
        assert [n.id for n in copy.nodes] == ["start", "end"]
        assert copy.metadata["source_workflow_id"] == "wf_n4"
        assert copy.metadata["batch_id"] == "batch-5"

    @pytest.mark.asyncio
    async def testExecuteDraftRequiresFlagAndDoesNotPromoteSafe(
        self, definition_env
    ):
        _save(definition_env, status=WorkflowStatus.DRAFT, workflow_id="wf_draft")

        refused = await executeWorkflowDefinition(
            "wf_draft", inputs={}, allowDraft=False, actorId="u1"
        )
        assert refused["success"] is False
        assert refused["code"] == "draft_execution_forbidden"

        ran = await executeWorkflowDefinition(
            "wf_draft", inputs={"x": 1}, allowDraft=True, actorId="u1"
        )
        assert ran["success"] is True
        assert ran["status"] == "completed"
        assert definition_env.getSafeVersion("wf_draft") is None

    @pytest.mark.asyncio
    async def testExecutePublishedPromotesSafeVersion(self, definition_env):
        _save(definition_env)
        getWorkflowDefinition("wf_n4", actorId="u1")

        nodes = _start_end_nodes()
        nodes[1]["label"] = "执行验证版本"
        updateWorkflowDefinition(
            "wf_n4", nodes=nodes, edges=_start_end_edges(), baseVersion=1, actorId="u1"
        )
        assert definition_env.getSafeVersion("wf_n4")["version"] == 1

        result = await executeWorkflowDefinition(
            "wf_n4", inputs={}, allowDraft=False, actorId="u1", actorAgentId="agent-x"
        )
        assert result["success"] is True
        safe = definition_env.getSafeVersion("wf_n4")
        assert safe["version"] == 2
        assert safe["reason"] == "execution_verified"

    @pytest.mark.asyncio
    async def testRolledBackContentIsWhatExecutionConsumes(
        self, definition_env, monkeypatch
    ):
        _save(definition_env)
        getWorkflowDefinition("wf_n4", actorId="u1")
        nodes = _start_end_nodes()
        nodes[1]["label"] = "坏版本"
        updateWorkflowDefinition(
            "wf_n4", nodes=nodes, edges=_start_end_edges(), baseVersion=1, actorId="u1"
        )
        rollbackWorkflowDefinition("wf_n4", actorId="u1")

        captured = {}

        class _Executor:
            async def execute(self, workflow, inputs, **kwargs):
                captured["labels"] = [n.label for n in workflow.nodes]
                return SimpleNamespace(
                    status=WorkflowStatus.COMPLETED,
                    outputs={},
                    error=None,
                    node_results={},
                    duration=0.0,
                    id="exec_probe",
                )

        monkeypatch.setattr(
            "neurova.collaboration.neurflow.execution_engine.get_workflow_executor",
            lambda: _Executor(),
        )
        result = await executeWorkflowDefinition(
            "wf_n4", inputs={}, allowDraft=False, actorId="u1"
        )
        assert result["success"] is True
        assert captured["labels"] == ["start", "end"]
