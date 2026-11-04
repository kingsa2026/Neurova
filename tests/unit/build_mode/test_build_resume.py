"""§12.4：交互回答后服务端自动拉起 Agent 回合。"""

from __future__ import annotations

import json

import pytest

from neurova.build_mode import build_session as bs
from neurova.build_mode.resume import buildResumePrompt, resumeBuildInteraction
from neurova.sync.session_sync_manager import EventType


def _assessment(ready: bool = True):
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
            "build_plan": {"summary": "按 ACOS 复盘并调预算"},
            "questions": [],
        },
        ensure_ascii=False,
    )


class _FakeAgent:
    def __init__(self, onChat=None, error: str = ""):
        self.calls = []
        self.onChat = onChat
        self.error = error

    async def chat(self, user_input, session_id=None, metadata=None, **kwargs):
        self.calls.append(
            {"prompt": user_input, "session_id": session_id, "metadata": metadata}
        )
        if self.error:
            raise RuntimeError(self.error)
        if self.onChat is not None:
            self.onChat()
        return {"text": "继续完成"}


class _FakeSync:
    def __init__(self):
        self.events = []
        self.registered = None

    def register_or_create_session(self, **kwargs):
        self.registered = kwargs

    async def broadcast_event(self, session_id, event):
        self.events.append((session_id, event))
        return 1


@pytest.fixture
def manager(tmp_path):
    instance = bs.BuildSessionManager(
        store_path=str(tmp_path / "build.json"),
        llm_call=lambda prompt: _assessment(True),
    )
    yield instance


async def _building_session(manager):
    session = await manager.create("帮我搭一条广告复盘流程", "agent-x", "u1")
    manager.approve(session.session_id, "u1")
    return manager.markBuilding(session.session_id)


def _ask(manager, session_id, *, kind="choice", options=None, secret_key="", chat_session_id="chat-1"):
    return manager.ask(
        session_id,
        "选哪个店铺？" if kind != "secret" else "请提供广告凭据",
        options=options or [{"label": "店铺 A"}, {"label": "店铺 B"}],
        kind=kind,
        allow_custom=True,
        why="需要数据源",
        impact="影响拉取",
        secret_key=secret_key,
        chat_session_id=chat_session_id,
    )


class TestBuildResume:
    @pytest.mark.asyncio
    async def testAnswerStartsServerTurnAndPublishesNextInteraction(self, manager):
        session = await _building_session(manager)
        ask = _ask(manager, session.session_id)
        manager.answerInteraction(
            session.session_id, ask["interaction_id"], {"selected": ["店铺 A"]}
        )

        agent = _FakeAgent(
            onChat=lambda: manager.ask(
                session.session_id,
                "预算上限？",
                options=["100", "200"],
                chat_session_id="chat-1",
            )
        )
        sync = _FakeSync()
        result = await resumeBuildInteraction(
            session.session_id,
            ask["interaction_id"],
            agentProvider=lambda agent_id: agent,
            sessionSyncManager=sync,
            manager=manager,
        )

        assert result["started"] is True
        assert result["status"] == "completed"
        assert result["chat_session_id"] == "chat-1"
        assert agent.calls and agent.calls[0]["session_id"] == "chat-1"
        assert agent.calls[0]["metadata"]["build_resume"] is True
        assert "店铺 A" in agent.calls[0]["prompt"]
        assert "按 ACOS 复盘并调预算" in agent.calls[0]["prompt"]
        eventTypes = [event.event_type for _, event in sync.events]
        assert EventType.BUILD_INTERACTION in eventTypes
        interactionEvent = next(
            event for _, event in sync.events if event.event_type == EventType.BUILD_INTERACTION
        )
        assert interactionEvent.payload["build_session_id"] == session.session_id
        assert interactionEvent.payload["question"] == "预算上限？"

    @pytest.mark.asyncio
    async def testNoChatSessionFallsBackToFrontendPrompt(self, manager):
        session = await _building_session(manager)
        ask = _ask(manager, session.session_id, chat_session_id="")
        manager.answerInteraction(
            session.session_id, ask["interaction_id"], {"selected": ["店铺 A"]}
        )
        agent = _FakeAgent()
        result = await resumeBuildInteraction(
            session.session_id,
            ask["interaction_id"],
            agentProvider=lambda agent_id: agent,
            sessionSyncManager=_FakeSync(),
            manager=manager,
        )
        assert result["started"] is False
        assert result["reason"] == "no_chat_session"
        assert result["resume_prompt"]
        assert agent.calls == []

    @pytest.mark.asyncio
    async def testAgentFailureIsPublishedNotFaked(self, manager):
        session = await _building_session(manager)
        ask = _ask(manager, session.session_id)
        manager.answerInteraction(
            session.session_id, ask["interaction_id"], {"selected": ["店铺 A"]}
        )
        sync = _FakeSync()
        result = await resumeBuildInteraction(
            session.session_id,
            ask["interaction_id"],
            agentProvider=lambda agent_id: _FakeAgent(error="model unavailable"),
            sessionSyncManager=sync,
            manager=manager,
        )
        assert result["started"] is True
        assert result["status"] == "failed"
        assert "model unavailable" in result["error"]
        assert any(
            event.event_type == EventType.BUILD_RESUME_FAILED
            for _, event in sync.events
        )

    @pytest.mark.asyncio
    async def testSecretAnswerNeverEntersPrompt(self, manager):
        session = await _building_session(manager)
        ask = _ask(
            manager,
            session.session_id,
            kind="secret",
            options=[],
            secret_key="NEUROVA_BUILD_RESUME_SECRET",
        )
        manager.answerInteraction(
            session.session_id,
            ask["interaction_id"],
            {"secret_value": "super-secret-value"},
        )
        prompt = buildResumePrompt(
            manager.get(session.session_id),
            next(
                item
                for item in manager.get(session.session_id).interactions
                if item["interaction_id"] == ask["interaction_id"]
            ),
        )
        assert "super-secret-value" not in prompt
        assert "凭据已配置" in prompt
