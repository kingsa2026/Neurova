"""N5：节点环境预检 + 工作流修复监督器（草稿副本 / EKB / RSI 骨架 / 5 轮预算）。"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
from types import SimpleNamespace

import pytest

from neurova.collaboration.canvas_ops import CanvasOpService
from neurova.collaboration.canvas_store import CanvasStore
from neurova.collaboration.neurflow.custom_nodes import CustomNodeService
from neurova.collaboration.neurflow.env_preflight import preflightNodeEnv
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
from neurova.collaboration.neurflow.workflow_repair import WorkflowRepairSupervisor
from neurova.collaboration.neurflow.workflow_definition_editor import (
    executeWorkflowDefinition,
)
from neurova.evolution.rsi.rollback_manager import RSIRollbackManager
from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase
from neurova.skills.models import ExperienceRecord
from neurova.tool_executor import ToolExecutor

SKILL_NAME = "workflow_node_repair"


def _probe_spec(env_requirements=None):
    return {
        "type": "custom:repair_probe",
        "label": "修复探针",
        "tier": "declarative",
        "executor_body": {"template": "{{good_key}}"},
        "form_schema": [
            {
                "id": "good_key",
                "type": "text",
                "required": True,
                "default_value": "ok",
            }
        ],
        "env_requirements": list(env_requirements or []),
    }


@pytest.fixture
def storage(tmp_path):
    store = NeurflowStorage(db_path=str(tmp_path / "neurflow.db"))
    yield store
    store.close()


@pytest.fixture
def custom_service(storage, monkeypatch):
    reset_node_registry()
    service = CustomNodeService(storage=storage, registry=get_node_registry())
    monkeypatch.setattr(
        "neurova.collaboration.neurflow.custom_nodes.get_custom_node_service",
        lambda: service,
    )
    yield service
    reset_node_registry()


@pytest.fixture
def ekb(tmp_path):
    instance = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))
    yield instance
    instance.close()


@pytest.fixture
def canvas_store(tmp_path):
    return CanvasStore(base_dir=tmp_path / "collaboration")


async def _noopBroadcast(*args, **kwargs):
    return None


def _create_probe(service, env_requirements=None):
    return service.create_node(
        _probe_spec(env_requirements), status="active", created_by="u1"
    )


def _node(node_id: str, node_type: str, config=None):
    return WorkflowNode(
        id=node_id,
        type=node_type,
        position={"x": 0, "y": 0},
        config=dict(config or {}),
    )


def _published_probe_workflow(storage, workflow_id="wf_repair", config=None):
    workflow = WorkflowDefinition(
        id=workflow_id,
        name="修复判据流程",
        description="",
        version="1.0.0",
        nodes=[
            _node("start", "builtin:start"),
            _node("probe", "custom:repair_probe", config or {"god_key": "v"}),
            _node("end", "builtin:end"),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="probe"),
            WorkflowEdge(id="e2", source="probe", target="end"),
        ],
        variables=[],
        tags=[],
        category="test",
        author="u1",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.PUBLISHED,
    )
    storage.save_workflow(workflow, user_id="u1")
    return workflow


def _failure(error="KeyError: 'good_key'", node_id="probe"):
    return {
        "success": False,
        "status": "failed",
        "execution_id": "exec_fail",
        "error": error,
        "node_results": {
            node_id: {"status": "failed", "error": error, "output": None}
        },
    }


def _success(execution_id="exec_ok"):
    return {
        "success": True,
        "status": "completed",
        "execution_id": execution_id,
        "error": None,
        "outputs": {"probe": "ok"},
        "node_results": {
            "probe": {"status": "success", "error": None, "output": "ok"}
        },
    }


class _ScriptedExecute:
    def __init__(self, results, onCall=None, repeatLast=False):
        self.results = list(results)
        self.calls = []
        self.onCall = onCall
        self.repeatLast = repeatLast

    async def __call__(self, workflowId, inputs):
        self.calls.append(workflowId)
        if self.onCall is not None:
            self.onCall(len(self.calls), workflowId)
        if not self.results:
            return _failure("no scripted result")
        if self.repeatLast and len(self.results) == 1:
            return self.results[0]
        return self.results.pop(0)


def _supervisor(
    storage,
    service,
    ekb,
    execute,
    *,
    candidateGenerator=None,
    armed=True,
    allowCommit=True,
    maxRounds=5,
    canvasStore=None,
    canvasOpService=None,
):
    return WorkflowRepairSupervisor(
        storage=storage,
        customNodeService=service,
        ekb=ekb,
        execute=execute,
        rollbackManager=RSIRollbackManager(),
        candidateGenerator=candidateGenerator,
        armed=armed,
        allowCommit=allowCommit,
        maxRounds=maxRounds,
        timeBudgetSeconds=30,
        canvasStore=canvasStore,
        canvasOpService=canvasOpService,
    )


def _executor():
    return ToolExecutor(
        SimpleNamespace(
            _current_user_id="u1",
            config=SimpleNamespace(agent_id="agent-x", user_id="u1"),
        )
    )


def _ekbRecords(ekb):
    return ekb.get_experience_records(skill_name=SKILL_NAME, limit=50)


class TestNodeEnvPreflight:
    def testMissingAndPresentSources(self, custom_service, monkeypatch):
        _create_probe(custom_service, ["NEUROVA_N5_MISSING_XYZ"])
        monkeypatch.delenv("NEUROVA_N5_MISSING_XYZ", raising=False)

        result = preflightNodeEnv(
            ["custom:repair_probe"],
            customNodeService=custom_service,
            secretStore=SimpleNamespace(list_keys=lambda: []),
        )
        assert result["success"] is True
        assert result["ready"] is False
        assert "NEUROVA_N5_MISSING_XYZ" in result["missing"]
        assert result["declared"]["custom:repair_probe"] == ["NEUROVA_N5_MISSING_XYZ"]
        assert "NEUROVA_N5_MISSING_XYZ" in result["providers"]

        monkeypatch.setenv("NEUROVA_N5_MISSING_XYZ", "present")
        ready = preflightNodeEnv(
            ["custom:repair_probe"],
            customNodeService=custom_service,
            secretStore=SimpleNamespace(list_keys=lambda: []),
        )
        assert ready["ready"] is True
        assert ready["missing"] == []
        assert "present" not in json.dumps(ready, ensure_ascii=False)

    def testSecretStoreKeyCountsAsAvailableWithoutReadingValue(
        self, custom_service, monkeypatch
    ):
        _create_probe(custom_service, ["NEUROVA_N5_STORE_ONLY"])
        monkeypatch.delenv("NEUROVA_N5_STORE_ONLY", raising=False)
        result = preflightNodeEnv(
            "custom:repair_probe",
            customNodeService=custom_service,
            secretStore=SimpleNamespace(list_keys=lambda: ["NEUROVA_N5_STORE_ONLY"]),
        )
        assert result["ready"] is True
        assert result["sources"]["NEUROVA_N5_STORE_ONLY"] == ["secret_store"]
        assert "super-secret-value" not in json.dumps(result, ensure_ascii=False)

    def testUnknownTypeReportsCode(self, custom_service):
        result = preflightNodeEnv(
            ["custom:no_such_node"],
            customNodeService=custom_service,
            secretStore=SimpleNamespace(list_keys=lambda: []),
        )
        assert result["success"] is False
        assert result["code"] == "unknown_node_type"
        assert "custom:no_such_node" in result["unknown_types"]

    def testToolRegisteredAndDispatched(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "node_env_preflight" in _BUILTIN_SCHEMAS
        assert "node_env_preflight" in ToolExecutor._builtin_dispatch

    def testToolDispatchReturnsMissingNames(self, custom_service, monkeypatch):
        _create_probe(custom_service, ["NEUROVA_N5_TOOL_MISSING"])
        monkeypatch.delenv("NEUROVA_N5_TOOL_MISSING", raising=False)
        result = asyncio.run(
            _executor()._execute_builtin_tool(
                "node_env_preflight", {"types": ["custom:repair_probe"]}
            )
        )
        assert result["success"] is True
        assert result["ready"] is False
        assert "NEUROVA_N5_TOOL_MISSING" in result["missing"]


class TestWorkflowRepairSupervisor:
    @pytest.mark.asyncio
    async def testRealEngineSurfacesInnerFailedStatus(self, storage, custom_service):
        """组合节点内层返回 status=failed 时，引擎必须让工作流失败而不是记 success。"""
        custom_service.create_node(
            {
                "type": "custom:engine_failure_probe",
                "label": "引擎失败探针",
                "tier": "composite",
                "executor_body": {
                    "steps": [
                        {
                            "node_type": "builtin:variable",
                            "config": {
                                "name": "{{config.good_key}}",
                                "value": "ok",
                            },
                        }
                    ]
                },
                "form_schema": [{"id": "good_key", "type": "text", "required": True}],
            },
            status="active",
            created_by="u1",
        )
        workflow = WorkflowDefinition(
            id="wf_inner_failed",
            name="内层失败判据",
            description="",
            version="1.0.0",
            nodes=[
                _node("start", "builtin:start"),
                _node("middle", "custom:engine_failure_probe", {"god_key": "x"}),
                _node("end", "builtin:end"),
            ],
            edges=[
                WorkflowEdge(id="e1", source="start", target="middle"),
                WorkflowEdge(id="e2", source="middle", target="end"),
            ],
            variables=[],
            tags=[],
            category="test",
            author="u1",
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.DRAFT,
        )
        storage.save_workflow(workflow, user_id="u1")

        result = await executeWorkflowDefinition(
            "wf_inner_failed",
            inputs={},
            allowDraft=True,
            actorId="u1",
            storage=storage,
        )
        assert result["success"] is False, result
        assert result["status"] == "failed", result
        assert result["node_results"]["middle"]["status"] == "failed", result
        assert "缺少变量名" in (result["node_results"]["middle"]["error"] or ""), result

    @pytest.mark.asyncio
    async def testConfigTypoRepairedOnDraftThenCommitted(
        self, storage, custom_service, ekb, monkeypatch
    ):
        _create_probe(custom_service)
        _published_probe_workflow(storage)

        def onCall(index, workflowId):
            if index == 1:
                target = storage.get_workflow("wf_repair")
                assert target.nodes[1].config.get("god_key") == "v"
                assert storage.get_workflow_version_number("wf_repair") == 1

        execute = _ScriptedExecute([_failure(), _success()], onCall=onCall)
        supervisor = _supervisor(storage, custom_service, ekb, execute)
        result = await supervisor.repair(
            workflowId="wf_repair",
            inputs={},
            commit=True,
            actorId="u1",
            batchId="batch-repair",
        )

        assert result["success"] is True
        assert result["status"] == "completed"
        assert result["rounds"] == 2
        assert result["committed"] is True
        assert result["draft_workflow_id"] != "wf_repair"

        target = storage.get_workflow("wf_repair")
        assert target.nodes[1].config["good_key"] == "v"
        assert "god_key" not in target.nodes[1].config
        assert storage.get_workflow_version_number("wf_repair") == 2
        assert result["proposals"][0]["status"] == "applied"

        records = _ekbRecords(ekb)
        assert any(record["success"] == 1 for record in records)
        assert any(
            "node:custom:repair_probe" in (record.get("tags") or [])
            for record in records
        )

    @pytest.mark.asyncio
    async def testMissingEnvBlocksBeforeAnyRun(
        self, storage, custom_service, ekb, monkeypatch
    ):
        _create_probe(custom_service, ["NEUROVA_N5_BLOCKED_XYZ"])
        monkeypatch.delenv("NEUROVA_N5_BLOCKED_XYZ", raising=False)
        _published_probe_workflow(storage)
        execute = _ScriptedExecute([_failure(), _success()])
        supervisor = _supervisor(storage, custom_service, ekb, execute)

        result = await supervisor.repair(
            workflowId="wf_repair", commit=True, actorId="u1"
        )
        assert result["success"] is False
        assert result["status"] == "blocked"
        assert result["rounds"] == 0
        assert execute.calls == []
        assert "NEUROVA_N5_BLOCKED_XYZ" in result["missing_env"]

        records = _ekbRecords(ekb)
        assert any(record["success"] == 0 for record in records)

    @pytest.mark.asyncio
    async def testNoCandidatesStopsWithoutBurningFiveRounds(
        self, storage, custom_service, ekb
    ):
        custom_service.create_node(
            {
                "type": "custom:repair_opaque",
                "label": "无契约节点",
                "tier": "declarative",
                "executor_body": {"template": "x"},
                "form_schema": [],
            },
            status="active",
            created_by="u1",
        )
        workflow = _published_probe_workflow(storage, workflow_id="wf_opaque")
        workflow.nodes[1] = _node("probe", "custom:repair_opaque")
        storage.save_workflow(workflow, user_id="u1")

        execute = _ScriptedExecute([_failure("opaque boom")], repeatLast=True)
        supervisor = _supervisor(storage, custom_service, ekb, execute)
        result = await supervisor.repair(workflowId="wf_opaque", actorId="u1")

        assert result["success"] is False
        assert result["status"] == "needs_agent"
        assert result["rounds"] == 1
        assert len(execute.calls) == 1

    @pytest.mark.asyncio
    async def testMaxFiveRoundsAndRollback(
        self, storage, custom_service, ekb
    ):
        _create_probe(custom_service)
        _published_probe_workflow(storage)

        counter = {"n": 0}

        def generator(diagnosis):
            counter["n"] += 1
            return [
                {
                    "action": "set_config",
                    "node_id": "probe",
                    "set": {"attempt": counter["n"]},
                    "remove": [],
                    "reason": "测试用候选",
                    "source": "test",
                }
            ]

        execute = _ScriptedExecute([_failure()], repeatLast=True)
        supervisor = _supervisor(
            storage,
            custom_service,
            ekb,
            execute,
            candidateGenerator=generator,
            maxRounds=9,
        )
        result = await supervisor.repair(workflowId="wf_repair", actorId="u1")

        assert result["success"] is False
        assert result["status"] == "failed"
        assert result["rounds"] == 5
        assert len(execute.calls) == 5
        assert all(p["status"] == "rolled_back" for p in result["proposals"])
        assert len(result["rollbacks"]) >= 1

    @pytest.mark.asyncio
    async def testNotArmedReturnsNeedsApprovalWithoutRunning(
        self, storage, custom_service, ekb
    ):
        _create_probe(custom_service)
        _published_probe_workflow(storage)
        execute = _ScriptedExecute([_failure(), _success()])
        supervisor = _supervisor(
            storage, custom_service, ekb, execute, armed=False
        )
        result = await supervisor.repair(workflowId="wf_repair", actorId="u1")

        assert result["success"] is False
        assert result["status"] == "needs_approval"
        assert result["reason"] == "repair_not_armed"
        assert execute.calls == []

    @pytest.mark.asyncio
    async def testCommitFalseLeavesTargetUntouched(
        self, storage, custom_service, ekb
    ):
        _create_probe(custom_service)
        _published_probe_workflow(storage)
        execute = _ScriptedExecute([_failure(), _success()])
        supervisor = _supervisor(storage, custom_service, ekb, execute)

        result = await supervisor.repair(
            workflowId="wf_repair", commit=False, actorId="u1"
        )
        assert result["success"] is True
        assert result["committed"] is False
        target = storage.get_workflow("wf_repair")
        assert target.nodes[1].config.get("god_key") == "v"
        assert "good_key" not in target.nodes[1].config
        draft = storage.get_workflow(result["draft_workflow_id"])
        assert draft.nodes[1].config["good_key"] == "v"

    @pytest.mark.asyncio
    async def testCanvasRepairCommitsConfigOnly(
        self, storage, custom_service, ekb, canvas_store
    ):
        _create_probe(custom_service)
        record = canvas_store.create(
            {
                "name": "画布修复判据",
                "nodes": [
                    {"id": "start", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}},
                    {
                        "id": "probe",
                        "type": "custom:repair_probe",
                        "position": {"x": 200, "y": 0},
                        "config": {"god_key": "v"},
                    },
                    {"id": "end", "type": "builtin:end", "position": {"x": 400, "y": 0}, "config": {}},
                ],
                "edges": [
                    {"id": "e1", "source": {"nodeId": "start"}, "target": {"nodeId": "probe"}},
                    {"id": "e2", "source": {"nodeId": "probe"}, "target": {"nodeId": "end"}},
                ],
            },
            user_id="u1",
        )
        canvasId = record["id"]

        def onCall(index, workflowId):
            if index == 1:
                assert canvas_store.get(canvasId)["version"] == 1
                probe = next(
                    n
                    for n in canvas_store.get(canvasId)["nodes"]
                    if n["id"] == "probe"
                )
                assert probe["config"].get("god_key") == "v"

        execute = _ScriptedExecute([_failure(), _success()], onCall=onCall)
        service = CanvasOpService(store=canvas_store, broadcaster=_noopBroadcast)
        supervisor = _supervisor(
            storage,
            custom_service,
            ekb,
            execute,
            canvasStore=canvas_store,
            canvasOpService=service,
        )
        result = await supervisor.repair(canvasId=canvasId, actorId="u1")

        assert result["success"] is True
        assert result["committed"] is True
        updated = canvas_store.get(canvasId)
        probe = next(n for n in updated["nodes"] if n["id"] == "probe")
        assert probe["config"]["good_key"] == "v"
        assert "god_key" not in probe["config"]
        assert updated["version"] == 2
        draft = storage.get_workflow(result["draft_workflow_id"])
        assert draft.metadata["source_canvas_id"] == canvasId

    @pytest.mark.asyncio
    async def testReplacementCandidateEvaluatedBeforeCommit(
        self, storage, custom_service, ekb
    ):
        for nodeType, label in (
            ("custom:swap_old", "交换节点A"),
            ("custom:swap_new", "交换节点B"),
        ):
            custom_service.create_node(
                {
                    "type": nodeType,
                    "label": label,
                    "category": "flow",
                    "tier": "declarative",
                    "executor_body": {"template": "x"},
                    "form_schema": [],
                },
                status="active",
                created_by="u1",
            )
        workflow = _published_probe_workflow(storage, workflow_id="wf_swap")
        workflow.nodes[1] = _node("probe", "custom:swap_old")
        storage.save_workflow(workflow, user_id="u1")

        def onCall(index, workflowId):
            if index == 2:
                draft = storage.get_workflow(workflowId)
                assert draft.nodes[1].type == "custom:swap_new"

        execute = _ScriptedExecute([_failure("swap required"), _success()], onCall=onCall)
        supervisor = _supervisor(storage, custom_service, ekb, execute)
        result = await supervisor.repair(workflowId="wf_swap", actorId="u1")

        assert result["success"] is True, result
        assert result["rounds"] == 2
        assert result["committed"] is True
        target = storage.get_workflow("wf_swap")
        assert target.nodes[1].type == "custom:swap_new"
        assert any(
            candidate.get("action") == "replace_node"
            for candidate in result["candidates_considered"]
        )

    @pytest.mark.asyncio
    async def testEkbHitIsSurfacedButStillEvaluated(
        self, storage, custom_service, ekb
    ):
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        ekb.add_experience_record(
            SKILL_NAME,
            ExperienceRecord(
                skill_name=SKILL_NAME,
                context={
                    "user_input": "KeyError: 'good_key'",
                    "topic": "custom:repair_probe",
                },
                result={
                    "patch": {
                        "action": "set_config",
                        "node_id": "probe",
                        "set": {"good_key": "from-ekb"},
                        "remove": ["god_key"],
                    },
                    "attempt": 1,
                    "outcome": "success",
                },
                success=True,
                timestamp=timestamp,
            ),
            agent_id="agent-x",
            tags=[SKILL_NAME, "node:custom:repair_probe"],
            evidence=True,
        )
        _create_probe(custom_service)
        _published_probe_workflow(storage)
        execute = _ScriptedExecute([_failure(), _success()])
        supervisor = _supervisor(storage, custom_service, ekb, execute)

        result = await supervisor.repair(workflowId="wf_repair", actorId="u1")
        assert result["success"] is True
        assert result["rounds"] == 2
        assert result["diagnosis"]["ekb_matches"]
        assert any(
            candidate.get("source") == "ekb"
            for candidate in result["candidates_considered"]
        )

    @pytest.mark.asyncio
    async def testCommitNotAllowedReturnsDraftForApproval(
        self, storage, custom_service, ekb
    ):
        _create_probe(custom_service)
        _published_probe_workflow(storage)
        execute = _ScriptedExecute([_failure(), _success()])
        supervisor = _supervisor(
            storage, custom_service, ekb, execute, allowCommit=False
        )
        result = await supervisor.repair(
            workflowId="wf_repair", commit=True, actorId="u1"
        )
        assert result["success"] is False
        assert result["status"] == "needs_approval"
        assert result["reason"] == "commit_not_allowed"
        assert result["draft_workflow_id"]
        assert storage.get_workflow_version_number("wf_repair") == 1

    def testToolsRegisteredGatedAndNonReproducible(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, _NON_REPRODUCIBLE_TOOLS

        assert "workflow_repair" in _BUILTIN_SCHEMAS
        assert "workflow_repair" in ToolExecutor._builtin_dispatch
        assert "workflow_repair" in ToolExecutor._BUILD_GATED_TOOLS
        assert "workflow_repair" in _NON_REPRODUCIBLE_TOOLS
        assert "node_env_preflight" not in ToolExecutor._BUILD_GATED_TOOLS
