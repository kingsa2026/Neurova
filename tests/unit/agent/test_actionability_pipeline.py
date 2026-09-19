"""任务2 切片4/6：actionability 读侧 —— 从会话历史取回 turn_origin（端到端使能）。

覆盖：
- SessionManager.get_recent_origins 能从落盘消息 metadata 读回 turn_origin（写→读通）。
- _recent_human_involved 经 get_recent_origins 判定，人类/存疑/空/异常一律放行（fail-open）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline


# ── 真实 SessionManager：写侧落 origin，读侧取回 ─────────────────
class TestRecentOriginsRoundTrip:
    @pytest.fixture
    def sm(self, tmp_path):
        from neurova.session_manager import SessionManager

        sm = SessionManager()
        sm._sessions_dir = Path(tmp_path) / "sessions"
        sm._sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def test_get_recent_origins_returns_user_turn_origins(self, sm):
        sm.add_message("agt", "s1", "q1", "a1", metadata={"turn_origin": "bot_peer"})
        sm.add_message("agt", "s1", "q2", "a2", metadata={"turn_origin": "human"})
        origins = sm.get_recent_origins("agt", "s1", max_messages=10)
        # 只看 user 轮的来源（助手轮是本 agent 自己的回复，不计入"谁发起")
        assert list(origins) == ["bot_peer", "human"]

    def test_get_recent_origins_empty_when_no_turn_origin(self, sm):
        sm.add_message("agt", "s2", "q", "a", metadata={})
        origins = sm.get_recent_origins("agt", "s2", max_messages=10)
        assert list(origins) == [None]


# ── 管线读侧接线（裸实例 + 假 session_manager.get_recent_origins）──
def _pipe(origins):
    p = object.__new__(ChatPipeline)

    class _SM:
        def get_recent_origins(self, agent_id=None, session_id=None, max_messages=None):
            return origins

    p._agent = SimpleNamespace(config=SimpleNamespace(agent_id="a1"), session_manager=_SM())
    return p


def _ctx(metadata):
    return ChatContext(user_input="x", session_id="s1", metadata=metadata)


@pytest.mark.asyncio
async def test_disabled_leaves_ctx_untouched():
    p = _pipe(["bot_peer"])
    ctx = _ctx({"turn_origin": "bot_peer"})
    with patch("neurova.agent.chat_pipeline.get_actionability_config", lambda *a, **k: (False, 20)):
        await p._check_actionability(ctx)
    assert ctx.metadata.get("actionable") is None


@pytest.mark.asyncio
async def test_human_origin_not_suppressed():
    p = _pipe(["bot_peer"])
    ctx = _ctx({"turn_origin": "human"})
    with patch("neurova.agent.chat_pipeline.get_actionability_config", lambda *a, **k: (True, 20)):
        await p._check_actionability(ctx)
    assert ctx.metadata.get("actionable") is None


@pytest.mark.asyncio
async def test_machine_origin_all_machine_history_suppresses():
    p = _pipe(["bot_peer", "bot_peer", "bot_peer"])
    ctx = _ctx({"turn_origin": "bot_peer"})
    with patch("neurova.agent.chat_pipeline.get_actionability_config", lambda *a, **k: (True, 20)):
        await p._check_actionability(ctx)
    assert ctx.metadata.get("actionable") is False
    assert ctx.metadata.get("actionable_origin") == "bot_peer"


@pytest.mark.asyncio
async def test_machine_origin_with_recent_human_allows():
    p = _pipe(["human", "bot_peer"])
    ctx = _ctx({"turn_origin": "bot_peer"})
    with patch("neurova.agent.chat_pipeline.get_actionability_config", lambda *a, **k: (True, 20)):
        await p._check_actionability(ctx)
    assert ctx.metadata.get("actionable") is None  # 近期有人类 → 放行


@pytest.mark.asyncio
async def test_unknown_origin_in_history_allows():
    p = _pipe([None, "bot_peer"])  # None=来源未知（旧消息未带 origin）→ 按人类计
    ctx = _ctx({"turn_origin": "bot_peer"})
    with patch("neurova.agent.chat_pipeline.get_actionability_config", lambda *a, **k: (True, 20)):
        await p._check_actionability(ctx)
    assert ctx.metadata.get("actionable") is None


@pytest.mark.asyncio
async def test_no_history_fails_open():
    p = _pipe([])
    ctx = _ctx({"turn_origin": "swarm"})
    with patch("neurova.agent.chat_pipeline.get_actionability_config", lambda *a, **k: (True, 20)):
        await p._check_actionability(ctx)
    assert ctx.metadata.get("actionable") is None


@pytest.mark.asyncio
async def test_session_manager_error_fails_open():
    p = object.__new__(ChatPipeline)

    class _Boom:
        def get_recent_origins(self, *a, **k):
            raise RuntimeError("db down")

    p._agent = SimpleNamespace(config=SimpleNamespace(agent_id="a1"), session_manager=_Boom())
    ctx = _ctx({"turn_origin": "bot_peer"})
    with patch("neurova.agent.chat_pipeline.get_actionability_config", lambda *a, **k: (True, 20)):
        await p._check_actionability(ctx)  # 不得抛
    assert ctx.metadata.get("actionable") is None
