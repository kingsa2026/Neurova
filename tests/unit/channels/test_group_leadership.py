"""群领导选举（spec 2026-09-19-group-leadership-election）实现测试。

覆盖 §10：仲裁器纯逻辑（申领/续租/拒答/过期接管/回收）、配置读取、
channel_router 集成（leader 应答 / 非 leader 静默 / 关闭现状 / fail-open / 人类仍答）。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from neurova.channels.base import ChannelMessage
from neurova.channels.channel_router import make_handler
from neurova.channels.group_leadership import (
    GroupLeadershipArbiter,
    get_group_leadership_arbiter,
    reset_group_leadership_arbiter,
)

GK = ("telegram", "g1")


# ── 纯逻辑：仲裁器 ─────────────────────────────────────────────
def test_first_candidate_claims():
    a = GroupLeadershipArbiter()
    assert a.may_respond(GK, "a1", now=100.0, ttl=90) is True
    assert a.current_leader(GK, now=100.0) == "a1"


def test_leader_renews_same_leader():
    a = GroupLeadershipArbiter()
    a.may_respond(GK, "a1", now=100.0, ttl=90)
    assert a.may_respond(GK, "a1", now=150.0, ttl=90) is True
    assert a.current_leader(GK, now=150.0) == "a1"


def test_nonleader_denied_within_lease():
    a = GroupLeadershipArbiter()
    a.may_respond(GK, "a1", now=100.0, ttl=90)          # leader until 190
    assert a.may_respond(GK, "a2", now=150.0, ttl=90) is False
    assert a.current_leader(GK, now=150.0) == "a1"


def test_takeover_after_lease_expiry():
    a = GroupLeadershipArbiter()
    a.may_respond(GK, "a1", now=100.0, ttl=90)          # expires 190
    assert a.may_respond(GK, "a2", now=195.0, ttl=90) is True
    assert a.current_leader(GK, now=195.0) == "a2"


def test_stale_records_evicted():
    a = GroupLeadershipArbiter()
    a.may_respond(("telegram", "gA"), "a1", now=100.0, ttl=1)
    a.may_respond(("telegram", "gB"), "a1", now=100.0, ttl=1)
    # 远未来时刻申领新群，触发对更早过期记录的回收
    a.may_respond(("telegram", "gC"), "a1", now=10_000.0, ttl=90)
    assert a.current_leader(("telegram", "gA"), now=10_000.0) is None
    assert a.current_leader(("telegram", "gB"), now=10_000.0) is None


# ── 配置读取 ───────────────────────────────────────────────────
def test_config_default_off(tmp_path, monkeypatch):
    from neurova.channels.group_leadership import get_group_leadership_config

    monkeypatch.delenv("NEUROVA_GROUP_LEADERSHIP", raising=False)
    enabled, ttl = get_group_leadership_config(path=tmp_path / "s.json")
    assert enabled is False
    assert ttl == 90


def test_config_persisted_on(tmp_path, monkeypatch):
    from neurova.channels.group_leadership import get_group_leadership_config
    from neurova.core.app_settings import save_app_settings

    monkeypatch.delenv("NEUROVA_GROUP_LEADERSHIP", raising=False)
    save_app_settings("routing", {"group_leadership_enabled": True, "group_lease_ttl_seconds": 30},
                      path=tmp_path / "s.json")
    enabled, ttl = get_group_leadership_config(path=tmp_path / "s.json")
    assert enabled is True
    assert ttl == 30


def test_config_env_forces_off(tmp_path, monkeypatch):
    from neurova.channels.group_leadership import get_group_leadership_config
    from neurova.core.app_settings import save_app_settings

    monkeypatch.setenv("NEUROVA_GROUP_LEADERSHIP", "off")
    save_app_settings("routing", {"group_leadership_enabled": True}, path=tmp_path / "s.json")
    enabled, _ = get_group_leadership_config(path=tmp_path / "s.json")
    assert enabled is False


# ── channel_router 集成 ────────────────────────────────────────
def _msg(agent_id):
    return ChannelMessage(
        channel_type="telegram", message_id="m", sender_id="u", sender_name="n",
        content="hello", chat_id="g1", chat_type="group",
        metadata={"agent_id": agent_id},
    )


def _fake_manager():
    return SimpleNamespace(
        resolve_session_scope_id=lambda m: "scope-g1",
        get_adapter=lambda *a, **k: None,  # _channel_cfg → {} （open，无 require_mention）
    )


def _fake_agent():
    ag = SimpleNamespace()
    ag.config = SimpleNamespace(owner_user_id="")
    ag.chat = AsyncMock(return_value={"text": "ok"})
    return ag


@pytest.fixture(autouse=True)
def _reset_arbiter():
    reset_group_leadership_arbiter()
    yield
    reset_group_leadership_arbiter()


@pytest.mark.asyncio
async def test_leader_replies_nonleader_silent():
    handler = make_handler(_fake_manager(), agent_lookup=lambda aid: _fake_agent())
    with patch("neurova.channels.channel_router.get_group_leadership_config",
               lambda *a, **k: (True, 90)):
        first = await handler(_msg("a1"))         # a1 成为 leader → 应答
        second = await handler(_msg("a2"))        # a2 非 leader（租约内）→ 静默
    assert first == ["ok"]
    assert second is None


@pytest.mark.asyncio
async def test_disabled_keeps_current_behavior():
    handler = make_handler(_fake_manager(), agent_lookup=lambda aid: _fake_agent())
    with patch("neurova.channels.channel_router.get_group_leadership_config",
               lambda *a, **k: (False, 90)):
        r1 = await handler(_msg("a1"))
        r2 = await handler(_msg("a2"))
    assert r1 == ["ok"] and r2 == ["ok"]  # 关闭时两个 agent 都按原逻辑应答


@pytest.mark.asyncio
async def test_fail_open_on_arbiter_error():
    handler = make_handler(_fake_manager(), agent_lookup=lambda aid: _fake_agent())
    boom = SimpleNamespace(may_respond=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with patch("neurova.channels.channel_router.get_group_leadership_config",
               lambda *a, **k: (True, 90)), \
         patch("neurova.channels.channel_router.get_group_leadership_arbiter", return_value=boom):
        r = await handler(_msg("a1"))
    assert r == ["ok"]  # 仲裁异常 → 放行（安全侧）
