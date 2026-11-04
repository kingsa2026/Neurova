"""N0：ask_user 工具与画布写工具的服务端就绪门。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neurova.build_mode import build_session as bs
from neurova.core.build_context import (
    resetCurrentBuildSessionId,
    setCurrentBuildSessionId,
)
from neurova.tool_executor import ToolExecutor


def _assessment(ready: bool, questions=None):
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
            "questions": questions or [],
        },
        ensure_ascii=False,
    )


def _executor():
    agent = SimpleNamespace(
        _current_user_id="u1",
        config=SimpleNamespace(agent_id="agent-x", user_id="u1"),
    )
    return ToolExecutor(agent)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    responses = [
        _assessment(
            False,
            [
                {
                    "id": "q1",
                    "question": "目标是什么？",
                    "kind": "text",
                    "why": "目标不明",
                    "impact": "决定节点",
                }
            ],
        ),
        _assessment(True),
    ]
    calls = {"n": 0}

    def llm(prompt):
        value = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return value

    instance = bs.BuildSessionManager(store_path=str(tmp_path / "build.json"), llm_call=llm)
    monkeypatch.setattr("neurova.build_mode.get_build_session_manager", lambda: instance)
    yield instance
    resetCurrentBuildSessionId()
    bs.reset_build_session_manager()


class TestAskUserTool:
    def test_schemaAndDispatchRegistered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, get_builtin_tool_capability

        assert "ask_user" in _BUILTIN_SCHEMAS
        assert ToolExecutor._builtin_dispatch.get("ask_user") == "_execute_ask_user"
        cap = get_builtin_tool_capability("ask_user")
        assert cap is not None and cap.readOnly is False

    @pytest.mark.asyncio
    async def test_askUserPausesBuild(self, manager):
        session = await manager.create("搭一条流程", "agent-x", "u1")
        await manager.answer(session.session_id, [{"id": "q1", "custom": "复盘广告"}])
        manager.approve(session.session_id, "u1")
        manager.markBuilding(session.session_id)
        setCurrentBuildSessionId(session.session_id)

        result = await _executor()._execute_builtin_tool(
            "ask_user",
            {
                "question": "用哪个店铺？",
                "kind": "choice",
                "options": ["店铺 A", "店铺 B"],
                "why": "需要 profileId",
            },
        )

        assert result["success"] is True
        assert result["status"] == "paused"
        assert result["interaction_id"]
        assert manager.get(session.session_id).status == bs.STATUS_BLOCKED


class TestBuildWriteGate:
    @pytest.mark.asyncio
    async def testCanvasWriteRefusedBeforeReady(self, manager, monkeypatch):
        session = await manager.create("搭一条流程", "agent-x", "u1")
        setCurrentBuildSessionId(session.session_id)
        called = AsyncMock(return_value={"success": True})
        monkeypatch.setattr(ToolExecutor, "_execute_canvas_create", called)

        result = await _executor()._execute_builtin_tool("canvas_create", {"name": "x"})

        assert result["success"] is False
        assert result["status"] == "clarification_required"
        assert result["build_session_id"] == session.session_id
        called.assert_not_awaited()

    @pytest.mark.asyncio
    async def testCanvasWriteAllowedAfterApproval(self, manager, monkeypatch):
        session = await manager.create("搭一条流程", "agent-x", "u1")
        await manager.answer(session.session_id, [{"id": "q1", "custom": "复盘广告"}])
        manager.approve(session.session_id, "u1")
        manager.markBuilding(session.session_id)
        setCurrentBuildSessionId(session.session_id)
        called = AsyncMock(return_value={"success": True})
        monkeypatch.setattr(ToolExecutor, "_execute_canvas_create", called)

        result = await _executor()._execute_builtin_tool("canvas_create", {"name": "x"})

        assert result["success"] is True
        called.assert_awaited_once()

    @pytest.mark.asyncio
    async def testManualCanvasWithoutBuildContextStillWorks(self, monkeypatch):
        resetCurrentBuildSessionId()
        called = AsyncMock(return_value={"success": True})
        monkeypatch.setattr(ToolExecutor, "_execute_canvas_create", called)

        result = await _executor()._execute_builtin_tool("canvas_create", {"name": "x"})

        assert result["success"] is True
        called.assert_awaited_once()

    @pytest.mark.asyncio
    async def testBlockedBuildCannotWriteEvenAfterApproval(self, manager, monkeypatch):
        session = await manager.create("搭一条流程", "agent-x", "u1")
        await manager.answer(session.session_id, [{"id": "q1", "custom": "复盘广告"}])
        manager.approve(session.session_id, "u1")
        manager.markBuilding(session.session_id)
        manager.ask(session.session_id, "选哪个？", options=["A", "B"])
        setCurrentBuildSessionId(session.session_id)
        called = AsyncMock(return_value={"success": True})
        monkeypatch.setattr(ToolExecutor, "_execute_canvas_create", called)

        result = await _executor()._execute_builtin_tool("canvas_create", {"name": "x"})

        assert result["success"] is False
        assert result["status"] == "clarification_required"
        called.assert_not_awaited()
