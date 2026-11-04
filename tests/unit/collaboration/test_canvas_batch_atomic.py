"""B5：画布批量操作一个事务提交，失败整批不落盘。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from neurova.build_mode import build_session as bs
from neurova.collaboration.canvas_ops import CanvasOpError, CanvasOpService
from neurova.collaboration.canvas_store import CanvasStore, CanvasVersionConflict
from neurova.core.build_context import (
    resetCurrentBuildSessionId,
    setCurrentBuildSessionId,
)
from neurova.tool_executor import ToolExecutor


@pytest.fixture
def canvas_env(tmp_path):
    events = []

    async def _broadcast(session_id, payload):
        events.append(payload)

    store = CanvasStore(base_dir=tmp_path / "collaboration")
    record = store.create(
        {"name": "批量画布", "nodes": [], "edges": []}, user_id="u1"
    )
    service = CanvasOpService(store=store, broadcaster=_broadcast)
    return SimpleNamespace(
        store=store,
        service=service,
        canvas_id=record["id"],
        events=events,
    )


def _executor():
    return ToolExecutor(
        SimpleNamespace(
            _current_user_id="u1",
            config=SimpleNamespace(agent_id="agent-x", user_id="u1"),
        )
    )


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
            "build_plan": {"summary": "建画布"},
            "questions": [] if ready else [
                {"id": "q1", "question": "目标？", "kind": "text", "why": "不明", "impact": "决定节点"}
            ],
        },
        ensure_ascii=False,
    )


class TestCanvasApplyBatch:
    @pytest.mark.asyncio
    async def testOneShotBuildCommitsAllOpsInOneVersion(self, canvas_env):
        operations = [
            {"op": "add_node", "id": "start", "node_type": "builtin:start", "position": {"x": 0, "y": 0}},
            {
                "op": "add_node",
                "id": "llm",
                "node_type": "builtin:llm",
                "position": {"x": 200, "y": 0},
                "config": {"prompt": "hi"},
            },
            {"op": "add_node", "id": "end", "node_type": "builtin:end", "position": {"x": 400, "y": 0}},
            {"op": "connect", "source_node": "start", "target_node": "llm"},
            {"op": "connect", "source_node": "llm", "target_node": "end"},
            {"op": "set_config", "node_id": "llm", "values": {"temperature": 0.2}},
            {"op": "layout"},
        ]
        result = await canvas_env.service.apply_batch(
            canvas_env.canvas_id, operations, session_id="session-1"
        )

        assert result["version"] == 2
        assert result["node_count"] == 3
        assert result["edge_count"] == 2
        record = canvas_env.store.get(canvas_env.canvas_id)
        assert [node["id"] for node in record["nodes"]] == ["start", "llm", "end"]
        llm = next(node for node in record["nodes"] if node["id"] == "llm")
        assert llm["config"]["temperature"] == 0.2
        assert len(canvas_env.events) == 1
        event = canvas_env.events[0]
        assert event["op"] == "batch"
        assert event["version"] == 2
        assert len(event["data"]["nodes"]) == 3
        assert len(event["data"]["edges"]) == 2

    @pytest.mark.asyncio
    async def testInvalidStepLeavesWholeBatchUnwritten(self, canvas_env):
        operations = [
            {"op": "add_node", "id": "good", "node_type": "builtin:start"},
            {"op": "add_node", "id": "bad", "node_type": "custom:no_such_type"},
        ]
        with pytest.raises(CanvasOpError) as exc:
            await canvas_env.service.apply_batch(canvas_env.canvas_id, operations)
        assert "批次第 2 步" in str(exc.value)

        record = canvas_env.store.get(canvas_env.canvas_id)
        assert record["version"] == 1
        assert record["nodes"] == []
        assert canvas_env.events == []

    @pytest.mark.asyncio
    async def testLaterStepFailureRollsBackEarlierAdds(self, canvas_env):
        operations = [
            {"op": "add_node", "id": "start", "node_type": "builtin:start"},
            {"op": "add_node", "id": "end", "node_type": "builtin:end"},
            {"op": "connect", "source_node": "start", "target_node": "missing"},
        ]
        with pytest.raises(CanvasOpError):
            await canvas_env.service.apply_batch(canvas_env.canvas_id, operations)

        record = canvas_env.store.get(canvas_env.canvas_id)
        assert record["version"] == 1
        assert record["nodes"] == []
        assert record["edges"] == []

    @pytest.mark.asyncio
    async def testRemoveCascadeAndReferenceFailureAreAtomic(self, canvas_env):
        first = await canvas_env.service.apply_batch(
            canvas_env.canvas_id,
            [
                {"op": "add_node", "id": "start", "node_type": "builtin:start"},
                {"op": "add_node", "id": "end", "node_type": "builtin:end"},
                {"op": "connect", "source_node": "start", "target_node": "end"},
            ],
            session_id="session-1",
        )
        assert first["version"] == 2

        with pytest.raises(CanvasOpError):
            await canvas_env.service.apply_batch(
                canvas_env.canvas_id,
                [
                    {"op": "remove_node", "node_id": "end"},
                    {"op": "connect", "source_node": "start", "target_node": "end"},
                ],
                base_version=2,
            )
        record = canvas_env.store.get(canvas_env.canvas_id)
        assert record["version"] == 2
        assert [node["id"] for node in record["nodes"]] == ["start", "end"]
        assert len(record["edges"]) == 1

        third = await canvas_env.service.apply_batch(
            canvas_env.canvas_id,
            [{"op": "remove_node", "node_id": "end"}],
            base_version=2,
        )
        assert third["version"] == 3
        record = canvas_env.store.get(canvas_env.canvas_id)
        assert [node["id"] for node in record["nodes"]] == ["start"]
        assert record["edges"] == []

    @pytest.mark.asyncio
    async def testStaleBaseVersionDoesNotWrite(self, canvas_env):
        with pytest.raises(CanvasVersionConflict):
            await canvas_env.service.apply_batch(
                canvas_env.canvas_id,
                [{"op": "add_node", "id": "start", "node_type": "builtin:start"}],
                base_version=99,
            )
        record = canvas_env.store.get(canvas_env.canvas_id)
        assert record["version"] == 1
        assert record["nodes"] == []

    @pytest.mark.asyncio
    async def testEmptyBatchRejected(self, canvas_env):
        with pytest.raises(CanvasOpError):
            await canvas_env.service.apply_batch(canvas_env.canvas_id, [])

    def testToolRegisteredGatedAndNonReproducible(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, _NON_REPRODUCIBLE_TOOLS

        assert "canvas_apply_batch" in _BUILTIN_SCHEMAS
        assert "canvas_apply_batch" in ToolExecutor._builtin_dispatch
        assert "canvas_apply_batch" in ToolExecutor._BUILD_GATED_TOOLS
        assert "canvas_apply_batch" in _NON_REPRODUCIBLE_TOOLS

    @pytest.mark.asyncio
    async def testToolHandlerReturnsOneVersion(self, canvas_env, monkeypatch):
        monkeypatch.setattr(
            "neurova.tool_executor.get_canvas_op_service",
            lambda: canvas_env.service,
        )
        result = await _executor()._execute_builtin_tool(
            "canvas_apply_batch",
            {
                "canvas_id": canvas_env.canvas_id,
                "operations": [
                    {"op": "add_node", "id": "start", "node_type": "builtin:start"},
                    {"op": "add_node", "id": "end", "node_type": "builtin:end"},
                    {"op": "connect", "source_node": "start", "target_node": "end"},
                ],
                "base_version": 1,
            },
        )
        assert result["success"] is True, result
        assert result["version"] == 2
        assert result["node_count"] == 2

    @pytest.mark.asyncio
    async def testBuildGateBlocksBatchBeforeApproval(
        self, canvas_env, tmp_path, monkeypatch
    ):
        manager = bs.BuildSessionManager(
            store_path=str(tmp_path / "build.json"),
            llm_call=lambda prompt: _assessment(False),
        )
        monkeypatch.setattr(
            "neurova.build_mode.get_build_session_manager", lambda: manager
        )
        session = await manager.create("建一张画布", "agent-x", "u1")
        setCurrentBuildSessionId(session.session_id)
        try:
            result = await _executor()._execute_builtin_tool(
                "canvas_apply_batch",
                {
                    "canvas_id": canvas_env.canvas_id,
                    "operations": [
                        {"op": "add_node", "id": "start", "node_type": "builtin:start"}
                    ],
                },
            )
        finally:
            resetCurrentBuildSessionId()

        assert result["success"] is False
        assert result["status"] == "clarification_required"
        assert canvas_env.store.get(canvas_env.canvas_id)["version"] == 1
