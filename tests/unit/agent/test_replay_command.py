# -*- coding: utf-8 -*-
"""P1-6 尾巴：/replay 重放崩溃悬空轮。

- 悬空轮（末条 user 无回复 + 账本有匹配视图）→ /replay 改写输入并钉住
  账本字节级视图；
- 无悬空轮 / 账本无匹配 → command_dispatched 诚实短路；
- 重放轮 Step 0.8 跳过提前落盘（用户消息不落两遍）；
- build_context(pinned_view=...) 直接使用钉住视图（不重新推导信封）。
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context import injection_ledger as il
from neurova.context.orchestrator import ContextOrchestrator
from neurova.session_manager import SessionManager


@pytest.fixture
def dataRoot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "neurova.core.data_root.resolveDataPath",
        lambda *parts, **k: tmp_path.joinpath(*parts),
    )
    return tmp_path


@pytest.fixture
def sm(tmp_path):
    manager = SessionManager()
    manager._sessions_dir = tmp_path / "sessions"
    manager._sessions_dir.mkdir(parents=True, exist_ok=True)
    return manager


@pytest.fixture
def pipeline(sm, tmp_path):
    from neurova.agent.chat_pipeline import ChatPipeline
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator.__new__(ContextOrchestrator)
    orch._context_health = orch._emptyContextHealth()
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = SimpleNamespace(
        conversation_history=[],
        context_orchestrator=orch,
        session_manager=sm,
        config=SimpleNamespace(agent_id="a-replay"),
        memory_agent=None,
    )
    return pipeline


def _ctx(userInput, sessionId="s-replay"):
    return SimpleNamespace(
        session_id=sessionId, user_input=userInput, metadata=None, event_emitter=None
    )


def _seedDangling(sm, sessionId="s-replay", agentId="a-replay", userInput="输入一"):
    """悬空轮：只有 user 消息，没有 assistant 回复。"""
    sm.save_message(agentId, sessionId, "user", userInput, user_id="u-1")


class TestReplayCommand:
    def test_replay_rewrites_input_and_pins_view(self, pipeline, sm, dataRoot):
        _seedDangling(sm)
        il.recordInjection("s-replay", "final_user_view", "<memories>召回</memories>\n\n输入一")
        ctx = _ctx("/replay")

        asyncio.run(pipeline._check_replay_command(ctx))

        assert ctx.user_input == "输入一"
        assert ctx.metadata["replay"] is True
        assert ctx.metadata["replay_pinned_view"] == "<memories>召回</memories>\n\n输入一"
        assert ctx.metadata.get("command_dispatched") is None

    def test_no_dangling_short_circuits(self, pipeline, sm):
        sm.save_message("a-replay", "s-replay", "user", "输入一", user_id="u-1")
        sm.save_message("a-replay", "s-replay", "assistant", "回复", user_id="u-1")
        ctx = _ctx("/replay")

        asyncio.run(pipeline._check_replay_command(ctx))

        assert ctx.metadata["command_dispatched"] is True
        assert "没有待重放" in ctx.reply

    def test_no_ledger_row_short_circuits(self, pipeline, sm):
        _seedDangling(sm)
        ctx = _ctx("/replay")

        asyncio.run(pipeline._check_replay_command(ctx))

        assert ctx.metadata["command_dispatched"] is True
        assert "注入账本" in ctx.reply

    def test_non_replay_input_ignored(self, pipeline):
        ctx = _ctx("普通问题")
        asyncio.run(pipeline._check_replay_command(ctx))
        assert ctx.metadata is None


class TestReplaySkipsEarlyPersist:
    def test_step_persist_skips_on_replay(self, pipeline, sm):
        _seedDangling(sm)
        ctx = _ctx("输入一")
        ctx.metadata = {"replay": True}

        asyncio.run(pipeline._step_persist_user_early(ctx))

        assert ctx.user_message_persisted is True
        # 用户消息不落两遍：会话里仍只有一条 user
        userRows = [
            m for m in sm.get_recent_context(agent_id="a-replay", session_id="s-replay")
            if m.get("role") == "user" and m.get("content") == "输入一"
        ]
        assert len(userRows) == 1


class TestOrchestratorPinnedView:
    def _orchestrator(self):
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.config.constitution = ""
        mock_agent.config.behavior_rules = []
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = "你是一个AI助手"
        mock_agent.personality = "友好"
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        return ContextOrchestrator(mock_agent, use_pool=True, auto_tag=True)

    def test_pinned_view_used_verbatim(self):
        orch = self._orchestrator()
        pinned = "<memories>召回行</memories>\n\n输入一"
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as mock_desc:
            mock_desc.return_value = "可用工具：file_read"
            result = asyncio.run(orch.build_context(user_input="输入一", pinned_view=pinned))
        lastUser = [m for m in result if m.get("role") == "user"][-1]
        assert lastUser["content"] == pinned, "钉住视图必须字节级原样使用"
