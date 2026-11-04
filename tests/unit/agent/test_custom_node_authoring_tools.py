"""N3：自定义节点 CRUD 工具（draft → 批次激活）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from neurova.build_mode import build_session as bs
from neurova.collaboration.neurflow.custom_nodes import CustomNodeService
from neurova.collaboration.neurflow.node_registry import (
    get_node_registry,
    reset_node_registry,
)
from neurova.collaboration.neurflow.storage import NeurflowStorage
from neurova.core.build_context import (
    resetCurrentBuildSessionId,
    setCurrentBuildSessionId,
)
from neurova.tool_executor import ToolExecutor


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
            "build_plan": {"summary": "构建流程"},
            "questions": [] if ready else [
                {"id": "q1", "question": "目标？", "kind": "text", "why": "目标不明", "impact": "决定节点"}
            ],
        },
        ensure_ascii=False,
    )


def _executor():
    return ToolExecutor(
        SimpleNamespace(
            _current_user_id="u1",
            config=SimpleNamespace(agent_id="agent-x", user_id="u1"),
        )
    )


@pytest.fixture
def service(tmp_path, monkeypatch):
    reset_node_registry()
    instance = CustomNodeService(
        storage=NeurflowStorage(),
        registry=get_node_registry(),
    )
    monkeypatch.setattr(
        "neurova.collaboration.neurflow.custom_nodes.get_custom_node_service",
        lambda: instance,
    )
    yield instance
    for node_type in ("custom:n3_test", "custom:n3_draft"):
        try:
            instance.delete_node(node_type)
        except Exception:
            pass
    reset_node_registry()


@pytest.fixture
def approved_session(tmp_path, monkeypatch, service):
    manager = bs.BuildSessionManager(
        store_path=str(tmp_path / "build.json"),
        llm_call=lambda prompt: _assessment(True),
    )
    monkeypatch.setattr("neurova.build_mode.get_build_session_manager", lambda: manager)
    yield manager
    resetCurrentBuildSessionId()


async def _approved(manager):
    session = await manager.create("搭一条流程", "agent-x", "u1")
    manager.approve(session.session_id, "u1")
    manager.markBuilding(session.session_id)
    setCurrentBuildSessionId(session.session_id)
    return session


def _spec(node_type="custom:n3_test"):
    return {
        "type": node_type,
        "label": "N3 测试节点",
        "tier": "declarative",
        "executor_body": {"template": "处理 {{input}}"},
        "form_schema": [{"id": "input", "type": "text", "required": True}],
        "env_requirements": ["NEUROVA_N3_TEST"],
    }


class TestCustomNodeAuthoring:
    def test_toolsRegistered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for name in (
            "custom_node_create",
            "custom_node_update",
            "custom_node_activate",
            "custom_node_delete",
        ):
            assert name in _BUILTIN_SCHEMAS
            assert name in ToolExecutor._builtin_dispatch

    @pytest.mark.asyncio
    async def test_gateBlocksBeforeApproval(self, tmp_path, monkeypatch, service):
        manager = bs.BuildSessionManager(
            store_path=str(tmp_path / "build.json"),
            llm_call=lambda prompt: _assessment(False),
        )
        monkeypatch.setattr("neurova.build_mode.get_build_session_manager", lambda: manager)
        session = await manager.create("搭一条流程", "agent-x", "u1")
        setCurrentBuildSessionId(session.session_id)

        result = await _executor()._execute_builtin_tool(
            "custom_node_create", {"spec": _spec()}
        )
        assert result["success"] is False
        assert result["status"] == "clarification_required"
        assert service.get_node("custom:n3_test") is None

    @pytest.mark.asyncio
    async def test_draftActivateAndActiveMutationRefused(
        self, approved_session, service
    ):
        session = await _approved(approved_session)

        created = await _executor()._execute_builtin_tool(
            "custom_node_create", {"spec": _spec()}
        )
        assert created["success"] is True
        assert created["node"]["status"] == "draft"
        assert created["node"]["batch_id"] == session.batch_id

        activated = await _executor()._execute_builtin_tool(
            "custom_node_activate", {"node_type": "custom:n3_test"}
        )
        assert activated["success"] is True
        assert activated["node"]["status"] == "active"

        update = await _executor()._execute_builtin_tool(
            "custom_node_update",
            {"node_type": "custom:n3_test", "spec": {"label": "改名"}},
        )
        assert update["success"] is False
        assert "draft" in update["error"]

        delete = await _executor()._execute_builtin_tool(
            "custom_node_delete", {"node_type": "custom:n3_test"}
        )
        assert delete["success"] is False

    @pytest.mark.asyncio
    async def test_updateAndDeleteDraft(self, approved_session, service):
        await _approved(approved_session)
        created = await _executor()._execute_builtin_tool(
            "custom_node_create", {"spec": _spec("custom:n3_draft")}
        )
        assert created["success"] is True

        updated = await _executor()._execute_builtin_tool(
            "custom_node_update",
            {
                "node_type": "custom:n3_draft",
                "spec": {"label": "改后的节点", "env_requirements": ["NEUROVA_N3_NEW"]},
            },
        )
        assert updated["success"] is True
        assert updated["node"]["label"] == "改后的节点"
        assert updated["node"]["env_requirements"] == ["NEUROVA_N3_NEW"]

        deleted = await _executor()._execute_builtin_tool(
            "custom_node_delete", {"node_type": "custom:n3_draft"}
        )
        assert deleted["success"] is True
        assert service.get_node("custom:n3_draft") is None
