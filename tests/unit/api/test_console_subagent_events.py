# -*- coding: utf-8 -*-
"""H-4 闭环读面：/console/chat/subagents/{id}/events 的归属判定与载荷。

- 管理员：任意 run 可读（含台账无行的早期运行）；
- 非管理员：只读自己的 run（台账行 user_id 判属）；台账无行 fail-closed 403；
- 载荷：事件按因果链序完整返回（spawned→…→terminal）。
"""

from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from neurova.agent.swarm_event_log import appendRunEvent
from neurova.api.deps import get_current_user
from neurova.api.endpoints.console import router
from neurova.core.agent_run_store import AgentRunStore


def _makeClient(store, user):
    app = FastAPI()
    app.include_router(router)

    async def _mock_user(request: Request):
        return user

    app.dependency_overrides[get_current_user] = _mock_user
    with patch("neurova.core.agent_run_store.get_agent_run_store", return_value=store):
        yield TestClient(app)


def _seedRun(store, subagentId, userId):
    store.intake("member-x", userId, "agentX", "子任务",
                 subagent_id=subagentId, parent_session_id="s-parent")
    store.claim_next("member-x")


def test_admin_reads_events_without_ownership_row(tmp_path):
    store = AgentRunStore(tmp_path / "runs.db")
    appendRunEvent("swarm_evt_a", "spawned", {"task": "t"})
    for client in _makeClient(store, {"user_id": "admin", "role": "admin"}):
        resp = client.get("/chat/subagents/swarm_evt_a/events")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["count"] == 1 and data["events"][0]["type"] == "spawned"


def test_owner_reads_own_events(tmp_path):
    store = AgentRunStore(tmp_path / "runs.db")
    _seedRun(store, "swarm_evt_b", "u1")
    first = appendRunEvent("swarm_evt_b", "spawned", {"task": "t"})
    appendRunEvent("swarm_evt_b", "terminal", {"status": "completed"}, causationId=first)
    for user in ({"user_id": "u1", "role": "user"}, {"user_id": "u9", "role": "admin"}):
        for client in _makeClient(store, user):
            resp = client.get("/chat/subagents/swarm_evt_b/events")
            assert resp.status_code == 200
            events = resp.json()["data"]["events"]
            assert [e["type"] for e in events] == ["spawned", "terminal"]
            assert events[1]["causation_id"] == events[0]["event_id"]


def test_non_owner_and_missing_row_fail_closed(tmp_path):
    store = AgentRunStore(tmp_path / "runs.db")
    _seedRun(store, "swarm_evt_c", "u1")
    # 非管理员：他人 run 403；台账无行 fail-closed 403
    for client in _makeClient(store, {"user_id": "u2", "role": "user"}):
        assert client.get("/chat/subagents/swarm_evt_c/events").status_code == 403
        assert client.get("/chat/subagents/swarm_norow/events").status_code == 403
    # 管理员：他人 run 与无行 run 均可读（无行=空账本）
    for client in _makeClient(store, {"user_id": "u9", "role": "admin"}):
        assert client.get("/chat/subagents/swarm_evt_c/events").status_code == 200
        assert client.get("/chat/subagents/swarm_norow/events").status_code == 200


# ── M5：after_seq 游标 → 全局事件库 replayThrough（A2 能力的生产消费点） ───


def _seedMirrorStore(tmp_path, monkeypatch):
    from neurova.agent import swarm as swarm_mod
    from neurova.agent.swarm_event_store import SwarmEventStore

    store = SwarmEventStore(str(tmp_path / "evt_mirror.db"))
    monkeypatch.setattr(swarm_mod, "_EVENT_STORE", store)
    return store


def test_events_after_seq_reads_store_replay(tmp_path, monkeypatch):
    store = _seedMirrorStore(tmp_path, monkeypatch)
    store.append("swarm_evt_r", "spawned", {"task": "t"})
    store.append("swarm_evt_r", "terminal", {"status": "completed"})
    store2 = AgentRunStore(tmp_path / "runs.db")
    for client in _makeClient(store2, {"user_id": "admin", "role": "admin"}):
        resp = client.get("/chat/subagents/swarm_evt_r/events?after_seq=1")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["mode"] == "replay"
        assert data["high_water"] == 2
        assert data["degraded"] is False
        assert [e["seq"] for e in data["events"]] == [2]


def test_events_after_seq_too_old_degrades_honestly(tmp_path, monkeypatch):
    store = _seedMirrorStore(tmp_path, monkeypatch)
    store.append("swarm_evt_d", "spawned", {"task": "t"})
    store.markPrunedThrough(store.highWater())  # 游标若低于边界 → 必须降级
    store2 = AgentRunStore(tmp_path / "runs.db")
    for client in _makeClient(store2, {"user_id": "admin", "role": "admin"}):
        resp = client.get("/chat/subagents/swarm_evt_d/events?after_seq=0")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["mode"] == "replay"
        assert data["degraded"] is True and data["events"] == [], \
            "游标过旧必须诚实降级（绝不部分回放）"
